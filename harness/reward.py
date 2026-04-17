"""
Multi-dimensional Reward Function Engine

Eight scoring dimensions with weighted aggregation:
- Functional correctness 33%: execution without errors + tests pass
- Spec compliance 18%: acceptance criteria coverage
- Type safety 14%: mypy strict check
- Security 12%: bandit + ruff security rules
- Complexity 8%: radon cyclomatic complexity + maintainability
- Architecture compliance 5%: custom rule checks
- Secret safety 5%: detect-secrets (hard gate)
- Code quality 5%: ruff lint
"""

from __future__ import annotations

import json as _json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RewardConfig:
    """Weights and gate thresholds for each dimension."""

    weights: dict[str, float] = field(default_factory=lambda: {
        "functional": 0.33,
        "spec_compliance": 0.18,
        "type_safety": 0.14,
        "security": 0.12,
        "complexity": 0.08,
        "architecture": 0.05,
        "secrets": 0.05,
        "code_quality": 0.05,
    })
    # Hard gates: if any of these dimensions score below threshold, the whole
    # report is marked as blocked. All gates defined here, not scattered in code.
    # Based on 367-bug analysis: secrets=any leak, functional<60=unusable, security<50=dangerous
    hard_gates: dict[str, int] = field(default_factory=lambda: {
        "secrets": 100,     # Any secret leak -> block
        "functional": 60,   # Code that doesn't work -> block
        "security": 50,     # Severe vulnerabilities -> block
    })
    # Minimum total score to pass
    pass_threshold: float = 60.0


@dataclass
class DimensionResult:
    """Scoring result for a single dimension."""

    name: str
    score: int  # 0-100, None if skipped
    passed: bool | None  # None if skipped
    details: str
    status: str = "evaluated"  # "evaluated" | "skipped" | "blocked"


@dataclass
class RewardReport:
    """Aggregated reward report across all dimensions."""

    dimensions: list[DimensionResult]
    total_score: float
    passed: bool
    blocked_by: str | None = None
    completeness: str = "complete"  # "complete" | "incomplete" | "minimal"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_available(name: str) -> bool:
    """Check whether a CLI tool is on PATH."""
    return shutil.which(name) is not None


