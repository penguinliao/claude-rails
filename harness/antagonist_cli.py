"""Antagonist CLI 入口。

用法：
    python3 -m harness.antagonist_cli run --project=<path>

退出码：
    0 = PASS（连续 3 轮 P0/P1=0）
    1 = FAIL（本轮发现 P0/P1，建议 retreat）
    2 = ESCALATE（20 轮上限或同 issue 3 次未修）
    3 = 配置或网络错误
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from harness import antagonist

logger = logging.getLogger("harness.antagonist_cli")


_GIT_ENV_DENYLIST = (
    # API keys（不必传给 git）
    "DEEPSEEK_API_KEY", "QWEN_API_KEY", "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY", "DEEPSEEK_MODEL", "QWEN_MODEL",
    # P1 防御深度（独立审查 R-0503 R9 DeepSeek 发现）：
    # load_env 已拦 GIT_*，但若 PM 在 shell 直接 export，os.environ 仍有；
    # subprocess 传 GIT_EXEC_PATH/GIT_SSH_COMMAND 给 git 子进程会被劫持
    "GIT_EXEC_PATH", "GIT_SSH_COMMAND", "GIT_SSL_CAINFO",
    "GIT_TEMPLATE_DIR", "GIT_CONFIG", "GIT_PROXY_COMMAND",
    # P1 防 GIT_DIR/GIT_WORK_TREE 注入（独立审查 R-0503 R11 DeepSeek 发现）：
    # 攻击者 export GIT_DIR=/恶意/repo/.git 让 git diff 看恶意 repo 的"完美代码"，
    # antagonist 审错代码绕过所有 P0/P1 阻断
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
    "HOME",
    # P0 防 GIT_CONFIG_PARAMETERS 系列注入（独立审查 R-0503 R15 DeepSeek 发现）：
    # git 2.31+ 支持通过环境变量动态注入 config，可设置 core.hooksPath 让 git
    # 跑恶意 hook → RCE。GIT_CONFIG_COUNT/KEY/VALUE 系列同理。
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM", "GIT_TRACE", "GIT_TRACE2",
    "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "DISPLAY",
)


def _run_git_diff(project_root: Path) -> str:
    """跑 ``git diff HEAD`` 拿改动；失败返回空串。

    P1 防 UnicodeDecodeError 漏接（独立审查 R-0503 Opus）：
    git diff 含二进制/非 UTF-8 内容时 text=True 会抛 UnicodeDecodeError
    （ValueError 子类，不是 OSError），穿透到 cmd_run 抛 traceback exit 1。

    P1 防 API key 泄漏给 subprocess（独立审查 R-0503 第四轮 DeepSeek）：
    git 不需要 DEEPSEEK_API_KEY 等敏感 env，传过去是不必要的攻击面。
    用过滤后的 env 调 subprocess。
    """
    # P1 防 LD_*/DYLD_* 动态链接器注入透传（独立审查 R-0503 R12 DeepSeek 发现）：
    # _GIT_ENV_DENYLIST 只列了固定 key，但 LD_PRELOAD/LD_LIBRARY_PATH/DYLD_*
    # 这类前缀模式必须 startswith 检测才完整
    safe_env = {
        k: v for k, v in os.environ.items()
        if k not in _GIT_ENV_DENYLIST
        and not k.startswith(("LD_", "DYLD_"))
    }
    # P0 防 PATH 污染 RCE（独立审查 R-0503 R19 DeepSeek 发现）：
    # subprocess 走 PATH 查 git，攻击者污染 PATH → 恶意 git → RCE。
    # 用 shutil.which 在当前 PATH 下找 git 绝对路径，subprocess 用绝对路径 +
    # 标准化 PATH 仅含系统路径（避免 PM shell 中 PATH 已被污染影响子进程）
    import shutil
    git_path = shutil.which("git") or "/usr/bin/git"
    safe_env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    try:
        result = subprocess.run(
            [git_path, "diff", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            errors="replace",  # 非 UTF-8 字节用 ? 替代而非抛异常
            env=safe_env,
        )
        # P0 防 git 异常静默假 PASS（独立审查 R-0503 R16 DeepSeek 发现）：
        # git diff returncode=0 表示无差异，1 表示有差异，其他（如 128）= 真错误
        # （仓库损坏/权限不足等）。静默返 "" 让 antagonist 仅审 spec → 假 PASS。
        if result.returncode not in (0, 1):
            raise RuntimeError(
                f"git diff 异常退出 (returncode={result.returncode}): "
                f"{(result.stderr or '')[:200]}"
            )
        return result.stdout or ""
    except FileNotFoundError as exc:
        # P0 防 git 不存在静默假 PASS（独立审查 R-0503 R14 DeepSeek 发现）：
        # CI 环境不装 git 时静默返 "" → antagonist 仅审 spec → 假 PASS。
        # FileNotFoundError 不属于"git 跑了但失败"应 raise 让 cli exit 3
        raise RuntimeError(
            f"git 命令不存在（FileNotFoundError）；antagonist 必须能跑 git diff 才能审代码改动: {exc}"
        ) from exc
    except (subprocess.SubprocessError, OSError, UnicodeDecodeError) as exc:
        logger.warning("git diff failed: %s", exc)
        return ""


def _historical_unfixed(state: antagonist.AntagonistState) -> list[dict]:
    return [
        i for i in state.all_issues
        if not i.get("fixed_round")
    ]


def _write_round_report(
    project_root: Path,
    state: antagonist.AntagonistState,
    new_issues: list[antagonist.Issue],
    rotated_angles: list[str],
    exit_code: int,
    reason: str,
) -> Path:
    """写本轮人类可读 report。"""
    report_dir = project_root / ".harness"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"antagonist_report_round_{state.round}.md"

    p0 = sum(1 for i in new_issues if i.severity == "P0")
    p1 = sum(1 for i in new_issues if i.severity == "P1")
    p2 = sum(1 for i in new_issues if i.severity == "P2")
    p3 = sum(1 for i in new_issues if i.severity == "P3")

    lines: list[str] = []
    lines.append(f"# Antagonist Round {state.round} Report")
    lines.append("")
    lines.append(f"- 时间: {state.started_at}")
    lines.append(f"- 本轮强制角度: {', '.join(rotated_angles) or '(无)'}")
    lines.append(f"- 本轮 issue 计数: P0={p0} P1={p1} P2={p2} P3={p3}")
    lines.append(f"- consecutive_pass: {state.consecutive_pass}/3")
    lines.append(f"- 决策: exit_code={exit_code} reason={reason}")
    lines.append("")
    lines.append("## 本轮 issue 列表")
    lines.append("")
    if new_issues:
        for i in new_issues:
            lines.append(f"### [{i.severity}] {i.file}:{i.line}")
            lines.append("")
            lines.append(f"- problem: {i.problem}")
            lines.append(f"- why_blocking: {i.why_blocking}")
            lines.append(f"- reproduce: {i.reproduce}")
            lines.append("")
    else:
        lines.append("(本轮无 issue)")
        lines.append("")

    lines.append("## 累计未 fixed issue")
    lines.append("")
    unfixed = _historical_unfixed(state)
    if unfixed:
        for h in unfixed:
            lines.append(
                f"- [{h.get('severity')}] {h.get('file')}: {h.get('problem')} "
                f"(R{h.get('first_seen_round')}~R{h.get('last_seen_round')})"
            )
    else:
        lines.append("(无)")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def cmd_run(project: str) -> int:
    project_root = Path(project).expanduser().resolve()
    if not project_root.exists():
        print(f"[antagonist] ERROR: project 路径不存在: {project_root}", file=sys.stderr)
        return 3

    # 1. load_env
    antagonist.load_env(str(project_root))

    # 2. 检查 API key
    try:
        clients = antagonist.get_clients()
    except RuntimeError as exc:
        print(f"[antagonist] ERROR: {exc}", file=sys.stderr)
        return 3

    # 3. 读 spec.md
    spec_path = project_root / ".harness" / "spec.md"
    if not spec_path.exists():
        print(
            f"[antagonist] ERROR: 未找到 {spec_path}，请先走 SPEC 阶段",
            file=sys.stderr,
        )
        return 3
    try:
        # P1 防 UnicodeDecodeError 漏接（独立审查 R-0503 R11 Sonnet 发现）：
        # spec.md 含非 UTF-8 字节时穿透到 main exit 1（误判 FAIL），统一 exit 3
        spec_text = spec_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"[antagonist] ERROR: 读 spec.md 失败: {exc}", file=sys.stderr)
        return 3

    # 4. git diff（git 不存在 FileNotFoundError → raise → cli exit 3）
    try:
        diff_text = _run_git_diff(project_root)
    except RuntimeError as exc:
        print(f"[antagonist] ERROR: {exc}", file=sys.stderr)
        return 3

    # 5. load state
    state_path = project_root / ".harness" / "antagonist_state.json"
    try:
        state = antagonist.load_state(state_path)
    except antagonist.StateCorruptError as exc:
        print(f"[antagonist] ERROR: {exc}", file=sys.stderr)
        print("[antagonist] state 已备份；请检查 .bak 文件后重试", file=sys.stderr)
        return 3

    # 6. 选角度
    rotated_angles = antagonist.pick_angles(state.rotation_history)

    # 7. 组 prompt
    historical = _historical_unfixed(state)
    system_prompt, user_prompt = antagonist.assemble_prompt(
        spec_text=spec_text,
        diff_text=diff_text,
        historical_issues=historical,
        rotated_angles=rotated_angles,
    )

    # 8. 调多家 antagonist API（跨家族监督的核心：≥2 家不同公司模型互相挑刺）
    issues_per_family: dict[str, list[antagonist.Issue]] = {}
    errors_per_family: dict[str, str] = {}
    for c in clients:
        try:
            raw = c.chat(system=system_prompt, user=user_prompt)
        except RuntimeError as exc:
            errors_per_family[c.family] = f"API: {exc}"
            print(f"[antagonist] WARN: {c.family} API 失败: {exc}", file=sys.stderr)
            continue
        try:
            issues_per_family[c.family] = antagonist.parse_issues(raw)
        except antagonist.LLMOutputUnparseable as exc:
            errors_per_family[c.family] = f"parse: {exc}"
            print(f"[antagonist] WARN: {c.family} 输出无法解析: {exc}", file=sys.stderr)

    # P1 防 partial-failure 假 PASS（独立审查 R-0503 Sonnet 发现）：
    # 任何一家失败 → exit 3，不能"至少一家成功就继续"。
    # 否则 garbage/超时家族被静默忽略，跨家族监督退化为单家独角戏，
    # 配合 P1#3 raise 的设计反而成为新的假 PASS 入口（其他家返合法空）。
    if errors_per_family:
        print(
            f"[antagonist] ERROR: {len(errors_per_family)}/{len(clients)} 家 antagonist 失败："
            f"{errors_per_family}。任何一家失败都不能继续（防 partial-failure 假 PASS）。",
            file=sys.stderr,
        )
        return 3
    if not issues_per_family:
        print(
            f"[antagonist] ERROR: 所有 {len(clients)} 家 antagonist 都失败：{errors_per_family}",
            file=sys.stderr,
        )
        return 3

    # 9. 合并多家 issues 去重（同 issue 多家挑出 → 取较高 severity）
    new_issues = antagonist.merge_issues_dedup(issues_per_family)
    family_summary = ", ".join(f"{fam}={len(iss)}" for fam, iss in issues_per_family.items())
    print(f"[antagonist] 各家 issue 数: {family_summary} → 合并去重后: {len(new_issues)}")

    # 10. 更新 state
    state.rotation_history.append(rotated_angles)
    state = antagonist.update_state(state, new_issues)

    # 11. 决策
    exit_code, reason = antagonist.decide_exit(state)

    # 12. 写 report + 持久化 state（磁盘满/权限不足时优雅 exit 3）
    try:
        report_path = _write_round_report(
            project_root, state, new_issues, rotated_angles, exit_code, reason,
        )
        antagonist.save_state(state, state_path)
    except OSError as exc:
        print(
            f"[antagonist] ERROR: 写 state/report 失败（磁盘满/权限不足？）: {exc}",
            file=sys.stderr,
        )
        return 3

    p0 = sum(1 for i in new_issues if i.severity == "P0")
    p1 = sum(1 for i in new_issues if i.severity == "P1")
    p2 = sum(1 for i in new_issues if i.severity == "P2")
    p3 = sum(1 for i in new_issues if i.severity == "P3")
    verdict = {0: "PASS", 1: "FAIL", 2: "ESCALATE", 3: "ERROR", 4: "CONTINUE"}.get(exit_code, "?")
    print(
        f"[antagonist] Round {state.round}: P0={p0} P1={p1} P2={p2} P3={p3}. "
        f"consecutive_pass={state.consecutive_pass}/3. -> {verdict}"
    )
    print(f"[antagonist] reason: {reason}")
    print(f"[antagonist] report: {report_path}")
    # 让 asdict/state 引用不被 ruff 算未用
    _ = asdict(state)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    parser = argparse.ArgumentParser(prog="harness antagonist")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="跑一轮 antagonist 找茬")
    run_p.add_argument("--project", required=True, help="项目根路径")
    reset_p = sub.add_parser(
        "reset",
        help="标所有 unfixed issue 为已修（PM 修完代码后跑一次让 stuck 解锁）",
    )
    reset_p.add_argument("--project", required=True, help="项目根路径")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args.project)
    if args.cmd == "reset":
        return cmd_reset(args.project)
    return 3


def cmd_reset(project: str) -> int:
    """标所有 unfixed issue 为已修（防 stuck 永久 ESCALATE）。

    P0 修复（独立审查 R-0503 第三轮 DeepSeek 发现）：
    spec 语义"同一 issue 修 3 次仍存在才 ESCALATE"，但当前 stuck 判定基于
    consecutive_count >= 3 + fixed_round=None。一旦 stuck，PM 即使修了代码，
    重跑 antagonist 还会立刻 ESCALATE（因为 consecutive_count 仍是 3）。
    需要显式 mark-fixed 入口，让 PM 修完代码后告诉 antagonist "我修了"。
    """
    project_root = Path(project).expanduser().resolve()
    if not project_root.exists():
        print(f"[antagonist] ERROR: project 路径不存在: {project_root}", file=sys.stderr)
        return 3
    state_path = project_root / ".harness" / "antagonist_state.json"
    if not state_path.exists():
        print("[antagonist] state 文件不存在，无需 reset")
        return 0
    try:
        state = antagonist.load_state(state_path)
    except antagonist.StateCorruptError as exc:
        print(f"[antagonist] ERROR: {exc}", file=sys.stderr)
        return 3
    unfixed = [i for i in state.all_issues if not i.get("fixed_round")]
    for issue in unfixed:
        issue["fixed_round"] = state.round
    try:
        antagonist.save_state(state, state_path)
    except OSError as exc:
        print(f"[antagonist] ERROR: 写 state 失败: {exc}", file=sys.stderr)
        return 3
    print(f"[antagonist] reset OK: {len(unfixed)} 条 unfixed issue 已标 fixed_round={state.round}")
    print("[antagonist] 现在跑 antagonist run，stuck 判定会跳过这些已修 issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
