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
    import fnmatch

    fname = os.path.basename(ctx.file_path) if ctx.file_path else ""

    # Early return: .harness/ special file handling
    if ctx.file_path:
        _fpath = _pl.Path(ctx.file_path)
        _fname = _fpath.name
        _state_early = get_state(ctx.project_root) if ctx.project_root else None
        _stage_early = _state_early.current_stage if _state_early else None

        # .harness/test_*.py and .harness/*_brief.md: allow in SPEC(1), block in IMPLEMENT(3)
        _is_harness_test = (
            fnmatch.fnmatch(_fname, "test_*.py")
            and ".harness" in str(_fpath)
        )
        _is_harness_brief = (
            fnmatch.fnmatch(_fname, "*_brief.md")
            and ".harness" in str(_fpath)
        )

        if _is_harness_test or _is_harness_brief:
            if _stage_early == 1:
                # SPEC stage: allow editing test scripts and brief files
                return HookResult(exit_code=0, message=f"[harness] {fname} OK (SPEC阶段允许编辑测试/任务书文件)")
            if _stage_early == 3:
                # IMPLEMENT stage: block
                if _is_harness_test:
                    return HookResult(
                        exit_code=2,
                        message="[harness] ❌ 测试脚本在 SPEC 阶段已锁定，IMPLEMENT 阶段不可修改",
                    )
                return HookResult(
                    exit_code=2,
                    message="[harness] ❌ 审计任务书在 SPEC 阶段已锁定，IMPLEMENT 阶段不可修改",
                )

        # .harness/change_request.md: always allow (Sonnet interface change channel)
        if _fname == "change_request.md" and ".harness" in str(_fpath):
            return HookResult(exit_code=0, message=f"[harness] {fname} OK (接口变更通道，始终放行)")

    allowed, reason = is_code_write_allowed(ctx.project_root, ctx.file_path)

    if not allowed:
        return HookResult(exit_code=2, message=f"[harness] {fname} blocked\n{reason}")

    # Show pipeline stage context if active
    state = get_state(ctx.project_root) if ctx.project_root else None

    # 保护 spec.md 和 review.md 只在对应阶段可编辑
    basename = _pl.Path(ctx.file_path).name if ctx.file_path else ""
    if basename in ("spec.md", "review.md") and ctx.file_path:
        file_parent = _pl.Path(ctx.file_path).resolve().parent.name
        if file_parent == ".harness":
            if basename == "spec.md" and state and state.current_stage != 1:
                return HookResult(exit_code=2, message="[harness] ❌ spec.md 只能在 SPEC 阶段(1)编辑")
            if basename == "review.md" and state and state.current_stage != 4:
                return HookResult(exit_code=2, message="[harness] ❌ review.md 只能在 REVIEW 阶段(4)编辑")

    if state:
        stage_name = STAGE_NAMES.get(state.current_stage, "?")

        # v3.2: Spec-based scope check — block edits outside spec's file list
        if state.current_stage == 3 and ctx.file_path:
            import pathlib as _pl

            _CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".html", ".css",
                          ".scss", ".svelte", ".go", ".rs", ".java", ".kt", ".swift"}

            def _check_spec_scope(file_path: str, project_root: str) -> "HookResult | None":
                """Check if file_path is in spec's affected files list.

                Returns HookResult(exit_code=2) if blocked, None if allowed.
                """
                try:
                    ext = _pl.Path(file_path).suffix.lower()
                    if ext not in _CODE_EXTS:
                        return None  # Non-code files always pass
                    from harness.spec_file import find_spec, extract_affected_files
                    spec_path = find_spec(project_root)
                    if not spec_path:
                        return None  # No spec → pass
                    affected = extract_affected_files(spec_path)
                    if not affected:
                        return None  # Empty spec file list → pass
                    norm = lambda p: os.path.normpath(p).replace(os.sep, "/")
                    rel_path = os.path.relpath(file_path, project_root)
                    if not any(norm(rel_path) == norm(af) for af in affected):
                        _bname = os.path.basename(file_path)
                        return HookResult(
                            exit_code=2,
                            message=f"[harness] ❌ {_bname} 不在spec.md影响文件列表中\n"
                                    f"spec列出的文件：{', '.join(affected[:5])}\n"
                                    f"如果确实需要修改，请先更新spec.md的影响文件部分",
                        )
                    return None
                except Exception:
                    return None  # Fail-open: spec parsing error should never block edits

            try:
                # Harness-engineering self-edit exemption (can't lock itself out)
                _harness_dir = str(_pl.Path(__file__).resolve().parent.parent)
                _file_resolved = str(_pl.Path(ctx.file_path).resolve()).lower()
                if _file_resolved.startswith(_harness_dir.lower()):
                    # Only exempt harness/ and hooks/ (core engine).
                    # docs/examples/templates etc. still need to be in spec.
                    _rel = os.path.relpath(ctx.file_path, _harness_dir)
                    if _rel.startswith("harness" + os.sep) or _rel.startswith("hooks" + os.sep):
                        pass  # Core engine files exempt from spec scope
                    else:
                        result = _check_spec_scope(ctx.file_path, ctx.project_root)
                        if result is not None:
                            return result
                else:
                    result = _check_spec_scope(ctx.file_path, ctx.project_root)
                    if result is not None:
                        return result
            except Exception:
                pass  # Fail-open: path resolution error should never block edits

        return HookResult(exit_code=0, message=f"[harness] {fname} OK (Stage {state.current_stage} {stage_name})")

    return HookResult(exit_code=0, message=f"[harness] {fname} OK")


if __name__ == "__main__":
    sys.exit(run_hook(handle, hook_type="pre_edit", fail_closed=True))
