#!/usr/bin/env python3
"""
PostToolUse hook for Agent — review code written by sub-agents.

The "independent reviewer" layer: code written by one AI gets checked by
a separate process that never saw the implementation conversation.

Strategy:
  1. Parse Agent output text for file paths it reports modifying
  2. Handle worktree paths (Agent may work in /tmp/.worktrees/...)
  3. Run check_standard on all discovered Python files
  4. Exit 2 (block) if any file fails quality gate

Exit codes:
  0 = pass (or no Python files found — don't block non-code agents)
  2 = fail (structured feedback shown to AI)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Add harness to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.hook_runner import run_hook, HookContext, HookResult

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue"}

# ---------------------------------------------------------------------------
# File path extraction from Agent output
# ---------------------------------------------------------------------------

# Patterns that agents typically use to report file modifications
_FILE_PATTERNS = [
    # Chinese: 修改了/创建了/编辑了/更新了/写入了 xxx.py/.ts/.vue 等
    re.compile(r"(?:修改了|创建了|编辑了|更新了|写入了|新建了)\s*[`「]?([^\s`」,，]+\.(?:py|ts|tsx|js|jsx|vue))[`」]?"),
    # English: Modified/Created/Edited/Updated/Wrote xxx.py/.ts/.vue 等
    re.compile(r"(?:Modified|Created|Edited|Updated|Wrote|Changed|Added)\s+[`]?([^\s`,]+\.(?:py|ts|tsx|js|jsx|vue))[`]?", re.IGNORECASE),
    # Tool-style: file_path: /path/to/file.py/.ts/.vue 等
    re.compile(r"file_path[\"']?\s*[:=]\s*[\"']?([^\s\"',]+\.(?:py|ts|tsx|js|jsx|vue))"),
    # Markdown code references: `path/to/file.py/.ts/.vue 等`
    re.compile(r"`(/[^\s`]+\.(?:py|ts|tsx|js|jsx|vue))`"),
    # Write/Edit tool mentions in agent output
    re.compile(r"(?:Write|Edit)\s+(?:tool\s+)?(?:to\s+)?[`]?(/[^\s`]+\.(?:py|ts|tsx|js|jsx|vue))[`]?", re.IGNORECASE),
]

# Worktree path indicators
_WORKTREE_INDICATORS = (".worktrees/", "/tmp/", "worktree")


def _is_within_allowed_roots(real_path: str) -> bool:
    """B1: Whitelist check — only allow files under cwd or ~/Desktop."""
    allowed_roots = [
        os.path.realpath(os.getcwd()),
        os.path.realpath(os.path.expanduser("~/Desktop")),
    ]
    for root in allowed_roots:
        if real_path.startswith(root + os.sep) or real_path == root:
            return True
    return False


def _extract_code_files(text: str) -> list[str]:
    """Extract code file paths from Agent output text.

    Returns deduplicated list of absolute paths, ordered by first appearance.
    All paths are normalized via realpath for dedup and security.
    """
    seen = set()
    files = []

    for pattern in _FILE_PATTERNS:
        for match in pattern.finditer(text):
            path = match.group(1)
            # Normalize: ensure absolute path
            if not os.path.isabs(path):
                # Try common project roots
                resolved = False
                for root in [os.getcwd(), os.path.expanduser("~/Desktop")]:
                    candidate = os.path.join(root, path)
                    if os.path.isfile(candidate):
                        path = candidate
                        resolved = True
                        break
                if not resolved:
                    continue  # B1: skip unresolvable relative paths

            if Path(path).suffix.lower() not in CODE_EXTS:
                continue

            # B1: normalize with realpath for consistent dedup + path traversal prevention
            real_path = os.path.realpath(path)
            if not _is_within_allowed_roots(real_path):
                continue  # B1: reject paths outside allowed roots

            if real_path not in seen:
                seen.add(real_path)
                files.append(real_path)

    return files


def _detect_worktree_root(files: list[str]) -> str | None:
    """If files are in a worktree, return the worktree root path."""
    for f in files:
        for indicator in _WORKTREE_INDICATORS:
            if indicator in f:
                # Walk up to find .git or project markers
                path = os.path.dirname(f)
                for _ in range(10):  # Max 10 levels up
                    if any(os.path.exists(os.path.join(path, m))
                           for m in (".git", "pyproject.toml", "CLAUDE.md")):
                        return path
                    parent = os.path.dirname(path)
                    if parent == path:
                        break
                    path = parent
    return None


# ---------------------------------------------------------------------------
# v3.1 Gap 4: Incremental scanning — only report issues in changed lines
# ---------------------------------------------------------------------------

def _get_changed_lines(file_path: str) -> set[int] | None:
    """Get line numbers changed in working tree vs HEAD.

    Returns set of changed line numbers, or None if:
      - file is untracked (new file, scan all)
      - not a git repo
      - any error occurs (fail-open)
    """
    try:
        cwd = os.path.dirname(file_path)
        # Check if file is tracked
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", file_path],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        if status.returncode != 0:
            return None  # Not a git repo

        output = status.stdout.strip()
        if output.startswith("??"):
            return None  # Untracked file, scan all

        # Get diff against HEAD
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--unified=0", "--", file_path],
            capture_output=True, text=True, timeout=10, cwd=cwd,
        )
        if diff.returncode != 0:
            return None

        lines: set[int] = set()
        for match in re.finditer(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', diff.stdout):
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) else 1
            lines.update(range(start, start + count))

        return lines if lines else None
    except Exception:
        return None  # Fail-open


def _filter_suggestions_by_lines(
    suggestions: list,
    changed_lines: dict[str, set[int] | None],
) -> list:
    """Filter FixSuggestion list to only issues in Agent-modified files AND lines.

    This is the core defense against "historical debt amplification": when Agent
    edits file A, mypy/bandit may transitively scan imported modules B and C and
    report existing issues there. Those must be filtered out, or every Agent call
    gets blocked by pre-existing debt it didn't touch.

    Logic:
      - changed_lines keys are the files Agent actually modified
      - If a suggestion's file is NOT in any changed_lines key → drop
        (unrelated file, historical debt in a transitively-scanned module)
      - If matched but changed_lines[path] is None (file untracked / no git) → keep
        (fail-open: we can't tell new from old, so don't filter)
      - If matched and s_line is in the changed set → keep
        (issue was introduced or modified by this Agent)
      - Otherwise → drop (issue exists in unchanged lines of a changed file — historical)
    """
    if not changed_lines:
        return suggestions  # Nothing to filter against

    filtered = []
    for s in suggestions:
        s_file = getattr(s, "file", "")
        s_line = getattr(s, "line", None)

        if not s_file:
            filtered.append(s)  # Can't filter without file info — keep
            continue

        # Try to match suggestion's file to an Agent-modified file
        matched_path: str | None = None
        matched_lines: set[int] | None = None
        s_basename = os.path.basename(s_file)
        for path, lines in changed_lines.items():
            # Match by exact equality, path containment, or basename equality
            if s_file == path or s_file in path or path.endswith("/" + s_file):
                matched_path = path
                matched_lines = lines
                break
            if os.path.basename(path) == s_basename:
                matched_path = path
                matched_lines = lines
                break

        if matched_path is None:
            # s_file is NOT an Agent-modified file → historical debt in
            # a transitively-scanned module, drop
            continue

        if matched_lines is None:
            # File matched but can't diff (untracked / no git) → fail-open, keep
            filtered.append(s)
            continue

        if s_line is not None and s_line in matched_lines:
            # Issue is in a line Agent actually changed → keep
            filtered.append(s)
        # else: changed file but issue in unchanged line → historical debt, drop

    return filtered


# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

def _resolve_project_root(ctx: HookContext, existing_files: list) -> str:
    """Resolve harness project root with multi-tier fallback.

    Priority:
      1. ctx.project_root (set by hook_runner if available)
      2. HARNESS_PROJECT env var (if that dir has .harness/)
      3. walk-up from any existing_files ancestor (max 10 levels)
      4. os.getcwd() last resort
    """
    if getattr(ctx, "project_root", None):
        return ctx.project_root
    env_root = os.environ.get("HARNESS_PROJECT")
    if env_root and os.path.isdir(os.path.join(env_root, ".harness")):
        return env_root
    for f in existing_files:
        try:
            d = os.path.dirname(os.path.realpath(f))
        except OSError:
            continue
        for _ in range(10):
            if os.path.isdir(os.path.join(d, ".harness")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return os.getcwd()


# ---------------------------------------------------------------------------
# Hook handler
# ---------------------------------------------------------------------------

def handle(ctx: HookContext) -> HookResult:
    """Review Python files modified by a sub-agent."""

    # Only trigger on Agent tool
    if ctx.tool_name != "Agent":
        return HookResult(exit_code=0)

    # Extract agent output from tool result
    # PostToolUse receives the tool's output in various fields
    agent_output = ""

    # Try tool_input first (some hooks get input, some get output)
    if isinstance(ctx.tool_input, dict):
        # Agent result may be in 'result', 'output', 'response', or 'prompt'
        for key in ("result", "output", "response", "stdout"):
            val = ctx.tool_input.get(key, "")
            if val:
                agent_output += str(val) + "\n"

    # Also check raw stdin for the full payload
    if ctx.raw_stdin:
        agent_output += ctx.raw_stdin

    if not agent_output.strip():
        return HookResult(exit_code=0, message="[harness] ⏭️ Agent输出为空，跳过审查")

    # Extract code files from output
    py_files = _extract_code_files(agent_output)

    if not py_files:
        return HookResult(exit_code=0, message="[harness] ⏭️ Agent未修改代码文件，跳过审查")

    # Filter to files that actually exist on disk
    existing_files = [f for f in py_files if os.path.isfile(f)]

    # If files are in a worktree, check there
    if not existing_files:
        worktree_root = _detect_worktree_root(py_files)
        if worktree_root:
            # B3: Use path suffix (last 2-3 segments) for matching, not just basename
            # This avoids collision when multiple dirs have e.g. utils.py
            def _path_suffix(p: str, segments: int = 2) -> str:
                parts = p.replace("\\", "/").split("/")
                return "/".join(parts[-segments:]) if len(parts) >= segments else parts[-1]

            # B2: Walk with depth limit to avoid traversing huge directories
            max_depth = 3
            worktree_real = os.path.realpath(worktree_root)
            base_depth = worktree_real.count(os.sep)
            for root, dirs, filenames in os.walk(worktree_real):
                current_depth = root.count(os.sep) - base_depth
                if current_depth >= max_depth:
                    dirs.clear()  # Stop descending
                    continue
                for fname in filenames:
                    if Path(fname).suffix.lower() not in CODE_EXTS:
                        continue
                    full = os.path.realpath(os.path.join(root, fname))
                    # B3: Match by suffix (e.g. "core/utils.py") not just "utils.py"
                    full_suffix = _path_suffix(full)
                    for f in py_files:
                        if _path_suffix(f) == full_suffix and full not in existing_files:
                            if _is_within_allowed_roots(full):
                                existing_files.append(full)
                            break

    if not existing_files:
        return HookResult(
            exit_code=0,
            message=f"[harness] ⏭️ Agent报告修改了 {len(py_files)} 个代码文件但均不存在，跳过审查"
        )

    # Gate: Agent modified code files → project must have test scripts
    # This ensures every code change has corresponding tests — not by checking
    # AI's self-report, but by checking the filesystem.
    # Only triggers if files were RECENTLY modified (mtime within 120s),
    # avoiding false positives from read-only agents that merely mention file paths.
    if existing_files:
        import glob as _glob
        now = time.time()
        recently_modified = [f for f in existing_files
                             if os.path.isfile(f)
                             and (now - os.path.getmtime(f)) < 120]
        if recently_modified:
            project_root = _resolve_project_root(ctx, recently_modified)
            harness_dir = os.path.join(project_root, ".harness")
            test_scripts = _glob.glob(os.path.join(harness_dir, "test_*.py"))
            py_code_files = [f for f in recently_modified if f.endswith(".py")
                             and not os.path.basename(f).startswith("test_")]
            if py_code_files and not test_scripts:
                file_list = ", ".join(os.path.basename(f) for f in py_code_files[:5])
                return HookResult(
                    exit_code=2,
                    message=f"[harness] ❌ Agent修改了代码文件（{file_list}）但项目缺少测试脚本。\n"
                            f"必须在 .harness/test_*.py 中编写可执行的测试脚本。\n"
                            f"测试脚本要求：验证spec.md中的验收标准，exit 0=通过。",
                )

    # B4: Delayed imports with try-except, fail-open on ImportError
    start = time.time()
    try:
        from harness.runner import check_standard
    except ImportError:
        return HookResult(exit_code=0, message="[harness] ⚠️ harness.runner不可用，跳过Agent代码审查")

    # v3.1 Gap 4: Get changed lines for incremental scanning
    changed_lines: dict[str, set[int] | None] = {}
    for f in existing_files:
        changed_lines[f] = _get_changed_lines(f)
    is_incremental = any(v is not None for v in changed_lines.values())
    scan_label = "增量扫描" if is_incremental else "全量扫描"

    report = check_standard(existing_files)
    elapsed = f"{time.time() - start:.1f}s"

    file_list = ", ".join(os.path.basename(f) for f in existing_files)

    # B5: Defensive attribute access with getattr
    if getattr(report, "passed", False):
        score = f"{getattr(report, 'total_score', 0):.0f}分"
        # 更新并显示风险等级
        try:
            from harness.pipeline import update_risk_level
            from harness.risk_analyzer import format_risk_summary
            update_risk_level(ctx.project_root)
            risk_info = format_risk_summary(ctx.project_root)
        except Exception:
            risk_info = ""
        msg = f"[harness] ✅ Agent代码审查通过：{file_list} ({score}, {elapsed}, {scan_label})"
        if risk_info:
            msg += f"\n[harness] {risk_info}"
        # Check for interface change request from Sonnet
        change_req_path = os.path.join(ctx.project_root or os.getcwd(), ".harness", "change_request.md")
        if os.path.isfile(change_req_path):
            try:
                with open(change_req_path, encoding="utf-8") as _cr_f:
                    _cr_content = _cr_f.read().strip()
                if _cr_content:
                    msg += (
                        "\n\n[harness] ⚠️ 检测到接口变更请求 (.harness/change_request.md)\n"
                        "Sonnet 认为 spec 中的接口需要调整。请 Opus 裁决：\n"
                        "  合理 → 更新 spec.md + 测试脚本 + 删除 change_request.md\n"
                        "  不合理 → 删除 change_request.md，Sonnet 按原 spec 继续"
                    )
            except Exception:
                pass
        return HookResult(exit_code=0, message=msg)

    # Failed — build structured feedback
    try:
        from harness.feedback import generate_feedback
        feedback = generate_feedback(report)
    except ImportError:
        feedback = None

    # v3.1 Gap 4: Filter suggestions to only changed lines
    suggestions = getattr(feedback, "suggestions", None) if feedback else None
    if suggestions and is_incremental:
        suggestions = _filter_suggestions_by_lines(suggestions, changed_lines)
        # If all issues are in existing code (not agent's changes), pass through
        if not suggestions:
            score = f"{getattr(report, 'total_score', 0):.0f}分"
            # 更新并显示风险等级
            try:
                from harness.pipeline import update_risk_level
                from harness.risk_analyzer import format_risk_summary
                update_risk_level(ctx.project_root)
                risk_info = format_risk_summary(ctx.project_root)
            except Exception:
                risk_info = ""
            msg = f"[harness] ✅ Agent代码审查通过（存量问题已过滤）：{file_list} ({score}, {elapsed})"
            if risk_info:
                msg += f"\n[harness] {risk_info}"
            # Check for interface change request from Sonnet
            change_req_path = os.path.join(ctx.project_root or os.getcwd(), ".harness", "change_request.md")
            if os.path.isfile(change_req_path):
                try:
                    with open(change_req_path, encoding="utf-8") as _cr_f:
                        _cr_content = _cr_f.read().strip()
                    if _cr_content:
                        msg += (
                            "\n\n[harness] ⚠️ 检测到接口变更请求 (.harness/change_request.md)\n"
                            "Sonnet 认为 spec 中的接口需要调整。请 Opus 裁决：\n"
                            "  合理 → 更新 spec.md + 测试脚本 + 删除 change_request.md\n"
                            "  不合理 → 删除 change_request.md，Sonnet 按原 spec 继续"
                        )
                except Exception:
                    pass
            return HookResult(exit_code=0, message=msg)

    # Build actionable message
    lines = [
        f"[harness] ❌ Agent代码审查未通过：{file_list} ({elapsed}, {scan_label})",
        "",
        "Agent写的代码存在以下问题，请修复后再继续：",
        "",
    ]

    # B5: Consistent getattr defense
    blocked_by = getattr(report, "blocked_by", None)
    if blocked_by:
        lines.append(f"🚫 硬门禁触发：{blocked_by}")
        lines.append("")

    # Add dimension scores
    dimensions = getattr(report, "dimensions", [])
    for dim in dimensions:
        passed = getattr(dim, "passed", False)
        icon = "✅" if passed else "❌"
        name = getattr(dim, "name", "?")
        score = getattr(dim, "score", 0)
        lines.append(f"  {icon} {name}: {score:.0f}分")

    lines.append("")

    # B6: Add fix suggestions with consistent defense (already filtered by Gap 4)
    if suggestions:
        lines.append("修复建议：")
        for i, s in enumerate(suggestions[:8], 1):
            sev = getattr(s, "severity", "MEDIUM").upper()
            s_file = getattr(s, "file", "?")
            s_line = getattr(s, "line", None) or "?"
            s_problem = getattr(s, "problem", "未知问题")
            lines.append(f"  {i}. [{sev}] {s_file}:{s_line} — {s_problem}")
            fix_hint = getattr(s, "fix_hint", None)
            if fix_hint:
                lines.append(f"     💡 {fix_hint}")

    return HookResult(exit_code=2, message="\n".join(lines))


if __name__ == "__main__":
    sys.exit(run_hook(handle, hook_type="post_agent", fail_closed=True))
