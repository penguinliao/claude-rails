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

import json
import os
import re
import subprocess
import sys

# Add harness to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.hook_runner import run_hook, HookContext, HookResult


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
        from harness.pipeline import get_state, STAGE_NAMES

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
        from harness.pipeline import get_state, STAGE_NAMES
        state = get_state(ctx.project_root)
        if state is not None:
            last_stage = state.route_stages[-1] if state.route_stages else 5
            # Check if pipeline is truly complete (last stage has PASS in history)
            pipeline_complete = any(
                e.stage == last_stage and e.status == "PASS"
                for e in state.history
            )
            if not pipeline_complete:
                stage_name = STAGE_NAMES.get(state.current_stage, str(state.current_stage))
                return HookResult(
                    exit_code=2,
                    message=(
                        f"[harness] ❌ Pipeline 未完成（当前 Stage {state.current_stage} {stage_name}），"
                        f"请继续推进到 TEST 通过后再停止。\n"
                        f"下一步：完成当前阶段后运行 python3 -m harness.pipeline advance"
                    ),
                )
    except Exception:
        pass  # fail-open: pipeline check failure should not block normal stop

    # Check pipeline completion and notify PM
    pipeline_msg = _notify_pm_if_pipeline_complete(ctx.project_root)

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
    sys.exit(run_hook(handle, hook_type="stop_check"))
