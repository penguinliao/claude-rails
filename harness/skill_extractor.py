"""
Skill Extractor — learn from retreats by capturing failure patterns as reusable skills.

After a pipeline completes, this module inspects the history for FAIL entries.
If retreats occurred, it generates a structured skill document that captures
what went wrong and how to prevent it in future projects.

Skills are saved to ~/.harness/skills/ and indexed in index.json.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path.home() / ".harness" / "skills"
_INDEX_FILE = _SKILLS_DIR / "index.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_fails(history: list) -> int:
    """Count FAIL status entries in pipeline history."""
    return sum(1 for entry in history if entry.status == "FAIL")


def _extract_fail_notes(history: list) -> list[str]:
    """Extract non-empty notes from FAIL history entries."""
    notes: list[str] = []
    for entry in history:
        if entry.status == "FAIL" and entry.note and entry.note.strip():
            notes.append(entry.note.strip())
    return notes


def _extract_domain(files: list[str]) -> str:
    """Infer domain from file paths. e.g. core/payment.py -> payment."""
    for file_path in files:
        # Get the filename without extension
        name = Path(file_path).stem
        if name and name not in ("__init__", "main", "utils", "helpers", "common", "base"):
            return name
    return "general"


def _extract_trigger_words(ac_texts: list[str]) -> list[str]:
    """Extract keywords (length >= 2) from acceptance criteria text."""
    words: set[str] = set()
    combined = " ".join(ac_texts)

    # Chinese words: extract sequences of Chinese characters (length >= 2)
    for m in re.finditer(r'[\u4e00-\u9fff]{2,}', combined):
        words.add(m.group(0))

    # English words: extract words of length >= 2, skip common stopwords
    stopwords = {
        "the", "a", "an", "is", "in", "on", "at", "to", "of", "and", "or",
        "it", "be", "as", "by", "if", "we", "do", "so", "no", "up", "my",
        "with", "for", "not", "are", "was", "has", "have", "from", "that",
        "this", "when", "then", "should", "given", "will", "can", "must",
    }
    for m in re.finditer(r'[a-zA-Z]{2,}', combined):
        word = m.group(0).lower()
        if word not in stopwords:
            words.add(word)

    return sorted(words)[:20]  # cap at 20 keywords


def _severity_from_retreats(fail_count: int) -> str:
    """Derive severity label from number of FAIL entries."""
    if fail_count >= 3:
        return "high"
    if fail_count >= 2:
        return "medium"
    return "low"


def _extract_failure_dimensions(notes: list[str]) -> list[str]:
    """Guess failure dimensions from FAIL notes."""
    dimensions: list[str] = []
    combined = " ".join(notes).lower()

    dim_keywords = {
        "functional": ["functional", "函数", "功能", "逻辑", "logic", "implement", "实现"],
        "security": ["security", "安全", "sql", "injection", "xss", "auth", "权限", "密钥"],
        "performance": ["performance", "性能", "slow", "timeout", "超时", "内存"],
        "style": ["style", "format", "ruff", "lint", "pep8", "格式"],
        "type": ["type", "mypy", "类型", "annotation"],
        "test": ["test", "测试", "assert", "coverage", "覆盖"],
    }

    for dim, keywords in dim_keywords.items():
        if any(kw in combined for kw in keywords):
            dimensions.append(dim)

    return dimensions if dimensions else ["functional"]


def _build_skill_doc(
    skill_id: str,
    domain: str,
    files: list[str],
    trigger_words: list[str],
    severity: str,
    source_project: str,
    retreats: int,
    failure_dimensions: list[str],
    fail_notes: list[str],
    created: str,
) -> str:
    """Build the skill markdown document."""
    # Frontmatter
    files_yaml = json.dumps(files)
    trigger_yaml = json.dumps(trigger_words)
    dim_yaml = json.dumps(failure_dimensions)

    problem_section = "\n".join(f"- {note}" for note in fail_notes) if fail_notes else "- (未记录具体失败原因)"

    rules_map = {
        "functional": "- 实现前先确认接口签名和返回格式与调用方一致",
        "security": "- 所有用户输入必须参数化，不允许 f-string 拼接 SQL；密钥从环境变量读取",
        "performance": "- 高频调用路径避免阻塞 I/O；数据库查询加索引",
        "style": "- 运行 ruff check 并修复所有 E/W 级别错误后再提交",
        "type": "- 为所有公开函数添加类型注解；运行 mypy 确认无类型错误",
        "test": "- 每条 AC 至少有一个独立测试脚本；关键字段 assert 长度/格式而非仅检查无异常",
    }

    rules_lines: list[str] = []
    for dim in failure_dimensions:
        rule = rules_map.get(dim)
        if rule:
            rules_lines.append(rule)
    if not rules_lines:
        rules_lines.append("- 完成实现后先自测核心路径，确认最终输出非空")

    rules_section = "\n".join(rules_lines)

    doc = f"""---
