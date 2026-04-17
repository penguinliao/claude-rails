#!/usr/bin/env python3
"""
PostToolUse hook for Edit|Write — run harness quality check on edited files.

Flow:
  1. Skip non-code files (exit 0 immediately)
  2. Run quick check (ruff + bandit, <2s) for Python files
  3. Run syntax check (esbuild) for TS/JS files
  4. Run structure check for Vue files
  5. If pass → return OK (remind AI not to advance during IMPLEMENT)
  6. If fail → run fix loop (auto-fix + re-check, up to 3 iterations)
  7. If still fail → exit 2 with structured feedback for AI

Exit codes:
  0 = pass
  2 = fail (feedback shown to AI)
"""

import os
import sys
import time
from pathlib import Path

# Add harness to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.hook_runner import HookContext, HookResult, run_hook

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue"}


def _check_typescript(file_path: str) -> HookResult:
    """用 esbuild 做 TS/JS 语法检查（<1秒）"""
    import shutil
    import subprocess
    fname = Path(file_path).name

    esbuild = shutil.which("npx")
    if not esbuild:
        return HookResult(exit_code=0, message=f"[harness] ⚠️ npx 不可用，跳过 {fname} 语法检查")

    try:
        result = subprocess.run(
            ["npx", "esbuild", "--bundle=false", "--log-level=error", file_path],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(file_path).parent)
        )
        if result.returncode != 0:
            errors = result.stderr.strip() or result.stdout.strip()
            return HookResult(
                exit_code=2,
                message=f"[harness] ❌ {fname} 语法错误:\n{errors[:500]}"
            )
        return HookResult(exit_code=0, message=f"[harness] ✅ {fname} 语法检查通过")
    except subprocess.TimeoutExpired:
        return HookResult(exit_code=0, message=f"[harness] ⚠️ {fname} 语法检查超时，跳过")
    except Exception as e:
        return HookResult(exit_code=0, message=f"[harness] ⚠️ {fname} 检查异常: {e}")


def _check_vue(file_path: str) -> HookResult:
    """Vue SFC 基础结构验证"""
    fname = Path(file_path).name
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        if "<script" not in content and "<template" not in content:
            return HookResult(
                exit_code=2,
                message=f"[harness] ❌ {fname} 缺少 <script> 或 <template> 块"
            )
        return HookResult(exit_code=0, message=f"[harness] ✅ {fname} 结构验证通过")
    except Exception as e:
        return HookResult(exit_code=0, message=f"[harness] ⚠️ {fname} 验证异常: {e}")


def handle(ctx: HookContext) -> HookResult:
    """Run harness check on edited code file."""
    file_path = ctx.file_path
    ext = Path(file_path).suffix.lower() if file_path else ""
    if not file_path or ext not in CODE_EXTS:
        fname = Path(file_path).name if file_path else ""
        return HookResult(exit_code=0, message=f"[harness] {fname or 'non-code'} skipped")

    fname = os.path.basename(file_path)

    # Skip if file doesn't exist (deleted file)
    if not os.path.isfile(file_path):
        return HookResult(exit_code=0, message=f"[harness] {fname} deleted, skipped")

    # TypeScript/JavaScript 检查
    if ext in {".ts", ".tsx", ".js", ".jsx"}:
        return _check_typescript(file_path)

    # Vue 文件基础验证
    if ext == ".vue":
        return _check_vue(file_path)

    # Python 检查（原有逻辑不动）
    # Quick check first (ruff + security, <2s)
    start = time.time()
    from harness.runner import check_quick
    report = check_quick([file_path])
    elapsed = f"{time.time() - start:.1f}s"

    if report.passed:
        score = f"{report.total_score:.0f}"
        msg = f"[harness] {fname} OK ({score}pts, {elapsed})"
        # 增量更新风险等级
        try:
            from harness.pipeline import update_risk_level
            from harness.risk_analyzer import format_risk_summary
            new_level = update_risk_level(ctx.project_root)
            if new_level == "standard":
                msg += f"\n[harness] {format_risk_summary(ctx.project_root)}"
        except Exception:
            pass  # 风险分析失败不影响编辑
        # Remind: do NOT advance during IMPLEMENT — wait for Agent to finish all edits
        try:
            from harness.pipeline import get_state
            state = get_state(ctx.project_root)
            if state and state.current_stage == 3:
                msg += "\n[harness] ⚠️ 编辑通过，但不要现在advance——等子Agent完成所有修改后再推进"
        except Exception:
            pass
        return HookResult(exit_code=0, message=msg)

    # Failed quick check → run fix loop
    from harness.autofix import fix_and_report
    output = fix_and_report([file_path], mode="quick")

    if output.startswith("PASS"):
        msg = f"[harness] {fname} auto-fixed OK"
        # 增量更新风险等级
        try:
            from harness.pipeline import update_risk_level
            from harness.risk_analyzer import format_risk_summary
            new_level = update_risk_level(ctx.project_root)
            if new_level == "standard":
                msg += f"\n[harness] {format_risk_summary(ctx.project_root)}"
        except Exception:
            pass  # 风险分析失败不影响编辑
        return HookResult(exit_code=0, message=msg)

    # Still failing → return feedback for AI
    return HookResult(exit_code=2, message=f"[harness] {fname} FAIL\n{output}")


if __name__ == "__main__":
    sys.exit(run_hook(handle, hook_type="post_edit", fail_closed=True))
