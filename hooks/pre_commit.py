#!/usr/bin/env python3
"""
PreToolUse hook for Bash — intercepts git commit commands.

Replaces pre_commit_gate.sh with Python for stability.

Flow:
  1. Check if the Bash command is a git commit
  2. If not → exit 0 (pass through)
  3. If git push → show reminder (exit 0)
  4. Get staged Python files
  5. Run standard check with spec validation
  6. Exit 0 (pass) or exit 2 (block with feedback)

Exit codes:
  0 = allow
  2 = block (quality gate failed)
"""

import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

# Add harness to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.hook_runner import run_hook, HookContext, HookResult

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue"}


def _test_marker_path(project_root: str) -> str:
    """Return path to test-executed marker file for this project."""
    h = hashlib.md5(project_root.encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"harness_tested_{h}")


def _deploy_marker_path(project_root: str) -> str:
    """Return path to deploy-executed marker file for this project."""
    h = hashlib.md5(project_root.encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"harness_deployed_{h}")


def _is_test_command(cmd: str) -> bool:
    """Check if command is a test execution command.

    Only counts real project tests, not random scripts in /tmp.
    """
    # Reject /tmp scripts — too easy to fake
    if "/tmp/" in cmd or "/private/tmp/" in cmd:
        return False
    patterns = [
        r'\bpytest\b',
        r'\bpython3?\s+.*\btest_',
        r'\bpython3?\s+-m\s+pytest\b',
    ]
    return any(re.search(p, cmd) for p in patterns)


# ---------------------------------------------------------------------------
# v3.2: Deep command classification — handles wrapping, chaining, and tampering
# ---------------------------------------------------------------------------

_DB_PATTERNS = [
    (r'\bDELETE\s+FROM\b', "DELETE FROM"),
    (r'\bDROP\s+(TABLE|DATABASE|INDEX)\b', "DROP"),
    (r'\bINSERT\s+INTO\b', "INSERT INTO"),
    (r'\bUPDATE\s+\w+\s+SET\b', "UPDATE SET"),
    (r'\bTRUNCATE\b', "TRUNCATE"),
]


def _classify_atom(cmd: str) -> tuple[str, str]:
    """Classify a single, unwrapped command (no shell -c, no chains).

    This is the leaf-level classifier. _classify_command calls this
    after unwrapping shell -c / python -c / chains.
    """
    cmd = cmd.strip()
    if not cmd:
        return ("safe", "")

    # DB mutation — full-text scan (catches ssh "... DELETE FROM ...")
    for pat, label in _DB_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return ("db_mutation", f"数据库变更({label})")

    # Service restart
    if ("kill" in cmd and "nohup" in cmd) or re.search(r'systemctl\s+restart', cmd):
        return ("service_restart", "服务重启")

    # SSH
    if re.match(r'^(?:\S+/)?ssh\s+', cmd):
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()
        target = ""
        skip_next = False
        for p in parts[1:]:
            if skip_next:
                skip_next = False
                continue
            if p in ("-i", "-p", "-o", "-l", "-F", "-J"):
                skip_next = True
                continue
            if p.startswith("-"):
                continue
            target = p
            break
        if target.startswith("git@"):
            return ("git_ssh", "Git SSH")
        return ("deploy_ssh", f"SSH到 {target}")

    # SCP
    if re.match(r'^(?:\S+/)?scp\s+', cmd):
        return ("deploy_scp", "SCP文件传输")

    return ("safe", "")


