"""
Spec File — read and validate spec.md files for the pipeline.

The spec file is the source of truth for what should be built.
It's created during Stage 2 (SPEC) and verified during Stage 5/6.

Expected format:
  ## 功能：XXX
  ## 验收标准
  - 当X时，应该Y
  - 当A时，应该B
  ## 影响文件
  - file1.py: 改什么
  ## 不做
  - 不改Z
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SpecValidation:
    """Result of spec file validation."""

    valid: bool
    path: str = ""
    criteria_count: int = 0
    file_count: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Criteria patterns (match common spec formats)
# ---------------------------------------------------------------------------

# Acceptance criteria patterns
_CRITERIA_PATTERNS = [
    re.compile(r"当.+时.+应该", re.IGNORECASE),      # 当X时，应该Y
    re.compile(r"when\s+.+\s+should", re.IGNORECASE),  # When X, should Y
    re.compile(r"^[-*]\s*\[[ x]\]", re.MULTILINE),     # - [ ] or - [x] checklist
    re.compile(r"given\s+.+\s+then", re.IGNORECASE),   # Given X, then Y
]

# Section header patterns (used for structure detection only, not criteria counting)
_HEADER_PATTERNS = [
    re.compile(r"验收.*(标准|条件)", re.IGNORECASE),     # 验收标准 header
    re.compile(r"acceptance\s+criter", re.IGNORECASE),  # Acceptance criteria header
]

# File reference patterns
_FILE_PATTERNS = [
    re.compile(r"\w+\.py"),                              # something.py
    re.compile(r"\w+\.(ts|tsx|js|jsx|vue|html|css)"),   # frontend files
    re.compile(r"影响文件|affected\s+file", re.IGNORECASE),  # Section header
]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def find_spec(project_root: str) -> str | None:
    """Find spec.md in the project. Returns path or None.

    Search order:
      1. {project_root}/.harness/spec.md
      2. {project_root}/spec.md
    """
    root = Path(project_root)

    harness_spec = root / ".harness" / "spec.md"
    if harness_spec.is_file() and harness_spec.stat().st_size > 0:
        return str(harness_spec)

    root_spec = root / "spec.md"
    if root_spec.is_file() and root_spec.stat().st_size > 0:
        return str(root_spec)

    return None


def extract_affected_files(spec_path: str) -> list[str]:
    """Extract file paths from spec's affected files section.

    Parses the ## 影响文件 / ## 修改范围 / ## Affected Files section
    and returns a list of file paths found in list items or table rows.
    """
    try:
        content = Path(spec_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    # Find the affected files section
    section_match = re.search(
        r'(?:##\s*(?:影响文件|修改范围|修改文件|Affected Files))(.*?)(?=\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if not section_match:
        return []

    section = section_match.group(1)
    files: list[str] = []

    # Match table rows: | path/file.py | ... |
    for m in re.finditer(r'\|\s*([^\s|]+\.\w+)\s*\|', section):
        files.append(m.group(1))

    # Match list items: - path/file.py: description  or  - path/file.py
    for m in re.finditer(r'[-*]\s+`?([^\s:`]+\.\w+)`?', section):
        files.append(m.group(1))

    return files


def validate_spec(spec_path: str, route: str = "") -> SpecValidation:
    """Validate a spec file's format and completeness.

    Checks:
      1. File exists and is non-empty
      2. Contains at least one acceptance criterion
      3. References at least one file (warned if missing)

    Returns SpecValidation with valid=True if minimum requirements met.
    """
    path = Path(spec_path)

    if not path.is_file():
        return SpecValidation(valid=False, path=spec_path, error="File not found")

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return SpecValidation(valid=False, path=spec_path, error=f"Cannot read: {e}")

    if not content.strip():
        return SpecValidation(valid=False, path=spec_path, error="File is empty")

    # Count acceptance criteria
    criteria_count = 0
    for pattern in _CRITERIA_PATTERNS:
        criteria_count += len(pattern.findall(content))

    # Count file references
    file_count = 0
    for pattern in _FILE_PATTERNS:
        file_count += len(pattern.findall(content))

    # Build warnings
    warnings = []
    if criteria_count == 0:
        warnings.append("No acceptance criteria found (expected '当X时，应该Y' or '- [ ]' format)")
    if file_count == 0:
        warnings.append("No file references found (expected an '影响文件' section)")

    # v3.1: Check criterion specificity — short criteria are likely too vague
    for pattern in _CRITERIA_PATTERNS[:2]:  # "当X时应该Y" and "When X should Y"
        for match in pattern.finditer(content):
            if len(match.group(0)) < 15:
                warnings.append(f"验收标准过于简短（<15字）：'{match.group(0)}'，请补充具体细节")
                break  # One warning is enough

    # v3.1: Check affected files exist on disk
    affected = extract_affected_files(spec_path)
    if affected:
        project_root = str(Path(spec_path).parent.parent)  # .harness/spec.md -> project root
        missing = [f for f in affected
                   if not Path(project_root, f).exists()
                   and not Path(project_root, f).with_suffix("").name.startswith("new_")]
        if missing:
            warnings.append(f"影响文件中以下文件不存在：{', '.join(missing[:5])}（如果是新建文件请忽略）")

    # v3.2: Minimum criteria count based on route
    # Format check is now a WARNING, not a hard gate.
    # Even if regex didn't match, the spec may have valid criteria in plain list format.
    # Pipeline advance will warn but NOT block on format mismatch (degradation path).
    min_criteria = 2 if route in ("standard", "full", "standard-deploy", "full-deploy") else 1

    if criteria_count == 0:
        # Criteria exist but in unrecognized format — count plain list items as fallback
        plain_items = re.findall(r'^[-*]\s+\S.{5,}', content, re.MULTILINE)
        if plain_items:
            criteria_count = len(plain_items)
            warnings.append(
                f"验收标准格式未匹配（期望'当X时，应该Y'或'- [ ]'格式），"
                f"但检测到{len(plain_items)}条普通列表项，按降级模式处理。"
                f"建议改写为：'当[用户做什么]时，应该[看到什么结果]'"
            )

    valid = criteria_count >= min_criteria

    if 0 < criteria_count < min_criteria:
        warnings.append(f"{route}路由至少需要{min_criteria}条验收标准，当前只有{criteria_count}条")

    return SpecValidation(
        valid=valid,
        path=spec_path,
        criteria_count=criteria_count,
        file_count=file_count,
        warnings=warnings,
    )


def extract_acceptance_criteria(spec_path: str) -> list[str]:
    """Extract individual acceptance criteria text from spec.md.

    Returns a list of criterion strings (e.g., "当用户点击时，应该跳转").
    Used by TEST stage to verify each AC has a corresponding test result.
    """
    try:
        content = Path(spec_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    criteria: list[str] = []

    def _add_unique(text: str) -> None:
        """Add AC text, deduplicating by substring containment."""
        for existing in criteria:
            if text in existing or existing in text:
                return  # Already covered by a longer/shorter version
        criteria.append(text)

    # Table row extraction FIRST (most structured, preferred source)
    ac_section = re.search(
        r'(?:##\s*(?:验收标准|验收条件|Acceptance Criteria))(.*?)(?=\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if ac_section:
        for row in re.finditer(r'\|\s*\d+\s*\|\s*(.+?)\s*\|', ac_section.group(1)):
            text = row.group(1).strip()
            if len(text) >= 10:
                _add_unique(text)

    # Pattern-based extraction: "当X时，应该Y" / "When X, should Y" / "Given X, then Y"
    for pattern in _CRITERIA_PATTERNS[:3]:  # skip checklist pattern for text extraction
        for match in pattern.finditer(content):
            text = match.group(0).strip()
            if len(text) >= 10:
                _add_unique(text)

    # Checklist extraction: "- [x] description" / "- [ ] description"
    for match in re.finditer(r'^[-*]\s*\[[ x]\]\s*(.+)', content, re.MULTILINE):
        text = match.group(1).strip()
        if len(text) >= 5:
            _add_unique(text)

    # Fallback: if no structured criteria found, try plain list items in AC section
    if not criteria and ac_section:
        for match in re.finditer(r'^[-*]\s+(\S.{9,})', ac_section.group(1), re.MULTILINE):
            _add_unique(match.group(1).strip())

    return criteria


def extract_test_strategy(spec_path: str) -> dict[str, bool]:
    """Parse the "## 测试策略" section from spec.md.

    Returns a dict with keys: need_ac_script, need_xiaoce, need_zhuolong.
    - Recognizes both full-width (：) and half-width (:) colons
    - "需要" => True, "不需要" => False
    - Missing section => all False (backward compat)
    - Unreadable file => all False
    """
    default: dict[str, bool] = {
        "need_ac_script": False,
        "need_xiaoce": False,
        "need_zhuolong": False,
    }

    try:
        content = Path(spec_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return default

    # Find "## 测试策略" section (up to next "## " or end of file)
    section_match = re.search(
        r'##\s*测试策略(.*?)(?=\n##\s|\Z)',
        content, re.DOTALL,
    )
    if not section_match:
        return default

    section = section_match.group(1)

    def _parse_field(line_pattern: str) -> bool:
        """Return True if line matches need, False if not-need, False if missing."""
        m = re.search(line_pattern + r'[：:]\s*(\S+)', section)
        if not m:
            return False
        value = m.group(1)
        # Check "不需要" first (contains "需要" as substring)
        if "不需要" in value:
            return False
        if "需要" in value:
            return True
        return False

    result = dict(default)
    result["need_ac_script"] = _parse_field(r'验收脚本')
    result["need_xiaoce"] = _parse_field(r'小测审计')
    result["need_zhuolong"] = _parse_field(r'浊龙验收')
    return result


def spec_summary(spec_path: str) -> str:
    """One-line summary of a spec file. For logging and display."""
    result = validate_spec(spec_path)
    if not result.valid:
        return f"INVALID: {result.error or '; '.join(result.warnings)}"
    return f"OK: {result.criteria_count} criteria, {result.file_count} file refs"
