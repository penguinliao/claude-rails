#!/usr/bin/env python3
"""
harness CLI — 开发质量门禁管理工具

子命令:
  init        在当前目录初始化 harness
  status      查看当前项目 pipeline 状态
  doctor      环境健康检查
  advance     手动推进到下一阶段
  retreat     手动回退到上一阶段
  uninstall   完全卸载 harness
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# harness_cli.py 在 bin/，harness 模块在 ../harness/
HARNESS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS_ROOT))


# ---------------------------------------------------------------------------
# 颜色输出（自动检测 tty）
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()

def _c(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def success(text: str) -> str: return _c(text, "32")
def warn(text: str) -> str:    return _c(text, "33")
def error(text: str) -> str:   return _c(text, "31")
def info(text: str) -> str:    return _c(text, "36")
def bold(text: str) -> str:    return _c(text, "1")


# ---------------------------------------------------------------------------
# 子命令：init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    cwd = os.getcwd()
    harness_dir = Path(cwd) / ".harness"
    pipeline_file = harness_dir / "pipeline.json"

    if harness_dir.exists() and pipeline_file.exists():
        try:
            from harness.pipeline import get_state, STAGE_NAMES
            state = get_state(cwd)
            if state and state.current_stage > 0:
                stage_label = f"Stage {state.current_stage} ({state.stage_name})"
            else:
                stage_label = "未开始"
        except Exception:
            stage_label = "未知"
        print(warn(f"⚠️  已经初始化过了。pipeline 状态: {stage_label}"))
        print(info(f"   目录: {harness_dir}"))
        return 0

    harness_dir.mkdir(parents=True, exist_ok=True)

    initial = {
        "version": 3,
        "current_stage": 0,
        "stage_name": "",
        "task_description": "",
        "route": "standard",
        "route_stages": [],
        "history": [],
        "spec_path": None,
        "affected_files": [],
        "consecutive_fails": 0,
        "risk_level": "standard",
        "started_at": "",
        "updated_at": datetime.now().isoformat(),
    }
    pipeline_file.write_text(
        json.dumps(initial, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(success("✅ harness 已初始化！"))
    print(info(f"   项目目录: {cwd}"))
    print()
    print("   在这个项目里用 Claude Code 时会自动启用质量门禁。")
    print("   下一步：用 Claude Code 开始一个任务，harness 会自动介入。")
    print()
    print(info("   如需手动启动 pipeline:"))
    print(info('   python3 -m harness.pipeline start --route standard --desc "你的任务描述"'))
    return 0


# ---------------------------------------------------------------------------
# 子命令：status
# ---------------------------------------------------------------------------

_STAGE_EMOJI = {
    0: "⏸️ ",
    1: "📋",
    2: "🏗️ ",
    3: "💻",
    4: "🔍",
    5: "🧪",
    6: "🚀",
}

def cmd_status(args: argparse.Namespace) -> int:
    cwd = os.getcwd()
    harness_dir = Path(cwd) / ".harness"

    if not harness_dir.exists():
        print(warn("⚠️  当前目录未初始化 harness"))
        print(info("   运行 harness init 来初始化"))
        return 1

    try:
        from harness.pipeline import get_state, STAGE_NAMES
        state = get_state(cwd)
    except Exception as e:
        print(error(f"❌ 读取 pipeline 状态失败: {e}"))
        return 1

    if state is None or state.current_stage == 0:
        print(bold("━━━ Pipeline 状态 ━━━"))
        print(f"  {_STAGE_EMOJI[0]} 状态: 未开始")
        print(f"  📁 项目: {cwd}")
        print(bold("━━━━━━━━━━━━━━━━━━━━━"))
        return 0

    stage_emoji = _STAGE_EMOJI.get(state.current_stage, "❓")
    print(bold("━━━ Pipeline 状态 ━━━"))
    print(f"  {stage_emoji} 当前阶段: {bold(f'Stage {state.current_stage} ({state.stage_name})')}")
    print(f"  📝 任务: {state.task_description}")
    print(f"  🗺️  路由: {state.route}  ({' → '.join(str(s) for s in state.route_stages)})")
    print(f"  ⚠️  风险等级: {state.risk_level}")
    if state.started_at:
        print(f"  🕐 开始时间: {state.started_at[:19].replace('T', ' ')}")
    if state.consecutive_fails > 0:
        print(warn(f"  ❗ 连续失败: {state.consecutive_fails} 次"))

    if state.history:
        print()
        print("  历史记录（最近5条）:")
        for h in state.history[-5:]:
            name = STAGE_NAMES.get(h.stage, str(h.stage))
            status_icon = {
                "PASS": "✅", "FAIL": "❌", "IN_PROGRESS": "🔄", "SKIPPED": "⏭️"
            }.get(h.status, "❓")
            ts = h.timestamp[:19].replace("T", " ") if h.timestamp else ""
            note_str = f" — {h.note}" if h.note else ""
            print(f"    {status_icon} Stage {h.stage} ({name}): {h.status}{note_str}  {info(ts)}")

    spec_path = harness_dir / "spec.md"
    review_path = harness_dir / "review.md"
    if spec_path.exists() or review_path.exists():
        print()
    if spec_path.exists():
        size = spec_path.stat().st_size
        print(f"  📄 spec.md: {success('存在')} ({size} 字节)")
    if review_path.exists():
        size = review_path.stat().st_size
        print(f"  📄 review.md: {success('存在')} ({size} 字节)")

    print(bold("━━━━━━━━━━━━━━━━━━━━━"))
    return 0


# ---------------------------------------------------------------------------
# 子命令：doctor
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    print(info("🏥 运行 harness 健康检查..."))
    print()

    all_ok = True

    try:
        from harness.health import check_health
        report = check_health()
        print(report.summary())
        if report.overall == "broken":
            all_ok = False
    except Exception as e:
        print(error(f"❌ 健康检查模块加载失败: {e}"))
        all_ok = False

    print()
    print(bold("━━━ 额外环境检查 ━━━"))

    harness_home = Path.home() / ".harness"
    if harness_home.exists():
        print(success("  ✅ ~/.harness/           存在"))
    else:
        print(warn("  ⚠️  ~/.harness/           不存在（运行 install.sh 后会创建）"))

    settings_path = Path.home() / ".claude" / "settings.json"
    hooks_found = 0
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            hooks = settings.get("hooks", {})
            for event_type, groups in hooks.items():
                for group in groups:
                    for h in group.get("hooks", []):
                        if "harness" in h.get("command", ""):
                            hooks_found += 1
            if hooks_found > 0:
                print(success(f"  ✅ settings.json hooks   已配置 ({hooks_found} 个 harness hook)"))
            else:
                print(warn("  ⚠️  settings.json hooks   未配置 harness hook"))
                print(info(f"     运行: python3 {HARNESS_ROOT}/hooks/install_v2.py --apply"))
                all_ok = False
        except Exception as e:
            print(warn(f"  ⚠️  settings.json         读取失败: {e}"))
    else:
        print(warn("  ⚠️  settings.json         不存在"))
        all_ok = False

    harness_bin = Path.home() / ".local" / "bin" / "harness"
    in_path = shutil.which("harness") is not None
    if harness_bin.exists() and in_path:
        print(success("  ✅ ~/.local/bin/harness  存在且在 PATH 中"))
    elif harness_bin.exists():
        print(warn("  ⚠️  ~/.local/bin/harness  存在但不在 PATH 中"))
        print(info('     添加: export PATH="$HOME/.local/bin:$PATH"'))
    else:
        print(warn("  ⚠️  ~/.local/bin/harness  不存在（运行 install.sh 安装）"))

    print(bold("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"))
    print()
    if all_ok:
        print(success("✅ 整体状态: OK"))
        return 0
    else:
        print(warn("⚠️  整体状态: 有问题需要处理（见上方警告/错误）"))
        return 1


# ---------------------------------------------------------------------------
# 子命令：advance
# ---------------------------------------------------------------------------

def cmd_advance(args: argparse.Namespace) -> int:
    cwd = os.getcwd()
    result = subprocess.run(
        [sys.executable, "-m", "harness.pipeline", "advance"],
        cwd=str(HARNESS_ROOT),
        env={**os.environ, "HARNESS_PROJECT": cwd},
    )
    return result.returncode


# ---------------------------------------------------------------------------
# 子命令：retreat
# ---------------------------------------------------------------------------

def cmd_retreat(args: argparse.Namespace) -> int:
    cwd = os.getcwd()

    try:
        from harness.pipeline import get_state, retreat as pipeline_retreat, STAGE_NAMES
        state = get_state(cwd)
        if state is None or not state.route_stages:
            print(error("❌ 没有活跃的 pipeline"))
            return 1
        current = state.current_stage
    except Exception as e:
        print(error(f"❌ 读取 pipeline 状态失败: {e}"))
        return 1

    if args.stage is not None:
        target = args.stage
    else:
        try:
            idx = state.route_stages.index(current)
        except ValueError:
            print(error(f"❌ 当前阶段 {current} 不在路由 {state.route_stages} 中"))
            return 1
        if idx == 0:
            print(warn("⚠️  已经在第一个阶段，无法继续回退"))
            return 1
        target = state.route_stages[idx - 1]

    try:
        res = pipeline_retreat(cwd, target)
        if res.ok:
            stage_name = STAGE_NAMES.get(res.new_stage, str(res.new_stage))
            print(success(f"✅ 已回退到 Stage {res.new_stage} ({stage_name})"))
            return 0
        else:
            print(error(f"❌ 回退失败: {res.reason}"))
            return 1
    except Exception as e:
        print(error(f"❌ 回退失败: {e}"))
        return 1


# ---------------------------------------------------------------------------
# 子命令：uninstall
# ---------------------------------------------------------------------------

def _remove_harness_hooks_from_settings(settings: dict) -> dict:
    """从 settings.json 中移除 harness 管理的 hooks，保留用户自定义 hook。"""
    hooks_dir = str(HARNESS_ROOT / "hooks")
    harness_home_hooks = str(Path.home() / ".harness" / "hooks")
    harness_phrases = ["Claude 完成了", "Claude 需要你的输入"]

    def is_harness_hook(h: dict) -> bool:
        cmd = h.get("command", "")
        if hooks_dir in cmd or harness_home_hooks in cmd:
            return True
        return any(phrase in cmd for phrase in harness_phrases)

    existing_hooks = settings.get("hooks", {})
    cleaned_hooks: dict = {}

    for event_type, groups in existing_hooks.items():
        cleaned_groups = []
        for group in groups:
            user_hooks = [h for h in group.get("hooks", []) if not is_harness_hook(h)]
            if user_hooks:
                cleaned_groups.append({"matcher": group.get("matcher", ""), "hooks": user_hooks})
        if cleaned_groups:
            cleaned_hooks[event_type] = cleaned_groups

    result = dict(settings)
    result["hooks"] = cleaned_hooks
    return result


def cmd_uninstall(args: argparse.Namespace) -> int:
    harness_home = Path.home() / ".harness"
    settings_path = Path.home() / ".claude" / "settings.json"
    harness_bin = Path.home() / ".local" / "bin" / "harness"

    if not args.yes:
        print(warn("⚠️  这将完全卸载 harness，包括："))
        print(f"   - 删除 {harness_home}")
        print(f"   - 从 {settings_path} 中移除 harness hooks")
        print(f"   - 删除 {harness_bin}")
        print()
        if settings_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"settings.json.uninstall-backup.{ts}"
            print(f"   你的 settings.json 会先备份到: ~/.claude/{backup_name}")
        print()
        answer = input("继续？[y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print(info("已取消。"))
            return 0

    errors = []

    if settings_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = settings_path.parent / f"settings.json.uninstall-backup.{ts}"
        try:
            settings_text = settings_path.read_text(encoding="utf-8")
            backup_path.write_text(settings_text, encoding="utf-8")
            print(success(f"✅ settings.json 已备份到: {backup_path}"))

            settings = json.loads(settings_text)
            cleaned = _remove_harness_hooks_from_settings(settings)
            settings_path.write_text(
                json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(success("✅ 已从 settings.json 中移除 harness hooks"))
        except Exception as e:
            errors.append(f"settings.json 处理失败: {e}")
            print(error(f"❌ settings.json 处理失败: {e}"))
    else:
        print(info("ℹ️  settings.json 不存在，跳过"))

    if harness_home.exists():
        try:
            shutil.rmtree(str(harness_home))
            print(success(f"✅ 已删除 {harness_home}"))
        except Exception as e:
            errors.append(f"删除 ~/.harness/ 失败: {e}")
            print(error(f"❌ 删除 {harness_home} 失败: {e}"))
    else:
        print(info(f"ℹ️  {harness_home} 不存在，跳过"))

    if harness_bin.exists():
        try:
            harness_bin.unlink()
            print(success(f"✅ 已删除 {harness_bin}"))
        except Exception as e:
            errors.append(f"删除 harness 命令失败: {e}")
            print(error(f"❌ 删除 {harness_bin} 失败: {e}"))
    else:
        print(info(f"ℹ️  {harness_bin} 不存在，跳过"))

    print()
    if errors:
        print(warn(f"⚠️  卸载完成，但有 {len(errors)} 个错误，请手动处理"))
        return 1
    else:
        print(success("✅ 卸载完成。感谢使用 harness！"))
        return 0


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="harness — Claude Code 开发质量门禁管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  harness init        在当前项目初始化 harness
  harness status      查看当前 pipeline 状态
  harness doctor      检查环境是否正常
  harness advance     推进到下一阶段
  harness retreat     回退到上一阶段
  harness uninstall   完全卸载 harness
""",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<命令>")

    p_init = subparsers.add_parser("init", help="在当前目录初始化 harness")
    p_init.set_defaults(func=cmd_init)

    p_status = subparsers.add_parser("status", help="查看当前项目 pipeline 状态")
    p_status.set_defaults(func=cmd_status)

    p_doctor = subparsers.add_parser("doctor", help="环境健康检查")
    p_doctor.set_defaults(func=cmd_doctor)

    p_advance = subparsers.add_parser("advance", help="手动推进到下一阶段")
    p_advance.set_defaults(func=cmd_advance)

    p_retreat = subparsers.add_parser("retreat", help="手动回退到上一阶段")
    p_retreat.add_argument(
        "--stage", type=int, default=None,
        help="指定要回退到的阶段编号（不指定则自动回退上一阶段）",
    )
    p_retreat.set_defaults(func=cmd_retreat)

    p_uninstall = subparsers.add_parser("uninstall", help="完全卸载 harness")
    p_uninstall.add_argument(
        "--yes", "-y", action="store_true",
        help="跳过确认直接卸载",
    )
    p_uninstall.set_defaults(func=cmd_uninstall)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        print(info("已取消。"))
        return 130


if __name__ == "__main__":
    sys.exit(main())
