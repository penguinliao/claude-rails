#!/usr/bin/env python3
"""
Stop hook — detect procrastination + notify PM when pipeline completes.

Two responsibilities:
  1. Detect deflection patterns ("建议你手动...", "超出范围")
  2. When pipeline Stage 5 (TEST) is complete, send macOS notification to PM

Exit codes:
  0 = pass (normal stop)
  2 = block (procrastination detected)
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

# Add harness to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.hook_runner import HookContext, HookResult, run_hook


# ---------------------------------------------------------------------------
# Escape valves — prevent legitimate "pausing" from being flagged as deflection
# ---------------------------------------------------------------------------

def _is_asking_user(response: str) -> bool:
    """Escape A: Claude is asking the user a question — allow stop."""
    stripped = response.rstrip()
    if not stripped:
        return False
    last_char = stripped[-1]
    if last_char in ("?", "\uff1f"):
        return True
    tail = stripped[-200:]
    # Choice prompts like Y/N, X/Y
    tail_upper = tail.upper()
    for token in ("Y/N", "X/Y"):
        if token in tail_upper:
            return True
    # Chinese question phrasing + question mark
    has_question_mark = ("?" in tail) or ("\uff1f" in tail)
    if has_question_mark:
        for word in ("\u8bf7", "\u8fd8\u662f", "\u8981\u4e0d\u8981", "\u9009\u62e9"):
            if word in tail:
                return True
    return False


def _is_waiting_for_background(response: str) -> bool:
    """Escape B: Claude is waiting for a background agent — allow stop."""
    if not response or len(response) >= 300:
        return False

    # Common Chinese waiting phrases (short-circuit)
    _wait_zh_substrings = (
        "\u7b49\u5f85",       # 等待
        "\u7a0d\u7b49",       # 稍等
        "\u7a0d\u5019",       # 稍候
        "\u5904\u7406\u4e2d", # 处理中
        "\u6b63\u5728\u5904\u7406",  # 正在处理
        "\u8bf7\u7a0d\u5019",        # 请稍候
        "\u7b49\u6211",              # 等我
    )
    for s in _wait_zh_substrings:
        if s in response:
            return True

    # Common English waiting phrases (short-circuit)
    lower = response.lower()
    for s in ("processing", "in progress", "hang on", "one moment"):
        if s in lower:
            return True

    # Original logic: Chinese "等...{keyword}" pattern
    _wait_pattern = re.compile(
        r"\u7b49[\u4e00-\u9fa5A-Za-z_]{0,30}"
        r"(Agent|\u5b8c\u6210|\u5ba1\u67e5|\u540e\u53f0|finish|background)",
        re.IGNORECASE,
    )
    if _wait_pattern.search(response):
        return True
    if "waiting for" in lower or "awaiting" in lower:
        return True
    return False


def _loop_marker_path(project_root: str, response: str) -> str:
    """Return the /tmp path for a loop-breaker marker for this (project, response) pair.

    The response is normalised (collapsed whitespace) before hashing so that
    trailing spaces / newlines do not produce different markers.
    """
    normalized = re.sub(r"\s+", " ", response.strip())
    h_proj = hashlib.md5(project_root.encode()).hexdigest()[:12]
    h_resp = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"harness_stopblock_{h_proj}_{h_resp}")


def _loop_breaker_should_release(project_root: str, response: str) -> bool:
    """Escape C: if the same response has been blocked >=3 times, release it."""
    marker = _loop_marker_path(project_root, response)
    try:
        with open(marker) as fh:
            count = int(fh.read().strip())
    except (OSError, ValueError):
        count = 0
    new_count = count + 1
    if new_count >= 3:
        try:
            os.remove(marker)
        except OSError:
            pass
        return True
    try:
        with open(marker, "w") as fh:
            fh.write(str(new_count))
    except OSError:
        pass
    return False


def _clear_loop_marker(project_root: str, response: str) -> None:
    """Delete the loop-breaker marker for this (project, response) pair."""
    try:
        os.remove(_loop_marker_path(project_root, response))
    except OSError:
        pass


def _log_pipeline_decision(
    project_root: str, decision: str, stage_name: str, response: str
) -> None:
    """Append a pipeline-incomplete decision telemetry line to .harness/hook.log (fail-open)."""
    try:
        log_path = os.path.join(project_root, ".harness", "hook.log")
        resp_head = response[:80].replace("\n", " ")
        with open(log_path, "a") as fh:
            fh.write(
                f"[stop_check] pipeline_incomplete decision={decision}"
                f" stage={stage_name} resp_head={resp_head}\n"
            )
    except (OSError, IOError):
        pass


def _test_marker_path(project_root: str) -> str:
    """Return path to test-executed marker file."""
    h = hashlib.md5(project_root.encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"harness_tested_{h}")


def _deploy_marker_path(project_root: str) -> str:
    """Return path to deploy-executed marker file."""
    h = hashlib.md5(project_root.encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"harness_deployed_{h}")


# Deflection patterns (regex, case-insensitive)
_DEFLECTION_PATTERNS = [
    re.compile(r"你说.*开始.*动手", re.IGNORECASE),
    re.compile(r"你确认.*要改", re.IGNORECASE),
    re.compile(r"建议.*开.*新.*对话", re.IGNORECASE),
    re.compile(r"建议.*手动", re.IGNORECASE),
    re.compile(r"超出.*范围", re.IGNORECASE),
    re.compile(r"后续.*跟进", re.IGNORECASE),
]


def _notify_pm_if_pipeline_complete(project_root: str) -> str:
    """Check if pipeline is at its last stage and completed. If so, notify PM.

    v3.2: Dynamic last stage — works with standard (last=5) and *-deploy (last=6) routes.
    """
    try:
        from harness.pipeline import STAGE_NAMES, get_state

        state = get_state(project_root)
        if state is None:
            return ""

        # Determine last stage from route (don't hardcode 5)
        last_stage = state.route_stages[-1] if state.route_stages else 5
        if state.current_stage != last_stage:
            return ""

        # Check if the last history entry for this stage is PASS
        for entry in reversed(state.history):
            if entry.stage == last_stage and entry.status == "PASS":
                stage_name = STAGE_NAMES.get(last_stage, str(last_stage))
                subprocess.Popen(
                    ["osascript", "-e",
                     f'display notification "Pipeline complete - Stage {last_stage} {stage_name} passed" '
                     'with title "Harness Pipeline" sound name "Glass"'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return f"\n[harness] Pipeline Stage {last_stage} {stage_name} passed — PM notified for review"
            if entry.stage == last_stage:
                break  # Found last stage but not PASS

        return ""
    except Exception:
        return ""  # fail-open


def handle(ctx: HookContext) -> HookResult:
    """Check for procrastination in assistant response + pipeline completion."""

    # Try to extract last_assistant_message
    response = ""
    try:
        if ctx.raw_stdin:
            data = json.loads(ctx.raw_stdin)
            response = data.get("last_assistant_message", "")
    except (json.JSONDecodeError, TypeError):
        pass

    # Pipeline completion check — block stop if pipeline is not finished
    try:
        from harness.pipeline import STAGE_NAMES, get_state
        state = get_state(ctx.project_root)
        if state is not None:
            last_stage = state.route_stages[-1] if state.route_stages else 5
            # Check if pipeline is truly complete.
            # Only look at the LAST history entry for the last_stage (not any()).
            # This prevents retreat from being fooled by old PASS records.
            pipeline_complete = False
            for entry in reversed(state.history):
                if entry.stage == last_stage:
                    pipeline_complete = entry.status == "PASS"
                    break
            if not pipeline_complete:
                stage_name = STAGE_NAMES.get(state.current_stage, str(state.current_stage))
                _incomplete_msg = (
                    f"[harness] \u274c Pipeline \u672a\u5b8c\u6210\uff08\u5f53\u524d Stage "
                    f"{state.current_stage} {stage_name}\uff09\uff0c"
                    f"\u8bf7\u7ee7\u7eed\u63a8\u8fdb\u5230 TEST \u901a\u8fc7\u540e\u518d\u505c\u6b62\u3002\n"
                    f"\u4e0b\u4e00\u6b65\uff1a\u5b8c\u6210\u5f53\u524d\u9636\u6bb5\u540e\u8fd0\u884c "
                    f"python3 -m harness.pipeline advance"
                )
                # Evaluate escape valves only when response is non-empty
                if response:
                    if _is_asking_user(response):
                        _clear_loop_marker(ctx.project_root, response)
                        _log_pipeline_decision(ctx.project_root, "bypass_A", stage_name, response)
                        # fall through — downstream deploy/deflection checks continue
                    elif _is_waiting_for_background(response):
                        _clear_loop_marker(ctx.project_root, response)
                        _log_pipeline_decision(ctx.project_root, "bypass_B", stage_name, response)
                        # fall through
                    elif _loop_breaker_should_release(ctx.project_root, response):
                        _log_pipeline_decision(ctx.project_root, "bypass_C", stage_name, response)
                        # fall through
                    else:
                        _log_pipeline_decision(ctx.project_root, "block", stage_name, response)
                        return HookResult(exit_code=2, message=_incomplete_msg)
                else:
                    _log_pipeline_decision(ctx.project_root, "block", stage_name, "")
                    return HookResult(exit_code=2, message=_incomplete_msg)
    except Exception:
        pass  # fail-open: pipeline check failure should not block normal stop

    # Check pipeline completion and notify PM
    pipeline_msg = _notify_pm_if_pipeline_complete(ctx.project_root)

    # Deploy-without-test detection — marker-based, no text scanning
    # pre_commit.py writes deploy marker when a deploy command is allowed through
    deploy_marker = _deploy_marker_path(ctx.project_root)
    test_marker = _test_marker_path(ctx.project_root)
    if os.path.exists(deploy_marker) and not os.path.exists(test_marker):
        return HookResult(
            exit_code=2,
            message=(
                "[harness] ❌ 本次会话执行了部署操作但未运行测试（未运行测试）。\n"
                "请先运行测试验证功能，再停止。"
                f"{pipeline_msg}"
            ),
        )

    if not response:
        return HookResult(exit_code=0, message=f"[harness] stop OK{pipeline_msg}")

    # Check for deflection patterns
    for pattern in _DEFLECTION_PATTERNS:
        if pattern.search(response):
            return HookResult(
                exit_code=2,
                message=f"[harness] deflection detected - continue working, don't push tasks to user{pipeline_msg}",
            )

    return HookResult(exit_code=0, message=f"[harness] stop OK{pipeline_msg}")


if __name__ == "__main__":
    sys.exit(run_hook(handle, hook_type="stop_check", fail_closed=False))