def _run_tool(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run an external tool, return CompletedProcess."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def _score_from_issue_count(total_lines: int, issue_count: int) -> int:
    """Convert issue count to a 0-100 score.

    Deduction is proportional to issue density (issues per lines of code).
    ~1 issue per 10 lines = full deduction. This ensures large files with
    a few issues aren't penalized the same as small files with the same count.
    """
    if issue_count == 0:
        return 100
    if total_lines == 0:
        total_lines = 1
    # Density-based: issue_count/total_lines * 1000 means ~1 issue per 10 lines = 100% deduction
    deduction = min(int(issue_count / total_lines * 1000), 100)
    return max(0, 100 - deduction)


def _count_lines(files: list[str]) -> int:
    """Count total lines across files."""
    total = 0
    for f in files:
        try:
            total += Path(f).read_text(encoding="utf-8").count("\n")
        except (OSError, UnicodeDecodeError):
            pass
    return total


def _filter_python(files: list[str]) -> list[str]:
    """Keep only .py files."""
    return [f for f in files if f.endswith(".py")]


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def score_code_quality(files: list[str]) -> DimensionResult:
    """Run ruff check, compute score from issue count."""
    name = "code_quality"
    py_files = _filter_python(files)
    if not py_files:
        return DimensionResult(name=name, score=100, passed=True, details="No Python files to check.")

    if not _tool_available("ruff"):
        return DimensionResult(
            name=name, score=0, passed=None, status="skipped",
            details="ruff not installed. Install with: pip install ruff",
        )

    try:
        result = _run_tool(["ruff", "check", "--output-format=concise", "--no-fix", *py_files])
        output = result.stdout.strip()
        if not output:
            return DimensionResult(name=name, score=100, passed=True, details="No lint issues found.")

        issue_count = len(output.splitlines())
        total_lines = _count_lines(py_files)
        score = _score_from_issue_count(total_lines, issue_count)
        return DimensionResult(
            name=name,
            score=score,
            passed=score >= 50,
            details=f"{issue_count} lint issue(s) found.\n{output[:2000]}",
        )
    except subprocess.TimeoutExpired:
        return DimensionResult(name=name, score=0, passed=False, details="ruff timed out.")
    except Exception as e:
        return DimensionResult(name=name, score=0, passed=False, details=f"ruff error: {e}")


def score_type_safety(files: list[str]) -> DimensionResult:
    """Run mypy --strict, compute score."""
    name = "type_safety"
    py_files = _filter_python(files)
    if not py_files:
        return DimensionResult(name=name, score=100, passed=True, details="No Python files to check.")

    if not _tool_available("mypy"):
        return DimensionResult(
            name=name, score=0, passed=None, status="skipped",
            details="mypy not installed. Install with: pip install mypy",
        )

    try:
        result = _run_tool(["mypy", "--strict", "--no-color-output", *py_files])
        output = (result.stdout + result.stderr).strip()

        # Count error lines (lines containing "error:")
        error_lines = [ln for ln in output.splitlines() if "error:" in ln]
        issue_count = len(error_lines)
        total_lines = _count_lines(py_files)
        score = _score_from_issue_count(total_lines, issue_count)
        return DimensionResult(
            name=name,
            score=score,
            passed=score >= 50,
            details=f"{issue_count} type error(s).\n{output[:2000]}",
        )
    except subprocess.TimeoutExpired:
        return DimensionResult(name=name, score=0, passed=False, details="mypy timed out.")
    except Exception as e:
        return DimensionResult(name=name, score=0, passed=False, details=f"mypy error: {e}")


def score_security(files: list[str]) -> DimensionResult:
    """Run ruff S-rules + bandit, compute score."""
    name = "security"
    py_files = _filter_python(files)
    if not py_files:
        return DimensionResult(name=name, score=100, passed=True, details="No Python files to check.")

    # If neither ruff nor bandit is available, skip entirely
    has_ruff = _tool_available("ruff")
    has_bandit = _tool_available("bandit")
    if not has_ruff and not has_bandit:
        return DimensionResult(
            name=name, score=0, passed=None, status="skipped",
            details="Neither ruff nor bandit installed. Install with: pip install ruff bandit",
        )

    import re
    issues: list[str] = []
    # Track unique issue locations to deduplicate ruff + bandit overlap
    seen_locations: set[tuple[str, int]] = set()
    issue_count = 0

    def _add_unique_issue(filepath: str, line_no: int) -> bool:
        """Return True if this is a new unique location."""
        key = (filepath, line_no)
        if key in seen_locations:
            return False
        seen_locations.add(key)
        return True

    # --- ruff security rules (JSON output for structured parsing) ---
    if has_ruff:
        try:
            result = _run_tool(["ruff", "check", "--select=S", "--output-format=json", "--no-fix", *py_files])
            ruff_output = result.stdout.strip()
            ruff_count = 0
            if ruff_output:
                try:
                    ruff_json = _json.loads(ruff_output)
                    for item in ruff_json:
                        loc_file = item.get("filename", "")
                        loc_line = item.get("location", {}).get("row", 0)
                        if _add_unique_issue(loc_file, loc_line):
                            ruff_count += 1
                    issue_count += ruff_count
                    issues.append(f"ruff S-rules: {ruff_count} issue(s)")
                except _json.JSONDecodeError:
                    # Fallback: count lines from concise output
                    fallback = _run_tool(["ruff", "check", "--select=S", "--output-format=concise", "--no-fix", *py_files])
                    lines = fallback.stdout.strip().splitlines()
                    issue_count += len(lines)
                    ruff_count = len(lines)
                    issues.append(f"ruff S-rules: {ruff_count} issue(s) (fallback)")
            if ruff_count > 0:
                # Also get concise output for human-readable details
                concise = _run_tool(["ruff", "check", "--select=S", "--output-format=concise", "--no-fix", *py_files])
                issues.append(concise.stdout.strip()[:1000])
        except (subprocess.TimeoutExpired, Exception):
            issues.append("ruff security check failed or timed out.")
    else:
        issues.append("ruff not installed, skipping S-rules.")

    # --- bandit (JSON output for structured parsing + deduplication) ---
    if has_bandit:
        try:
            result = _run_tool(["bandit", "-r", "-f", "json", "-q", *py_files])
            bandit_output = result.stdout.strip()
            bandit_count = 0
            bandit_total = 0
            if bandit_output:
                try:
                    bandit_json = _json.loads(bandit_output)
                    bandit_results = bandit_json.get("results", [])
                    bandit_total = len(bandit_results)
                    for item in bandit_results:
                        loc_file = item.get("filename", "")
                        loc_line = item.get("line_number", 0)
                        if _add_unique_issue(loc_file, loc_line):
                            bandit_count += 1
                    deduplicated = bandit_total - bandit_count
                    issue_count += bandit_count
                    issues.append(f"bandit: {bandit_count} unique issue(s) ({deduplicated} deduplicated from {bandit_total} total)")
                except _json.JSONDecodeError:
                    # Fallback: text format
                    fallback = _run_tool(["bandit", "-r", "--format=text", "-q", *py_files])
                    fb_output = (fallback.stdout + fallback.stderr).strip()
                    bandit_lines = [ln for ln in fb_output.splitlines() if ln.strip().startswith(">>") or "Issue:" in ln]
                    issue_count += len(bandit_lines)
                    bandit_count = len(bandit_lines)
                    issues.append(f"bandit: {bandit_count} issue(s) (fallback, no dedup)")
            if bandit_count > 0:
                # Get text output for details
                text_result = _run_tool(["bandit", "-r", "--format=text", "-q", *py_files])
                issues.append((text_result.stdout + text_result.stderr).strip()[:1000])
        except (subprocess.TimeoutExpired, Exception):
            issues.append("bandit check failed or timed out.")
    else:
        issues.append("bandit not installed. Install with: pip install bandit")

    # --- Custom regex checks for patterns ruff/bandit miss ---
    custom_patterns = [
        # Path traversal: open() with f-string containing user variable
        (re.compile(r'open\(f["\'].*\{.*\}'), "Path traversal risk: open() with f-string variable"),
        # CORS wildcard: allow_origins with "*"
        (re.compile(r'''allow_origins.*\[.*["']\*["']'''), "CORS wildcard: allow_origins=['*'] allows all origins"),
    ]
    custom_count = 0
    for f in py_files:
        try:
            content = Path(f).read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), 1):
                for pattern, desc in custom_patterns:
                    if pattern.search(line):
                        loc = f"{f}:{i}"
                        if _add_unique_issue(f, i):
                            custom_count += 1
                            issues.append(f"custom: {loc} - {desc}")
        except (OSError, UnicodeDecodeError):
            continue
    issue_count += custom_count
    if custom_count > 0:
        issues.insert(0, f"custom security checks: {custom_count} issue(s)")

    total_lines = _count_lines(py_files)
    score = _score_from_issue_count(total_lines, issue_count)
    details = "\n".join(issues) if issues else "No security issues found."

    return DimensionResult(name=name, score=score, passed=score >= 50, details=details)