def _classify_command(cmd: str) -> tuple[str, str]:
    """Classify a Bash command for pipeline stage gating.

    v3.2: Handles command wrapping and chaining:
      - bash -c "ssh ..."     → unwrap and classify inner command
      - python3 -c "os.system('ssh ...')" → scan for dangerous keywords
      - true; ssh server      → split on ;/&& and classify each part
      - pipeline.json tampering → detect writes to .harness/

    Returns (category, description).
    """
    cmd = cmd.strip()
    if not cmd:
        return ("safe", "")

    # R2: Pipeline state file write protection
    # Only block actual WRITE operations to .harness/ state files.
    # Read operations (cat, grep, ls) are legitimate and must not be blocked.
    # The primary protection is settings.json deny rules (Edit/Write tools).
    # This hook catches Bash-based write attempts that deny rules can't see.
    _harness_write = r'\.harness/.*(?:>|>>|\btee\b)'  # shell redirect into .harness/
    _harness_cmd_write = r'\b(?:cp|mv|ln)\b.*\.harness/'  # file ops into .harness/
    _harness_sed = r'\bsed\s+-i\b.*\.harness/'  # in-place edit
    if re.search(_harness_write, cmd) or re.search(_harness_cmd_write, cmd) or re.search(_harness_sed, cmd):
        return ("pipeline_tamper", "篡改pipeline状态文件")

    # R3: Code file write detection via Bash redirect/sed/tee/cp/mv
    _code_redirect = r'>\s*(\S+\.(?:py|ts|tsx|js|jsx|vue))\b'
    _code_sed = r'\bsed\s+(?:-\w*i)\S*\s.*\.(?:py|ts|tsx|js|jsx|vue)\b'
    _code_tee = r'\btee\s+(?:-\w+\s+)*(\S+\.(?:py|ts|tsx|js|jsx|vue))\b'
    _code_cpmv = r'\b(?:cp|mv)\s+.*\s(\S+\.(?:py|ts|tsx|js|jsx|vue))\s*$'

    for _pat, _group in [(_code_redirect, 1), (_code_tee, 1)]:
        _m = re.search(_pat, cmd)
        if _m:
            _matched_file = _m.group(_group)
            if "/tmp/" not in _matched_file and "/private/tmp/" not in _matched_file:
                return ("code_file_write", f"通过Bash直接写入代码文件: {_matched_file}")

    _m_sed = re.search(_code_sed, cmd)
    if _m_sed:
        _matched_file = _m_sed.group(0)
        if "/tmp/" not in _matched_file and "/private/tmp/" not in _matched_file:
            return ("code_file_write", f"通过Bash直接写入代码文件: {_matched_file}")

    _m_cpmv = re.search(_code_cpmv, cmd)
    if _m_cpmv:
        _matched_file = _m_cpmv.group(1)
        if "/tmp/" not in _matched_file and "/private/tmp/" not in _matched_file:
            return ("code_file_write", f"通过Bash直接写入代码文件: {_matched_file}")

    # R1a: Unwrap shell -c "..." wrappers (bash/sh/zsh -c "inner command")
    wrapper_match = re.match(
        r'^(?:bash|sh|zsh)\s+(?:-\w*c)\s+(.+)$',
        cmd, re.DOTALL,
    )
    if wrapper_match:
        inner = wrapper_match.group(1).strip()
        # Strip outer quotes
        if (inner.startswith('"') and inner.endswith('"')) or \
           (inner.startswith("'") and inner.endswith("'")):
            inner = inner[1:-1]
        cat, desc = _classify_command(inner)  # recurse (max depth limited by cmd length)
        if cat != "safe":
            return (cat, f"{desc} (via shell -c)")

    # R1b: python3 -c "..." — scan for dangerous keywords inside Python code
    py_match = re.match(
        r'^python3?\s+(?:-\w*c)\s+(.+)$',
        cmd, re.DOTALL,
    )
    if py_match:
        inner = py_match.group(1)
        # Check for remote operations
        if re.search(r'\bssh\b|\bscp\b|\bos\.system\b|\bsubprocess\b|\bPopen\b', inner):
            return ("deploy_ssh", "Python脚本中的远程操作")
        # Check for code file writes via open()
        if re.search(r'\bopen\s*\(.*\.(?:py|ts|tsx|js|jsx|vue)', inner):
            return ("code_file_write", "Python脚本中直接写入代码文件")
        # Check for DB mutations
        for pat, label in _DB_PATTERNS:
            if re.search(pat, inner, re.IGNORECASE):
                return ("db_mutation", f"Python脚本中的{label}")
        # Pipeline state protection is handled by settings.json deny rules
        # (Edit/Write blocked) and Bash deny rules (>, >>, tee, cp, mv to .harness/).
        # No keyword scanning needed — it blocks legitimate operations like
        # writing test scripts or reading logs.

    # R1c: Split chain commands (;  &&  ||) and classify each part
    # Fix: exclude bare `&` (e.g. `2>&1` redirects) to avoid infinite recursion
    if re.search(r';|&&|\|\|', cmd):
        subcmds = re.split(r'\s*(?:;|\&\&|\|\|)\s*', cmd)
        for sub in subcmds:
            sub = sub.strip()
            if not sub:
                continue
            cat, desc = _classify_command(sub)
            if cat != "safe":
                return (cat, desc)

    # Leaf classification
    return _classify_atom(cmd)


