"""
Pipeline State Machine — mechanical enforcement of the 5-stage development process.

Architecture: Opus (main agent) supervises, Sonnet (sub-agents) writes code.
PM provides requirements, then the pipeline runs fully automatically until testing completes.

State is persisted in {project_root}/.harness/pipeline.json.
Projects without this file: code writes are BLOCKED (must start pipeline first).

Stages:
  1 SPEC        — output acceptance criteria + file list (no code writes)
  2 DESIGN      — design architecture, define interfaces (no code writes)
  3 IMPLEMENT   — Sonnet agents write code (only stage allowing code writes)
  4 REVIEW      — Opus reviews code with fresh context (no code writes)
  5 TEST        — white-box + black-box testing (no code writes)

Routes (based on change size):
  micro:    3 → 4 → 5          (typo/style fixes)
  standard: 1 → 3 → 4 → 5     (1-3 files, skip design)
  full:     1 → 2 → 3 → 4 → 5 (4+ files or new features)

Loop: TEST/REVIEW fail → retreat to IMPLEMENT → fix → REVIEW → TEST (max 3 rounds)

Usage:
  python3 -m harness.pipeline start --route standard --desc "Add auth"
  python3 -m harness.pipeline status
  python3 -m harness.pipeline advance
  python3 -m harness.pipeline reset
  python3 -m harness.pipeline skip
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGE_NAMES = {
    1: "SPEC",
    2: "DESIGN",
    3: "IMPLEMENT",
    4: "REVIEW",
    5: "TEST",
    6: "DEPLOY",
}

# Only IMPLEMENT stage allows code writes — Sonnet agents write code here.
# REVIEW and TEST stages must NOT write code (separation of writer and reviewer).
_CODE_WRITE_STAGES = {3}

# Route definitions: which stages to visit
ROUTES = {
    "micro":           [3, 4, 5],         # typo/style: implement → review → test
    "standard":        [1, 3, 4, 5],      # 1-3 files: spec → implement → review → test
    "full":            [1, 2, 3, 4, 5],   # 4+ files: spec → design → implement → review → test
    "standard-deploy": [1, 3, 4, 5, 6],   # standard + deploy stage
    "full-deploy":     [1, 2, 3, 4, 5, 6], # full + deploy stage
}

# Code file extensions that pipeline gates check
_CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".html", ".css",
    ".scss", ".svelte", ".go", ".rs", ".java", ".kt", ".swift",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StageEntry:
    """Record of a stage transition."""
    stage: int
    status: str       # IN_PROGRESS | PASS | FAIL | SKIPPED
    timestamp: str = ""
    duration_s: int = 0
    note: str = ""


@dataclass
class PipelineState:
    """Current pipeline state."""
    version: int = 3
    current_stage: int = 0
    stage_name: str = ""
    task_description: str = ""
    route: str = "standard"
    route_stages: list[int] = field(default_factory=list)
    history: list[StageEntry] = field(default_factory=list)
    spec_path: str | None = None
    affected_files: list[str] = field(default_factory=list)
    consecutive_fails: int = 0  # Consecutive FAIL count for current stage
    risk_level: str = "standard"  # micro/small/standard，由hook自动计算
    started_at: str = ""
    updated_at: str = ""


@dataclass
class AdvanceResult:
    """Result of attempting to advance to next stage."""
    ok: bool
    new_stage: int = 0
    new_stage_name: str = ""
    reason: str = ""
    completed: bool = False  # True when last stage is done


# ---------------------------------------------------------------------------
# State file operations
# ---------------------------------------------------------------------------

def _state_path(project_root: str) -> Path:
    """Path to pipeline state file."""
    return Path(project_root) / ".harness" / "pipeline.json"


def get_state(project_root: str) -> PipelineState | None:
    """Read pipeline state. Returns None if no pipeline active."""
    path = _state_path(project_root)
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        state = PipelineState(
            version=data.get("version", 2),
            current_stage=data.get("current_stage", 0),
            stage_name=data.get("stage_name", ""),
            task_description=data.get("task_description", ""),
            route=data.get("route", "standard"),
            route_stages=data.get("route_stages", []),
            spec_path=data.get("spec_path"),
            affected_files=data.get("affected_files", []),
            consecutive_fails=data.get("consecutive_fails", 0),
            risk_level=data.get("risk_level", "standard"),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
        )
        # Parse history
        for h in data.get("history", []):
            state.history.append(StageEntry(
                stage=h.get("stage", 0),
                status=h.get("status", ""),
                timestamp=h.get("timestamp", ""),
                duration_s=h.get("duration_s", 0),
                note=h.get("note", ""),
            ))
        return state
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _save_state(project_root: str, state: PipelineState) -> None:
    """Write pipeline state to disk using atomic write (temp + rename).

    v3.2: Prevents corruption from concurrent writes or crashes mid-write.
    """
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    state.updated_at = datetime.now().isoformat()
    state.stage_name = STAGE_NAMES.get(state.current_stage, "UNKNOWN")

    data = {
        "version": state.version,
        "current_stage": state.current_stage,
        "stage_name": state.stage_name,
        "task_description": state.task_description,
        "route": state.route,
        "route_stages": state.route_stages,
        "history": [asdict(h) for h in state.history],
        "spec_path": state.spec_path,
        "affected_files": state.affected_files,
        "consecutive_fails": state.consecutive_fails,
        "risk_level": state.risk_level,
        "started_at": state.started_at,
        "updated_at": state.updated_at,
    }

    import tempfile
    content = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix="pipeline_",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(path))  # atomic on same filesystem
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Pipeline operations
# ---------------------------------------------------------------------------

def start(
    project_root: str,
    description: str,
    route: str = "standard",
) -> PipelineState:
    """Start a new pipeline run.

    Args:
        project_root: Path to project root.
        description: What this task is about.
        route: One of "micro", "standard", "full".

    Returns:
        New PipelineState.
    """
    if route not in ROUTES:
        route = "standard"

    route_stages = ROUTES[route]
    first_stage = route_stages[0]
    now = datetime.now().isoformat()

    state = PipelineState(
        current_stage=first_stage,
        stage_name=STAGE_NAMES.get(first_stage, ""),
        task_description=description,
        route=route,
        route_stages=route_stages,
        history=[StageEntry(stage=first_stage, status="IN_PROGRESS", timestamp=now)],
        started_at=now,
    )

    _save_state(project_root, state)
    return state


_RISK_LEVELS = {"micro": 0, "small": 1, "standard": 2}


def advance(project_root: str, note: str = "") -> AdvanceResult:
    """Advance to next stage after validating exit criteria.

    Exit criteria:
      Stage 2 (SPEC): .harness/spec.md must exist and be valid
      Other stages: no special validation (AI self-reports completion)

    Returns:
        AdvanceResult with success/failure and reason.
    """
    state = get_state(project_root)
    if state is None:
        return AdvanceResult(ok=False, reason="No active pipeline. Use 'start' first.")

    # v3.2 R7: Self-heal if current_stage is invalid
    if state.route_stages and state.current_stage not in state.route_stages:
        old = state.current_stage
        state.current_stage = state.route_stages[0]
        state.stage_name = STAGE_NAMES.get(state.current_stage, "")
        _save_state(project_root, state)
        return AdvanceResult(
            ok=False,
            reason=f"Pipeline状态异常(stage {old} 不在路由 {state.route_stages} 中)，已自愈到 Stage {state.current_stage}。请重新advance。",
        )

    current = state.current_stage

    # v3.5: Advance cooldown — prevent rapid-fire advancing through stages
    if state.risk_level != "micro" and state.history:
        last_ts = state.history[-1].timestamp
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds()
            if elapsed < 30:
                return AdvanceResult(
                    ok=False,
                    reason=f"advance冷却中（距上次{elapsed:.0f}秒，需等待{30-elapsed:.0f}秒）。"
                           f"非micro路由每次advance间隔至少30秒。",
                )
        except (ValueError, TypeError):
            pass  # 时间解析失败不阻塞

    # Validate exit criteria for current stage
    if current == 1:  # SPEC stage requires spec file
        # SPEC阶段根据risk_level调档
        if state.risk_level == "micro":
            # micro: 跳过spec.md检查，允许直接advance
            pass  # 不检查spec.md
        else:
            # small/standard: 使用现有完整检查逻辑
            from harness.spec_file import find_spec, validate_spec
            spec_path = find_spec(project_root)
            if not spec_path:
                return AdvanceResult(
                    ok=False,
                    reason="Stage 1 (SPEC) requires .harness/spec.md — please generate it first.",
                )
            validation = validate_spec(spec_path, route=state.route)
            if not validation.valid:
                # v3.2: Hard gate only if spec is empty or unreadable.
                # Format mismatch (criteria_count=0 but content exists) → warn, not block.
                if validation.error:
                    # File missing, unreadable, empty — hard block
                    return AdvanceResult(
                        ok=False,
                        reason=f"spec.md validation failed: {validation.error}",
                    )
                # Format warnings only — degrade gracefully, allow advance with warning
                warnings_text = "; ".join(validation.warnings)
                print(f"[harness] ⚠️ spec.md format warning (降级通过): {warnings_text}")
            state.spec_path = spec_path

    elif current == 4:  # REVIEW stage — harness physically runs check_standard
        if state.risk_level == "micro":
            # micro: 跳过review（真的只改了10行以内的非敏感文件）
            pass
        else:
            # Gate 1: harness runs check_standard on affected files
            from harness.spec_file import find_spec, extract_affected_files
            spec_path = find_spec(project_root)
            affected_files: list[str] = []
            if spec_path:
                raw_files = extract_affected_files(spec_path)
                for f in raw_files:
                    full = os.path.join(project_root, f)
                    if os.path.isfile(full) and f.endswith(".py"):
                        affected_files.append(full)

            if affected_files:
                try:
                    from harness.runner import check_standard
                    report = check_standard(affected_files)
                    # Distinguish "real failures" from "tools unavailable"
                    evaluated = [d for d in report.dimensions if d.status == "evaluated"]
                    if not report.passed and evaluated:
                        blocked = f" (blocked by: {report.blocked_by})" if report.blocked_by else ""
                        details = []
                        for dim in evaluated:
                            if not dim.passed:
                                details.append(f"  - {dim.name}: {dim.score}/100")
                        detail_str = "\n".join(details[:5])
                        fail_reason = (
                            f"REVIEW自动检查未通过（总分{report.total_score:.0f}/100）{blocked}\n"
                            f"未通过的维度:\n{detail_str}\n"
                            f"请retreat回IMPLEMENT修复后重新审查。"
                        )
                        state.history.append(StageEntry(
                            stage=current, status="FAIL",
                            timestamp=datetime.now().isoformat(),
                            note=fail_reason,
                        ))
                        _save_state(project_root, state)
                        return AdvanceResult(
                            ok=False,
                            reason=fail_reason,
                        )
                    if evaluated:
                        print(f"[harness] ✅ REVIEW自动检查通过（{report.total_score:.0f}/100）")
                    else:
                        print("[harness] ⚠️ REVIEW检查工具不可用，降级通过")
                except Exception as exc:
                    # fail-closed: 检查异常时拒绝advance
                    return AdvanceResult(
                        ok=False,
                        reason=f"REVIEW自动检查异常: {exc}。请确认工具已安装（ruff/mypy/bandit）。",
                    )

    elif current == 5:  # TEST stage — harness physically runs test scripts
        if state.risk_level == "micro":
            # micro: skip AC coverage check, but still execute test scripts if they exist
            import glob as _glob_m
            import subprocess as _sp_m
            harness_dir_m = os.path.join(project_root, ".harness")
            micro_scripts = sorted(_glob_m.glob(os.path.join(harness_dir_m, "test_*.py")))
            if micro_scripts:
                for script in micro_scripts:
                    try:
                        res = _sp_m.run(
                            ["python3", script], cwd=project_root,
                            capture_output=True, text=True, timeout=60,
                        )
                        if res.returncode != 0:
                            return AdvanceResult(
                                ok=False,
                                reason=f"micro测试脚本失败：{os.path.basename(script)} "
                                       f"(exit {res.returncode})\n{(res.stderr or '')[-300:]}",
                            )
                    except Exception as exc:
                        print(f"[harness] ⚠️ micro测试脚本执行异常：{os.path.basename(script)} ({exc})")
                print(f"[harness] ✅ micro TEST：{len(micro_scripts)}个脚本通过")
            # No test scripts for micro → pass (it's really just a typo fix)
        else:
            import glob as _glob
            import subprocess as _sp

            harness_dir = os.path.join(project_root, ".harness")
            test_scripts = sorted(_glob.glob(os.path.join(harness_dir, "test_*.py")))

            # Gate 1: test scripts must exist
            if not test_scripts:
                return AdvanceResult(
                    ok=False,
                    reason="Stage 5 (TEST) requires test scripts in .harness/test_*.py — "
                           "在 IMPLEMENT 阶段必须同时编写可执行的测试脚本。"
                           "脚本要求：exit 0 表示通过，非零表示失败。",
                )

            # Gate 2: harness executes each test script, checks exit code
            failed_scripts: list[str] = []
            for script in test_scripts:
                try:
                    result = _sp.run(
                        ["python3", script],
                        cwd=project_root,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode != 0:
                        script_name = os.path.basename(script)
                        stderr_tail = (result.stderr or "")[-500:]
                        failed_scripts.append(f"{script_name} (exit {result.returncode}): {stderr_tail}")
                except _sp.TimeoutExpired:
                    failed_scripts.append(f"{os.path.basename(script)} (timeout 120s)")
                except Exception as exc:
                    failed_scripts.append(f"{os.path.basename(script)} (error: {exc})")

            if failed_scripts:
                detail = "\n".join(failed_scripts[:5])
                fail_reason = (
                    f"测试脚本执行失败（{len(failed_scripts)}/{len(test_scripts)}）:\n{detail}\n"
                    f"请retreat回IMPLEMENT修复后重新测试。"
                )
                state.history.append(StageEntry(
                    stage=current, status="FAIL",
                    timestamp=datetime.now().isoformat(),
                    note=fail_reason,
                ))
                _save_state(project_root, state)
                return AdvanceResult(
                    ok=False,
                    reason=fail_reason,
                )

            print(f"[harness] ✅ TEST通过：{len(test_scripts)}个测试脚本全部exit 0")

            # Gate 2: 小测审计报告（如果有 brief 就必须有 report）
            xiaoce_brief = os.path.join(harness_dir, "xiaoce_brief.md")
            xiaoce_report = os.path.join(harness_dir, "xiaoce_report.md")
            if os.path.isfile(xiaoce_brief):
                if not os.path.isfile(xiaoce_report):
                    return AdvanceResult(
                        ok=False,
                        reason="小测审计任务书(xiaoce_brief.md)已定义，但未找到审计报告(xiaoce_report.md)。\n"
                               "请派小测Agent执行白盒审计后再advance。",
                    )
                with open(xiaoce_report, encoding="utf-8") as _xr_f:
                    report_content = _xr_f.read().strip()
                if not report_content:
                    return AdvanceResult(
                        ok=False,
                        reason="小测审计报告(xiaoce_report.md)为空。请确保小测完成审计并写入报告。",
                    )
                print("[harness] ✅ Gate 2: 小测审计报告已确认")

            # Gate 3: 浊龙验收报告（如果有 brief 就必须有 report）
            zhuolong_brief = os.path.join(harness_dir, "zhuolong_brief.md")
            zhuolong_report = os.path.join(harness_dir, "zhuolong_report.md")
            if os.path.isfile(zhuolong_brief):
                if not os.path.isfile(zhuolong_report):
                    return AdvanceResult(
                        ok=False,
                        reason="浊龙交付单(zhuolong_brief.md)已定义，但未找到验收报告(zhuolong_report.md)。\n"
                               "请派浊龙Agent执行黑盒验收后再advance。",
                    )
                with open(zhuolong_report, encoding="utf-8") as _zlr_f:
                    report_content = _zlr_f.read().strip()
                if not report_content:
                    return AdvanceResult(
                        ok=False,
                        reason="浊龙验收报告(zhuolong_report.md)为空。请确保浊龙完成验收并写入报告。",
                    )
                print("[harness] ✅ Gate 3: 浊龙验收报告已确认")

            # AC awareness — log for reference, don't enforce count match.
            # One test script can cover multiple ACs. The real gate is
            # Gate 1+2 (scripts exist AND exit 0), not script count.
            from harness.spec_file import find_spec, extract_acceptance_criteria
            spec_path = find_spec(project_root)
            if spec_path:
                ac_list = extract_acceptance_criteria(spec_path)
                if ac_list:
                    print(f"[harness] 📋 spec有{len(ac_list)}条AC，{len(test_scripts)}个测试脚本覆盖")

    # Find next stage in route
    try:
        current_idx = state.route_stages.index(current)
    except ValueError:
        return AdvanceResult(
            ok=False,
            reason=f"Stage {current} is not in route {state.route_stages}. Use 'reset' to clear.",
        )

    if current_idx >= len(state.route_stages) - 1:
        # Last stage done — pipeline complete
        now = datetime.now().isoformat()
        state.history.append(StageEntry(
            stage=current, status="PASS", timestamp=now, note=note,
        ))
        _save_state(project_root, state)

        # Skill extraction: learn from retreats
        try:
            from harness.skill_extractor import extract_skill
            skill_path = extract_skill(project_root)
            if skill_path:
                print(f"[harness] 经验已沉淀: {os.path.basename(skill_path)}")
        except Exception:
            pass  # Skill extraction failure must not block pipeline completion

        return AdvanceResult(
            ok=True, new_stage=current,
            new_stage_name=STAGE_NAMES.get(current, ""),
            reason="Pipeline complete!",
            completed=True,
        )

    next_stage = state.route_stages[current_idx + 1]
    now = datetime.now().isoformat()

    # Record completion of current stage
    state.history.append(StageEntry(
        stage=current, status="PASS", timestamp=now, note=note,
    ))

    # Move to next stage
    state.current_stage = next_stage
    state.consecutive_fails = 0  # Reset fail count on successful advance
    state.history.append(StageEntry(
        stage=next_stage, status="IN_PROGRESS", timestamp=now,
    ))

    _save_state(project_root, state)

    return AdvanceResult(
        ok=True,
        new_stage=next_stage,
        new_stage_name=STAGE_NAMES.get(next_stage, ""),
        reason=f"Advanced to Stage {next_stage} ({STAGE_NAMES.get(next_stage, '')})",
    )


def is_code_write_allowed(project_root: str, file_path: str = "") -> tuple[bool, str]:
    """Check if a code write (Edit/Write) is allowed in the current pipeline stage.

    Args:
        project_root: Path to project root.
        file_path: The file being edited (used to check if it's a code file).

    Returns:
        (allowed, reason) tuple.
    """
    # Check if the file is a code file (non-code files like spec.md are always allowed)
    if file_path:
        ext = Path(file_path).suffix.lower()
        if ext not in _CODE_EXTENSIONS:
            return True, ""  # Non-code files (md, json, yaml, etc.) always allowed

    # harness-engineering eats its own dogfood: no pipeline stage exemption.
    # Only spec scope check has a self-edit exemption (in pre_edit.py) to avoid
    # circular dependency (harness can't list itself in its own spec).

    state = get_state(project_root)

    # No pipeline active → BLOCK code writes (must start pipeline first)
    if state is None:
        return False, (
            "No active pipeline. Code writes are blocked until a pipeline is started.\n"
            "Run: python3 -m harness.pipeline start --route standard --desc \"your task\"\n"
            "Or for small changes: python3 -m harness.pipeline start --route micro --desc \"your task\""
        )

    # v3.6: Pipeline expiration — stale pipelines cannot be reused for new tasks.
    # Active development updates updated_at every few minutes. 4+ hours of inactivity
    # means a different session/task — AI must start a fresh pipeline.
    _EXPIRY_HOURS = 4
    if state.updated_at:
        try:
            _last = datetime.fromisoformat(state.updated_at)
            _hours = (datetime.now() - _last).total_seconds() / 3600
            if _hours > _EXPIRY_HOURS:
                return False, (
                    f"Pipeline已过期（{_hours:.0f}小时未活动）。\n"
                    f"旧pipeline不能用于新任务，请先reset再启动新pipeline：\n"
                    f"  python3 -m harness.pipeline reset\n"
                    f"  python3 -m harness.pipeline start --route standard --desc \"新任务描述\""
                )
        except (ValueError, TypeError):
            pass  # 时间解析失败不阻塞

    # v3.1: Self-heal — if current_stage is not in route_stages, reset to IMPLEMENT
    if state.current_stage not in state.route_stages and state.route_stages:
        state.current_stage = 3 if 3 in state.route_stages else state.route_stages[0]
        state.stage_name = STAGE_NAMES.get(state.current_stage, "")
        _save_state(project_root, state)

    # Check stage — only IMPLEMENT (stage 3) allows code writes
    if state.current_stage in _CODE_WRITE_STAGES:
        return True, ""

    stage_name = STAGE_NAMES.get(state.current_stage, str(state.current_stage))
    return False, (
        f"Stage {state.current_stage} ({stage_name}): code writes not allowed.\n"
        f"Only Stage 3 (IMPLEMENT) allows code writes.\n"
        f"Complete this stage first, then run: python3 -m harness.pipeline advance"
    )


def reset(project_root: str) -> None:
    """Remove pipeline state. Escape hatch for stuck pipelines."""
    path = _state_path(project_root)
    if path.is_file():
        path.unlink()


def skip(project_root: str, reason: str = "") -> AdvanceResult:
    """Skip current stage without validation. Emergency use only.
    REVIEW(4) and TEST(5) cannot be skipped — they are mandatory gates.
    """
    state = get_state(project_root)
    if state is None:
        return AdvanceResult(ok=False, reason="No active pipeline.")

    # REVIEW and TEST are mandatory — cannot skip
    if state.current_stage in (4, 5):
        stage_name = STAGE_NAMES.get(state.current_stage, "")
        return AdvanceResult(
            ok=False,
            reason=f"Stage {state.current_stage} ({stage_name}) 不允许skip，"
                   f"必须完成审查/测试后用advance推进。",
        )

    # Force advance without exit criteria check
    try:
        current_idx = state.route_stages.index(state.current_stage)
    except ValueError:
        return AdvanceResult(ok=False, reason="Current stage not in route.")

    if current_idx >= len(state.route_stages) - 1:
        reset(project_root)
        return AdvanceResult(ok=True, completed=True, reason="Pipeline complete (skipped).")

    next_stage = state.route_stages[current_idx + 1]
    now = datetime.now().isoformat()

    state.history.append(StageEntry(
        stage=state.current_stage, status="SKIPPED", timestamp=now,
    ))
    state.current_stage = next_stage
    state.history.append(StageEntry(
        stage=next_stage, status="IN_PROGRESS", timestamp=now,
    ))

    _save_state(project_root, state)

    return AdvanceResult(
        ok=True,
        new_stage=next_stage,
        new_stage_name=STAGE_NAMES.get(next_stage, ""),
        reason=f"Skipped to Stage {next_stage} ({STAGE_NAMES.get(next_stage, '')})",
    )


MAX_CONSECUTIVE_FAILS = 3


@dataclass
class FailResult:
    """Result of recording a stage failure."""
    ok: bool
    retries_left: int = 0
    should_stop: bool = False  # True when MAX_CONSECUTIVE_FAILS reached
    reason: str = ""


def fail(project_root: str, reason: str = "") -> FailResult:
    """Record a FAIL for the current stage and stay (for retry).

    After MAX_CONSECUTIVE_FAILS, signals that AI should stop and report to user.
    Does NOT automatically move stages — AI decides whether to retry or escalate.
    """
    state = get_state(project_root)
    if state is None:
        return FailResult(ok=False, reason="No active pipeline.")

    now = datetime.now().isoformat()
    state.consecutive_fails += 1
    state.history.append(StageEntry(
        stage=state.current_stage, status="FAIL", timestamp=now, note=reason,
    ))

    _save_state(project_root, state)

    retries_left = MAX_CONSECUTIVE_FAILS - state.consecutive_fails
    if retries_left <= 0:
        return FailResult(
            ok=True,
            retries_left=0,
            should_stop=True,
            reason=f"Stage {state.current_stage} failed {state.consecutive_fails} times consecutively. Stop and report to user.",
        )

    return FailResult(
        ok=True,
        retries_left=retries_left,
        reason=f"Stage {state.current_stage} failed ({state.consecutive_fails}/{MAX_CONSECUTIVE_FAILS}). {retries_left} retries left.",
    )


def retreat(project_root: str, target_stage: int, reason: str = "") -> AdvanceResult:
    """Retreat to an earlier stage for fixing. Used when Stage 5/6 fails.

    Only allows retreating to stages in the current route that are <= current stage.
    Resets consecutive_fails counter.

    Args:
        project_root: Path to project root.
        target_stage: Stage number to retreat to.
        reason: Human-readable reason for retreating (stored in FAIL history entry).
    """
    state = get_state(project_root)
    if state is None:
        return AdvanceResult(ok=False, reason="No active pipeline.")

    if target_stage not in state.route_stages:
        return AdvanceResult(ok=False, reason=f"Stage {target_stage} is not in route {state.route_stages}.")

    if target_stage >= state.current_stage:
        return AdvanceResult(ok=False, reason=f"Can only retreat to earlier stages (current: {state.current_stage}).")

    now = datetime.now().isoformat()
    state.history.append(StageEntry(
        stage=state.current_stage, status="FAIL", timestamp=now,
        note=reason if reason else f"Retreating to Stage {target_stage}",
    ))
    state.current_stage = target_stage
    state.consecutive_fails = 0
    state.history.append(StageEntry(
        stage=target_stage, status="IN_PROGRESS", timestamp=now,
    ))

    _save_state(project_root, state)

    return AdvanceResult(
        ok=True,
        new_stage=target_stage,
        new_stage_name=STAGE_NAMES.get(target_stage, ""),
        reason=f"Retreated to Stage {target_stage} ({STAGE_NAMES.get(target_stage, '')})",
    )


def status(project_root: str) -> str:
    """Human-readable pipeline status."""
    state = get_state(project_root)
    if state is None:
        return "No active pipeline."

    lines = [
        f"━━━ Pipeline Status ━━━",
        f"  Task: {state.task_description}",
        f"  Route: {state.route} ({' → '.join(str(s) for s in state.route_stages)})",
        f"  Current: Stage {state.current_stage} ({state.stage_name})",
        f"  Started: {state.started_at}",
        "",
        "  History:",
    ]

    for h in state.history:
        name = STAGE_NAMES.get(h.stage, str(h.stage))
        lines.append(f"    Stage {h.stage} ({name}): {h.status} {h.note}")

    if state.spec_path:
        lines.append(f"\n  Spec: {state.spec_path}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Risk level management
# ---------------------------------------------------------------------------

def update_risk_level(project_root: str) -> str:
    """调用风险分析器，更新pipeline.json中的risk_level。

    v3.5 Ratchet机制：risk_level只能升不能降。
    防止大改动通过中途小改自动降级到micro/small绕过REVIEW/TEST检查。

    Returns:
        更新后的risk_level字符串（"micro"/"small"/"standard"）
    """
    import logging
    logger = logging.getLogger(__name__)

    state = get_state(project_root)
    if not state:
        return "standard"

    try:
        from harness.risk_analyzer import analyze_risk
        proposed_level = analyze_risk(project_root)
    except Exception as e:
        logger.warning(f"风险分析失败，默认standard: {e}")
        proposed_level = "standard"

    # Ratchet: only allow risk_level to go UP, never down
    current_val = _RISK_LEVELS.get(state.risk_level, 2)
    proposed_val = _RISK_LEVELS.get(proposed_level, 2)

    if proposed_val > current_val:
        # 升级：允许
        old_level = state.risk_level
        state.risk_level = proposed_level
        _save_state(project_root, state)
        logger.info(f"[Pipeline] risk_level升级: {old_level} → {proposed_level}")
        return proposed_level
    elif proposed_val < current_val:
        # 降级：拒绝（ratchet）
        logger.info(
            f"[Pipeline] risk_level ratchet: 拒绝从 {state.risk_level} 降到 {proposed_level}"
        )
        return state.risk_level
    else:
        return state.risk_level


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args:
        print("Usage: python3 -m harness.pipeline <command> [options]")
        print("Commands: start, advance, status, reset, skip")
        sys.exit(1)

    cmd = args[0]
    # Default project root: current directory
    project = os.getcwd()

    if cmd == "start":
        desc = "unnamed task"
        route = "standard"
        i = 1
        while i < len(args):
            arg = args[i]
            if arg.startswith("--desc="):
                desc = arg.split("=", 1)[1]
            elif arg == "--desc" and i + 1 < len(args):
                i += 1; desc = args[i]
            elif arg.startswith("--route="):
                route = arg.split("=", 1)[1]
            elif arg == "--route" and i + 1 < len(args):
                i += 1; route = args[i]
            elif arg.startswith("--project="):
                project = arg.split("=", 1)[1]
            elif arg == "--project" and i + 1 < len(args):
                i += 1; project = args[i]
            i += 1
        state = start(project, desc, route)
        print(f"Pipeline started: Stage {state.current_stage} ({state.stage_name})")
        print(f"Route: {state.route} ({' → '.join(str(s) for s in state.route_stages)})")
        print(f"Set HARNESS_PROJECT if code files are outside this directory:")
        print(f"  export HARNESS_PROJECT={project}")

    elif cmd == "advance":
        note = ""
        for arg in args[1:]:
            if arg.startswith("--note="):
                note = arg.split("=", 1)[1]
            elif arg.startswith("--project="):
                project = arg.split("=", 1)[1]
        result = advance(project, note)
        if result.ok:
            if result.completed:
                print("Pipeline complete!")
            else:
                print(f"Advanced to Stage {result.new_stage} ({result.new_stage_name})")
        else:
            print(f"Cannot advance: {result.reason}")
            sys.exit(1)

    elif cmd == "status":
        for arg in args[1:]:
            if arg.startswith("--project="):
                project = arg.split("=", 1)[1]
        print(status(project))

    elif cmd == "reset":
        for arg in args[1:]:
            if arg.startswith("--project="):
                project = arg.split("=", 1)[1]
        reset(project)
        print("Pipeline state cleared.")

    elif cmd == "skip":
        for arg in args[1:]:
            if arg.startswith("--project="):
                project = arg.split("=", 1)[1]
        result = skip(project)
        print(result.reason)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