def score_secrets(files: list[str]) -> DimensionResult:
    """Run detect-secrets. Any leak = 0 points (hard gate)."""
    name = "secrets"
    if not files:
        return DimensionResult(name=name, score=100, passed=True, details="No files to scan.")

    if not _tool_available("detect-secrets"):
        # Fall back to simple regex scan
        import re
        secret_patterns = [
            re.compile(r"""(?:password|secret|api_key|token|apikey)\s*=\s*['"][^'"]{8,}['"]""", re.IGNORECASE),
            re.compile(r"""(?:sk-|ghp_|gho_|AKIA)[A-Za-z0-9+/=]{20,}"""),
        ]
        found: list[str] = []
        for f in files:
            try:
                content = Path(f).read_text(encoding="utf-8")
                for i, line in enumerate(content.splitlines(), 1):
                    for pat in secret_patterns:
                        if pat.search(line):
                            found.append(f"{f}:{i}")
                            break
            except (OSError, UnicodeDecodeError):
                continue

        if found:
            return DimensionResult(
                name=name, score=0, passed=False,
                details=f"Potential secrets found (regex fallback, detect-secrets not installed):\n" + "\n".join(found[:20]),
            )
        return DimensionResult(
            name=name, score=100, passed=True,
            details="No secrets detected (regex fallback, detect-secrets not installed).",
        )

    try:
        result = _run_tool(["detect-secrets", "scan", *files])
        scan_result = _json.loads(result.stdout)
        results_map = scan_result.get("results", {})
        total_secrets = sum(len(v) for v in results_map.values())

        if total_secrets > 0:
            detail_lines = []
            for filepath, secrets in results_map.items():
                for s in secrets:
                    detail_lines.append(f"  {filepath}:{s.get('line_number', '?')} - {s.get('type', 'unknown')}")
            return DimensionResult(
                name=name, score=0, passed=False,
                details=f"{total_secrets} secret(s) detected!\n" + "\n".join(detail_lines[:20]),
            )
        return DimensionResult(name=name, score=100, passed=True, details="No secrets detected.")
    except subprocess.TimeoutExpired:
        return DimensionResult(name=name, score=0, passed=False, details="detect-secrets timed out.")
    except Exception as e:
        return DimensionResult(name=name, score=0, passed=None, status="skipped", details=f"detect-secrets error: {e}")


