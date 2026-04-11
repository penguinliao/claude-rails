#!/usr/bin/env python3
"""
PreToolUse hook for Edit|Write — pipeline stage gate.

v3.0 behavior:
  - No pipeline.json → BLOCK code writes (must start pipeline first)
  - Pipeline active, wrong stage → BLOCK code writes
  - Non-code files (md, json, yaml, toml, etc.) → always ALLOW
  - harness-engineering project itself → always ALLOW (can't lock itself out)

Exit codes:
  0 = allow (pass through)
  2 = block (with reason shown to AI)
"""

import os
import sys

# Add harness to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.hook_runner import run_hook, HookContext, HookResult


def handle(ctx: HookContext) -> HookResult:
    """Check if code write is allowed in current pipeline stage."""
    from harness.pipeline import is_code_write_allowed, get_state, STAGE_NAMES
    import pathlib as _pl

    fname = os.path.basename(ctx.file_path) if ctx.file_path else ""
    allowed, reason = is_code_write_allowed(ctx.project_root, ctx.file_path)

    if not allowed:
        return HookResult(exit_code=2, message=f"[harness] {fname} blocked\n{reason}")

    # Show pipeline stage context if active
    state = get_state(ctx.project_root) if ctx.project_root else None

    # 保护 spec.md 和 review.md 只在对应阶段可编辑
    basename = _pl.Path(ctx.file_path).name if ctx.file_path else ""
    if basename == "spec.md" and ".harness" in (ctx.file_path or ""):
        if state and state.current_stage != 1:  # 只在 SPEC 阶段可写
            return HookResult(exit_code=2, message="[harness] ❌ spec.md 只能在 SPEC 阶段(1)编辑")
    if basename == "review.md" and ".harness" in (ctx.file_path or ""):
        if state and state.current_stage != 4:  # 只在 REVIEW 阶段可写
            return HookResult(exit_code=2, message="[harness] ❌ review.md 只能在 REVIEW 阶段(4)编辑")

    if state:
        stage_name = STAGE_NAMES.get(state.current_stage, "?")

        # v3.2: Spec-based scope check — block edits outside spec's file list
        if state.current_stage == 3 and ctx.file_path:
            try:
                import pathlib as _pl
                # Harness-engineering self-edit exemption (can't lock itself out)
                _harness_dir = str(_pl.Path(__file__).resolve().parent.parent)
                if str(_pl.Path(ctx.file_path).resolve()).lower().startswith(_harness_dir.lower()):
                    pass  # Skip spec scope check for harness-engineering itself
                else:
                    _ext = _pl.Path(ctx.file_path).suffix.lower()
                    _CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".html", ".css",
                                  ".scss", ".svelte", ".go", ".rs", ".java", ".kt", ".swift"}
                    if _ext not in _CODE_EXTS:
                        pass  # Non-code files always pass spec scope check
                    else:
                        from harness.spec_file import find_spec, extract_affected_files
                        spec_path = find_spec(ctx.project_root)
                        if spec_path:
                            affected = extract_affected_files(spec_path)
                            if affected:
                                rel_path = os.path.relpath(ctx.file_path, ctx.project_root)
                                basename = os.path.basename(ctx.file_path)
                                if not any(basename in af or rel_path in af for af in affected):
                                    return HookResult(
                                        exit_code=2,
                                        message=f"[harness] ❌ {basename} 不在spec.md影响文件列表中\n"
                                                f"spec列出的文件：{', '.join(affected[:5])}\n"
                                                f"如果确实需要修改，请先更新spec.md的影响文件部分",
                                    )
            except Exception:
                pass  # Fail-open: spec parsing error should never block edits

        return HookResult(exit_code=0, message=f"[harness] {fname} OK (Stage {state.current_stage} {stage_name})")

    return HookResult(exit_code=0, message=f"[harness] {fname} OK")


if __name__ == "__main__":
    sys.exit(run_hook(handle, hook_type="pre_edit", fail_closed=True))
