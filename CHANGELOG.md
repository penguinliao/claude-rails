# Changelog

All notable changes to Claude H-H (harness-engineering) are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/).

## [0.3.1] — 2026-04-17

First dogfood-driven bugfix release. Every change in this version walked
through its own pipeline (SPEC → IMPLEMENT → REVIEW → TEST) and is covered
by at least one AC script under `.harness/test_*.py`.

### Fixed

- **Security hard gate bypass for non-Python files** (`harness/reward.py`)
  `score_secrets` was filtering inputs to `.py` only, so a `.env` file
  containing an AWS-style key passed the `secrets` hard gate with score 100.
  Now scans the full input regardless of extension.
- **`score_functional` silently accepting failed tests** (`harness/reward.py`)
  When all input files were `test_*.py` (total importable = 0), the function
  returned 100 without running `test_cmd`. A failing pytest run was masked as
  a perfect score. Now `test_cmd` is honoured in the `total == 0` branch.
- **`stop_check` infinite loop on legitimate waits** (`hooks/stop_check.py`)
  The pipeline-incomplete block fired on every stop, including when Claude
  was asking the user a question or waiting on a background agent. Added
  three escape valves:
  - A: trailing `?`/`？`, `Y/N`/`X/Y` (case-insensitive), or Chinese asking
    phrases.
  - B: short responses (<300 chars) matching waiting patterns in Chinese
    (等待/稍等/处理中/…) and English (processing, waiting for, …).
  - C: loop-breaker — same normalized response blocks ≥3 times → release.
- **`stop_check` dead code referencing removed patterns**
  An unreachable text-scanning block was shadowed by an earlier marker check.
  Removed the block and the `_DEPLOY_DONE_PATTERNS` list.
- **`post_agent` false "missing test scripts" block** (`hooks/post_agent.py`)
  `project_root = ctx.project_root or os.getcwd()` fell back to the calling
  shell's cwd, which frequently is not the harness project root. Added a
  four-tier resolver: `ctx.project_root` → `$HARNESS_PROJECT` → walk-up
  `.harness/` search → `os.getcwd()`.
- **Bandit deduplication count showed 0** (`harness/reward.py`)
  The formula `bandit_count + len(seen_locations) - issue_count` simplifies
  to 0. Now reports `X unique issue(s) (M deduplicated from N total)`.

### Added

- **Decision log for stop hook**
  `stop_check` writes one line to `<project>/.harness/hook.log` whenever a
  pipeline-incomplete check reaches a decision (block or bypass A/B/C),
  making hook behaviour auditable.
- **Brief-requirement gate on SPEC→IMPLEMENT advance** (`harness/pipeline.py`,
  `harness/spec_file.py`)
  The SPEC stage now parses `## 测试策略` in `spec.md` and blocks advance if
  `小测审计: 需要` or `浊龙验收: 需要` is declared without the matching
  `.harness/<role>_brief.md` file.
- **Marker lifecycle on pipeline start/reset** (`harness/pipeline.py`,
  `hooks/pre_commit.py`)
  `/tmp/harness_tested_*` and `/tmp/harness_deployed_*` markers are cleared
  when a new pipeline starts or an existing one is reset. Test markers are
  written by a PostToolUse Bash hook when a real test command exits 0.
- **Code-file-write detection in Bash** (`hooks/pre_commit.py`)
  Detects `>` / `tee` / `sed -i` / `cp` / `mv` targeting `.py`/`.ts`/`.tsx`/
  `.vue`/`.js`/`.jsx` outside `/tmp/` and blocks them, forcing all code
  changes through `Edit`/`Write` tools and the standard gate.
- **IMPLEMENT-stage advance reminder** (`hooks/post_edit.py`)
  After a successful edit in Stage 3, the hook appends a reminder that
  advancing now would likely skip the remainder of the Agent's work.

### Changed

- **`hooks/post_edit.py`** now runs `fail-closed` — a crashed hook aborts
  instead of silently passing.
- **`hooks/pre_commit.py`** normalizes `ssh`/`scp` command matching to
  accept absolute paths (e.g. `/usr/bin/ssh …`).
- **Documentation** (`CLAUDE.md`)
  TEST stage documented as four gates (G1–G4) instead of three; hook count
  corrected from 5 to 6.

### Dogfood note

These fixes were discovered and validated by running Claude H-H on itself.
The third hotfix (stop_check escape valves) was caught in the wild by an
unrelated project session and fixed within the next dogfood cycle.

### Housekeeping

- Added `.claude/`, `findings.md`, `progress.md`, `task_plan.md` to
  `.gitignore` — these are per-session artifacts, not source.
- Aligned `pyproject.toml` version (`0.1.0` → `0.3.1`) with the versions
  already referenced in the README and `CLAUDE.md`.

## [0.3.0]

First `Claude H-H` branded release (rebrand from `Claude Rails`). See git
log for the commit-level changelog prior to the introduction of this file.