def score_functional(files: list[str], test_cmd: str | None = None) -> DimensionResult:
    """Try to import modules + run tests."""
    name = "functional"
    py_files = _filter_python(files)
    if not py_files:
        return DimensionResult(name=name, score=100, passed=True, details="No Python files to check.")

    errors: list[str] = []
    importable = 0
    total = 0

    from harness.exec_verifier import verify_import

    for f in py_files:
        path = Path(f)
        if path.name.startswith("test_") or path.name.startswith("__"):
            continue
        total += 1
        # Use exec_verifier for proper import check (subprocess-isolated)
        result = verify_import(f)
        if result.passed:
            importable += 1
        else:
            errors.append(f"{result.error_type} in {f}: {result.error_message}")

    if total == 0:
        # 全部是 test/dunder 文件。如果传了 test_cmd，先跑测试；否则按 N/A 满分处理
        if test_cmd:
            from harness.exec_verifier import verify_tests
            test_result = verify_tests(test_cmd, timeout=120)
            if not test_result.passed:
                return DimensionResult(
                    name=name,
                    score=0,
                    passed=False,
                    details=f"All files are test/dunder, but test_cmd failed: {test_result.error_type}: {test_result.error_message}",
                )
            return DimensionResult(
                name=name,
                score=100,
                passed=True,
                details="No importable non-test Python files, but test_cmd passed.",
            )
        return DimensionResult(
            name=name,
            score=100,
            passed=True,
            details="No importable non-test Python files to check (all files are test_*.py or __*.py)",
        )

    import_score = int((importable / total) * 100)

    # Run tests if provided (using verify_tests for proper isolation)
    test_score = 100
    test_details = ""
    if test_cmd:
        from harness.exec_verifier import verify_tests
        test_result = verify_tests(test_cmd, timeout=120)
        if test_result.passed:
            test_details = "Tests passed."
        else:
            test_score = 0
            test_details = f"{test_result.error_type}: {test_result.error_message}"

    # Weighted: 60% import/compile, 40% test
    if test_cmd:
        score = int(import_score * 0.6 + test_score * 0.4)
    else:
        score = import_score

    details_parts = []
    if errors:
        details_parts.append(f"Compile errors:\n" + "\n".join(errors[:10]))
    details_parts.append(f"Compilable: {importable}/{total}")
    if test_details:
        details_parts.append(test_details)

    return DimensionResult(
        name=name,
        score=score,
        passed=score >= 50,
        details="\n".join(details_parts),
    )


def score_architecture(files: list[str]) -> DimensionResult:
    """Check custom architecture rules."""
    name = "architecture"
    py_files = _filter_python(files)
    if not py_files:
        return DimensionResult(name=name, score=100, passed=True, details="No Python files to check.")

    violations: list[str] = []

    for f in py_files:
        try:
            content = Path(f).read_text(encoding="utf-8")
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        filename = Path(f).name

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Rule 1: No bare except
            if stripped == "except:" or stripped.startswith("except: "):
                violations.append(f"{f}:{i} - Bare except clause (catch specific exceptions)")

            # Rule 2: No direct DB connection strings in code
            if "sqlite:///" in stripped or "postgresql://" in stripped or "mysql://" in stripped:
                if "test" not in filename and "config" not in filename:
                    violations.append(f"{f}:{i} - Hardcoded DB connection string (use config)")

            # Rule 3: No os.system calls (use subprocess)
            if "os.system(" in stripped:
                violations.append(f"{f}:{i} - os.system() call (use subprocess.run)")

            # Rule 4: No wildcard imports
            if stripped.startswith("from ") and "import *" in stripped:
                violations.append(f"{f}:{i} - Wildcard import (import specific names)")

            # Rule 5: No eval/exec on external input
            if ("eval(" in stripped or "exec(" in stripped) and "compile(" not in stripped:
                violations.append(f"{f}:{i} - eval()/exec() usage (potential code injection)")

        # Rule 7: File too large (>500 lines)
        if len(lines) > 500:
            violations.append(f"{f} - File has {len(lines)} lines (consider splitting, >500)")

    issue_count = len(violations)
    total_lines = _count_lines(py_files)
    score = _score_from_issue_count(total_lines, issue_count)
    details = "\n".join(violations[:20]) if violations else "No architecture violations found."

    return DimensionResult(name=name, score=score, passed=score >= 50, details=details)