def handle(ctx: HookContext) -> HookResult:
    """Intercept git commit and dangerous server operations."""
    # Extract command from tool_input
    command = ""
    exit_code = 0
    if isinstance(ctx.tool_input, dict):
        command = ctx.tool_input.get("command", "")
        exit_code = ctx.tool_input.get("exit_code", 0)

    if not command:
        return HookResult(exit_code=0)

    cmd_stripped = command.strip()

    # PostToolUse: only track test execution (marker writing), then pass through
    if ctx.hook_event == "PostToolUse":
        if _is_test_command(cmd_stripped) and exit_code == 0:
            try:
                marker = _test_marker_path(ctx.project_root or os.getcwd())
                with open(marker, "w") as f:
                    f.write("1")
            except Exception:
                pass  # fail-open
        return HookResult(exit_code=0)

    # --- PreToolUse logic only below ---

    # v3.1 Gap 2: Classify command for server operation control
    category, desc = _classify_command(cmd_stripped)

    if category == "git_ssh":
        return HookResult(exit_code=0)  # Always allow git SSH

    # R2: Block pipeline state tampering — must use pipeline CLI
    if category == "pipeline_tamper":
        return HookResult(
            exit_code=2,
            message=f"[harness] ❌ 禁止直接修改pipeline.json\n请使用pipeline命令：python3 -m harness.pipeline advance/retreat/reset",
        )

    if category == "code_file_write":
        return HookResult(
            exit_code=2,
            message=(
                f"[harness] ❌ {desc}\n"
                f"通过 Bash 直接修改代码文件会绕过 pre_edit 阶段检查。\n"
                f"正确做法：\n"
                f"  - 使用 Edit 工具修改文件（会触发 pre_edit hook 检查 pipeline 阶段）\n"
                f"  - 或派 Sonnet 子 Agent（model=\"sonnet\"）执行代码修改"
            ),
        )

    if category in ("deploy_ssh", "deploy_scp", "service_restart"):
        # Check test marker before allowing deploy
        marker = _test_marker_path(ctx.project_root or os.getcwd())
        if not os.path.exists(marker):
            return HookResult(
                exit_code=2,
                message=(
                    f"[harness] ❌ 检测到部署操作：{desc}\n"
                    f"但本次会话未运行任何测试。\n"
                    f"正确做法：\n"
                    f"  1. 先运行项目测试（pytest 或 python3 项目目录/test_*.py）\n"
                    f"  2. 测试通过后再执行部署命令\n"
                    f"  注意：/tmp 下的临时脚本不算测试，必须是项目内的测试文件"
                ),
            )
        try:
            from harness.pipeline import get_state
            state = get_state(ctx.project_root) if ctx.project_root else None
            if state and state.current_stage != 6:
                stage_name = {1: "SPEC", 2: "DESIGN", 3: "IMPLEMENT", 4: "REVIEW", 5: "TEST", 6: "DEPLOY"}.get(state.current_stage, "?")
                return HookResult(
                    exit_code=2,
                    message=(
                        f"[harness] ❌ 检测到部署操作：{desc}\n"
                        f"当前在 Stage {state.current_stage} ({stage_name})，部署只允许在 DEPLOY(6) 阶段。\n"
                        f"正确做法：\n"
                        f"  1. 用 standard-deploy 路由启动 pipeline（包含 DEPLOY 阶段）：\n"
                        f"     PYTHONPATH=~/Desktop/harness-engineering python3 -m harness.pipeline start "
                        f"--project=<项目路径> --route=standard-deploy\n"
                        f"  2. 完成 IMPLEMENT→REVIEW→TEST 后，pipeline 自动进入 DEPLOY 阶段\n"
                        f"  3. 在 DEPLOY 阶段执行部署命令"
                    ),
                )
            if state:
                # Write deploy marker so stop_check can detect deploy-without-test
                try:
                    dm = _deploy_marker_path(ctx.project_root or os.getcwd())
                    with open(dm, "w") as f:
                        f.write("1")
                except Exception:
                    pass
                return HookResult(exit_code=0, message=f"[harness] ⚠️ 部署操作：{desc} (Stage {state.current_stage})")
            # 没有活跃pipeline时也拦截SSH部署操作（防止跳过pipeline直接改服务器）
            if state is None:
                return HookResult(
                    exit_code=2,
                    message=(
                        f"[harness] ❌ 检测到部署操作：{desc}\n"
                        f"当前没有活跃的 pipeline。\n"
                        f"正确做法：\n"
                        f"  1. 启动包含 DEPLOY 阶段的 pipeline：\n"
                        f"     PYTHONPATH=~/Desktop/harness-engineering python3 -m harness.pipeline start "
                        f"--project=<项目路径> --route=standard-deploy --desc=\"描述\"\n"
                        f"  2. 走完 SPEC→IMPLEMENT→REVIEW→TEST→DEPLOY 流程\n"
                        f"  3. 在 DEPLOY(6) 阶段执行部署命令"
                    ),
                )
        except Exception:
            return HookResult(
                exit_code=2,
                message=(
                    f"[harness] ❌ 检测到部署操作：{desc}\n"
                    f"Pipeline状态检查异常，为安全起见拦截部署操作。"
                ),
            )

    if category == "db_mutation":
        try:
            from harness.pipeline import get_state
            state = get_state(ctx.project_root) if ctx.project_root else None
            # DB writes: IMPLEMENT(3)阶段允许（开发需要）, DEPLOY(6)阶段允许（迁移需要）
            # TEST(5)阶段只允许SELECT查询（已在_classify_atom中，SELECT不匹配db_mutation）
            if state and state.current_stage not in (3, 6):
                stage_name = {1: "SPEC", 2: "DESIGN", 3: "IMPLEMENT", 4: "REVIEW", 5: "TEST", 6: "DEPLOY"}.get(state.current_stage, "?")
                return HookResult(
                    exit_code=2,
                    message=f"[harness] ❌ 检测到{desc}\n当前在 Stage {state.current_stage} ({stage_name})，数据库变更只允许在 IMPLEMENT(3) 或 DEPLOY(6) 阶段",
                )
            if state:
                return HookResult(exit_code=0, message=f"[harness] ⚠️ {desc} (Stage {state.current_stage})")
        except Exception:
            pass  # Fail-open

    # Only intercept git commit (exact match, not git commit-tree etc.)
    parts = cmd_stripped.split()
    is_git_commit = len(parts) >= 2 and parts[0] == "git" and parts[1] == "commit"

    if not is_git_commit:
        # Show reminder for git push
        if cmd_stripped.startswith("git push"):
            return HookResult(
                exit_code=0,
                message="[harness] ⚠️ 即将 git push，请确认：1) 测试通过 2) 无未提交改动 3) 分支正确",
            )
        return HookResult(exit_code=0)

    # Get staged Python files
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, timeout=10,
            cwd=ctx.project_root or None,
        )
        staged_files = [
            f.strip() for f in result.stdout.splitlines()
            if f.strip() and Path(f.strip()).suffix.lower() in CODE_EXTS
        ]
    except Exception:
        # Can't get staged files → allow commit (fail-open)
        return HookResult(exit_code=0)

    if not staged_files:
        return HookResult(exit_code=0)  # No code files staged

    # 检测是否有 TS/Vue 文件，运行 tsc 类型检查
    ts_files = [f for f in staged_files if Path(f).suffix.lower() in {".ts", ".tsx", ".vue"}]
    if ts_files:
        project_root = ctx.project_root or os.getcwd()
        try:
            tsc_result = subprocess.run(
                ["npx", "tsc", "--noEmit"],
                capture_output=True, text=True, timeout=30,
                cwd=project_root
            )
            if tsc_result.returncode != 0:
                errors = tsc_result.stdout.strip()[:500]
                return HookResult(
                    exit_code=2,
                    message=f"[harness] ❌ TypeScript 类型检查失败:\n{errors}"
                )
        except subprocess.TimeoutExpired:
            print("[harness] ⚠️ tsc --noEmit 超时(30s)，跳过类型检查")
        except FileNotFoundError:
            print("[harness] ⚠️ npx/tsc 不可用，跳过类型检查")

    # Make paths absolute
    root = ctx.project_root or os.getcwd()
    abs_files = [
        os.path.join(root, f) if not os.path.isabs(f) else f
        for f in staged_files
    ]

    # Find spec for validation
    from harness.spec_file import find_spec
    spec_path = find_spec(root)

    # Run standard check
    from harness.runner import check_standard
    report = check_standard(abs_files, test_cmd=None)

    if report.passed:
        score = f"{report.total_score:.0f}分"
        return HookResult(exit_code=0, message=f"[harness] ✅ commit质量检查通过 ({len(abs_files)}个文件, {score})")

    # Failed → generate feedback
    from harness.feedback import generate_feedback, feedback_to_text
    from harness.reward import RewardConfig
    feedback = generate_feedback(report, RewardConfig())
    text = feedback_to_text(feedback)

    return HookResult(exit_code=2, message=f"[harness] ❌ commit质量检查未通过\n{text}")


if __name__ == "__main__":
    sys.exit(run_hook(handle, hook_type="pre_commit", fail_closed=True))