id: {skill_id}
version: "1.0"
platforms: [claude-rails]
domain: {domain}
files: {files_yaml}
trigger_words: {trigger_yaml}
severity: {severity}
source_project: {source_project}
created: "{created}"
retreats: {retreats}
failure_dimensions: {dim_yaml}
---

## 问题
{problem_section}

## 规则
{rules_section}
"""
    return doc


def _load_index(skills_dir: Path) -> list[dict]:
    """Load index.json or return empty list."""
    index_file = skills_dir / "index.json"
    if not index_file.is_file():
        return []
    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(skills_dir: Path, index: list[dict]) -> None:
    """Write index.json atomically."""
    import tempfile
    index_file = skills_dir / "index.json"
    content = json.dumps(index, ensure_ascii=False, indent=2)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(skills_dir), suffix=".tmp", prefix="idx_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(index_file))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_skill(
    project_root: str,
    skills_dir: Optional[str] = None,
) -> Optional[str]:
    """Extract a skill from a completed pipeline run.

    Called after pipeline completion. Generates a skill document only when
    at least one retreat (FAIL) occurred — a perfect run has no lessons.

    Args:
        project_root: Path to the project root containing .harness/pipeline.json.
        skills_dir: Override default ~/.harness/skills/ directory (used in tests).

    Returns:
        Absolute path to the generated skill .md file, or None if no skill was extracted.
    """
    from harness.pipeline import get_state
    from harness.spec_file import find_spec, extract_affected_files, extract_acceptance_criteria

    # --- 1. Load pipeline state ---
    try:
        state = get_state(project_root)
        if state is None:
            return None
    except Exception:
        return None

    # --- 2. Count FAIL entries ---
    try:
        fail_count = _count_fails(state.history)
    except Exception:
        return None

    if fail_count == 0:
        return None  # One-pass success — no lesson to capture

    # --- 3. Resolve skills directory ---
    output_dir = Path(skills_dir) if skills_dir else _SKILLS_DIR
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    # --- 4. Extract context from spec ---
    affected_files: list[str] = []
    ac_texts: list[str] = []
    try:
        spec_path = find_spec(project_root)
        if spec_path:
            affected_files = extract_affected_files(spec_path)
            ac_texts = extract_acceptance_criteria(spec_path)
    except Exception:
        pass

    # --- 5. Derive skill metadata ---
    try:
        domain = _extract_domain(affected_files)
        trigger_words = _extract_trigger_words(ac_texts)
        severity = _severity_from_retreats(fail_count)
        fail_notes = _extract_fail_notes(state.history)
        failure_dims = _extract_failure_dimensions(fail_notes)
        created = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        skill_id = f"skill_{timestamp}_{domain}"
        source_project = Path(project_root).name
    except Exception:
        return None

    # --- 6. Generate skill document ---
    try:
        doc = _build_skill_doc(
            skill_id=skill_id,
            domain=domain,
            files=affected_files,
            trigger_words=trigger_words,
            severity=severity,
            source_project=source_project,
            retreats=fail_count,
            failure_dimensions=failure_dims,
            fail_notes=fail_notes,
            created=created,
        )
    except Exception:
        return None

    # --- 7. Write skill file ---
    skill_filename = f"{skill_id}.md"
    skill_path = output_dir / skill_filename
    try:
        skill_path.write_text(doc, encoding="utf-8")
    except Exception:
        return None

    # --- 8. Update index.json ---
    try:
        index = _load_index(output_dir)
        entry = {
            "id": skill_id,
            "domain": domain,
            "files": affected_files,
            "trigger_words": trigger_words,
            "severity": severity,
            "path": skill_filename,
        }
        index.append(entry)
        _save_index(output_dir, index)
    except Exception:
        pass  # Index update failure should not prevent skill file delivery

    return str(skill_path)