def score_spec_compliance(files: list[str], spec_path: str | None = None) -> DimensionResult:
    """Check spec compliance. Delegates to spec_validator if spec_path given."""
    name = "spec_compliance"

    if not spec_path or not Path(spec_path).exists():
        return DimensionResult(
            name=name, score=70, passed=True,
            details="No spec file provided. Score based on code structure only.",
        )

    try:
        from harness.spec_validator import parse_spec, check_coverage

        code_dir = str(Path(files[0]).parent) if files else "."
        criteria = parse_spec(spec_path)
        if not criteria:
            return DimensionResult(name=name, score=80, passed=True, details="Spec has no parseable criteria.")

        report = check_coverage(criteria, code_dir)
        score = int(report.coverage_pct)
        uncovered_text = "\n".join(f"  - {c.condition} -> {c.expected_behavior}" for c in report.uncovered[:10])
        details = f"Coverage: {report.coverage_pct:.0f}% ({len(criteria) - len(report.uncovered)}/{len(criteria)} criteria)"
        if report.uncovered:
            details += f"\nUncovered:\n{uncovered_text}"

        return DimensionResult(name=name, score=score, passed=score >= 50, details=details)
    except Exception as e:
        return DimensionResult(name=name, score=50, passed=True, details=f"Spec check error: {e}")


def score_complexity(files: list[str]) -> DimensionResult:
    """Run radon for cyclomatic complexity and maintainability index."""
    name = "complexity"
    py_files = _filter_python(files)
    if not py_files:
        return DimensionResult(name=name, score=100, passed=True, details="No Python files to check.")

    if not _tool_available("radon"):
        return DimensionResult(
            name=name, score=0, passed=None, status="skipped",
            details="radon not installed. Install with: pip install radon",
        )

    details_parts: list[str] = []
    avg_cc: float | None = None
    avg_mi: float | None = None

    # --- Cyclomatic complexity ---
    try:
        result = _run_tool(["radon", "cc", "-a", "-j", *py_files])
        cc_data = _json.loads(result.stdout) if result.stdout.strip() else {}

        # Collect all complexity scores
        all_cc: list[float] = []
        for file_path, blocks in cc_data.items():
            if isinstance(blocks, list):
                for block in blocks:
                    if isinstance(block, dict) and "complexity" in block:
                        all_cc.append(block["complexity"])

        if all_cc:
            avg_cc = sum(all_cc) / len(all_cc)
            details_parts.append(f"Cyclomatic complexity: avg={avg_cc:.1f} across {len(all_cc)} block(s)")
        else:
            details_parts.append("Cyclomatic complexity: no blocks found")
    except (subprocess.TimeoutExpired, Exception) as e:
        details_parts.append(f"radon cc failed: {e}")

    # --- Maintainability index ---
    try:
        result = _run_tool(["radon", "mi", "-j", *py_files])
        mi_data = _json.loads(result.stdout) if result.stdout.strip() else {}

        mi_scores: list[float] = []
        for file_path, mi_info in mi_data.items():
            if isinstance(mi_info, dict) and "mi" in mi_info:
                mi_scores.append(mi_info["mi"])
            elif isinstance(mi_info, (int, float)):
                mi_scores.append(float(mi_info))

        if mi_scores:
            avg_mi = sum(mi_scores) / len(mi_scores)
            details_parts.append(f"Maintainability index: avg={avg_mi:.1f} across {len(mi_scores)} file(s)")
        else:
            details_parts.append("Maintainability index: no data")
    except (subprocess.TimeoutExpired, Exception) as e:
        details_parts.append(f"radon mi failed: {e}")

    # CC score: <=10 = 100, >=20 = 0, linear between
    cc_score: int | None = None
    if avg_cc is not None:
        if avg_cc <= 10:
            cc_score = 100
        elif avg_cc >= 20:
            cc_score = 0
        else:
            cc_score = int(100 * (20 - avg_cc) / 10)

    # MI score: radon MI ranges 0-100+ (higher = more maintainable), cap at 100
    mi_score: int | None = None
    if avg_mi is not None:
        mi_score = min(int(avg_mi), 100)

    # Blend: 60% CC + 40% MI. If one is missing, use the other at 100%.
    if cc_score is not None and mi_score is not None:
        score = int(cc_score * 0.6 + mi_score * 0.4)
    elif cc_score is not None:
        score = cc_score
    elif mi_score is not None:
        score = mi_score
    else:
        score = 80  # No data available; give benefit of doubt

    details = "\n".join(details_parts) if details_parts else "No complexity data."
    return DimensionResult(name=name, score=score, passed=score >= 50, details=details)


# ---------------------------------------------------------------------------
# Shared scoring helpers (used by both compute_reward and runner.check)
# ---------------------------------------------------------------------------

def compute_weighted_total(
    dimensions: list[DimensionResult],
    config: RewardConfig,
) -> float:
    """Compute weighted total score with re-normalization for evaluated dimensions.

    Skipped dimensions are excluded and their weights redistributed proportionally
    among evaluated dimensions, so the total always reflects a 0-100 scale.
    """
    evaluated = [(d, d.name) for d in dimensions if d.status == "evaluated"]
    if not evaluated:
        return 0.0

    raw_weight_sum = sum(config.weights.get(key, 0.0) for _, key in evaluated)
    if raw_weight_sum <= 0:
        return 0.0

    total = 0.0
    for dim, key in evaluated:
        weight = config.weights.get(key, 0.0)
        normalized = weight / raw_weight_sum
        total += dim.score * normalized

    return round(total, 1)


def compute_completeness(dimensions: list[DimensionResult]) -> str:
    """Determine completeness based on how many dimensions were skipped."""
    total_count = len(dimensions)
    skipped_count = sum(1 for d in dimensions if d.status == "skipped")
    if skipped_count == 0:
        return "complete"
    skip_ratio = skipped_count / total_count if total_count > 0 else 0
    if skip_ratio > 0.75:
        return "minimal"
    return "incomplete"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_reward(
    files: list[str],
    config: RewardConfig | None = None,
    spec_path: str | None = None,
    test_cmd: str | None = None,
) -> RewardReport:
    """Run all dimensions, compute weighted total score.

    Args:
        files: List of file paths to evaluate.
        config: Reward configuration (weights, gates, threshold).
        spec_path: Path to spec.md for compliance checking.
        test_cmd: Shell command to run tests.

    Returns:
        RewardReport with all dimension scores and aggregated result.
    """
    if config is None:
        config = RewardConfig()

    # Run each dimension
    dimensions: list[DimensionResult] = [
        score_functional(files, test_cmd=test_cmd),
        score_spec_compliance(files, spec_path=spec_path),
        score_type_safety(files),
        score_security(files),
        score_complexity(files),
        score_architecture(files),
        score_secrets(files),
        score_code_quality(files),
    ]

    # Map dimension names for weight lookup
    dim_weight_keys = [
        "functional", "spec_compliance", "type_safety",
        "security", "complexity", "architecture", "secrets", "code_quality",
    ]

    # Check hard gates
    blocked_by: str | None = None
    for dim, key in zip(dimensions, dim_weight_keys):
        if key in config.hard_gates:
            if dim.status == "evaluated" and dim.score < config.hard_gates[key]:
                blocked_by = dim.name
                break

    total = compute_weighted_total(dimensions, config)
    completeness = compute_completeness(dimensions)
    passed = blocked_by is None and total >= config.pass_threshold

    return RewardReport(
        dimensions=dimensions,
        total_score=total,
        passed=passed,
        blocked_by=blocked_by,
        completeness=completeness,
    )
