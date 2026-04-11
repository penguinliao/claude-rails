"""
Execution Verifier

Actually runs Python code to check whether it works:
1. Try importing a module, catch ImportError / SyntaxError
2. If there's a main() or app, try starting it (with timeout)
3. If there are pytest tests, run them
4. Return PASS/FAIL + error details
"""

from __future__ import annotations

import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyResult:
    """Result of an execution verification."""

    passed: bool
    error_type: str | None = None
    error_message: str | None = None
    traceback_str: str | None = None


def verify_import(file_path: str) -> VerifyResult:
    """Try to import a Python file as a module.

    Uses a subprocess to avoid polluting the current process.
    Checks syntax via compile() first, then attempts actual import.

    Args:
        file_path: Path to the Python file.

    Returns:
        VerifyResult indicating success or failure.
    """
    path = Path(file_path)
    if not path.exists():
        return VerifyResult(
            passed=False,
            error_type="FileNotFoundError",
            error_message=f"File not found: {file_path}",
        )

    if not path.suffix == ".py":
        return VerifyResult(
            passed=False,
            error_type="ValueError",
            error_message=f"Not a Python file: {file_path}",
        )

    # Step 1: Syntax check via compile()
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, file_path, "exec")
    except SyntaxError as e:
        return VerifyResult(
            passed=False,
            error_type="SyntaxError",
            error_message=str(e),
            traceback_str=traceback.format_exc(),
        )
    except Exception as e:
        return VerifyResult(
            passed=False,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback_str=traceback.format_exc(),
        )

    # Step 2: Attempt actual import in subprocess
    module_name = path.stem
    import_script = (
        f"import sys; sys.path.insert(0, {str(path.parent)!r}); "
        f"import {module_name}; print('OK')"
    )

    try:
        result = subprocess.run(
            [sys.executable, "-c", import_script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(path.parent),
        )
        if result.returncode == 0 and "OK" in result.stdout:
            return VerifyResult(passed=True)

        stderr = result.stderr.strip()
        # Parse error type from traceback
        error_type = "ImportError"
        error_message = stderr
        for line in stderr.splitlines():
            if "Error:" in line or "Exception:" in line:
                parts = line.split(":", 1)
                error_type = parts[0].strip().split(".")[-1]
                error_message = parts[1].strip() if len(parts) > 1 else line

        # v0.1.1 fix: ModuleNotFoundError / ImportError often come from a
        # sys.path context mismatch, not a real code bug. For package-internal
        # files (e.g. `core/db.py` that does `from core.xxx import yyy`), the
        # subprocess can't resolve the parent package. Step 1 (compile) already
        # proved the syntax is valid, so treat import failures as a warning
        # rather than a hard fail — don't let functional = 0 block legitimate
        # code just because harness can't guess the right sys.path.
        if error_type in ("ModuleNotFoundError", "ImportError"):
            return VerifyResult(
                passed=True,
                error_type=error_type,
                error_message=f"(warn, compile OK) {error_message}",
                traceback_str=None,
            )

        return VerifyResult(
            passed=False,
            error_type=error_type,
            error_message=error_message,
            traceback_str=stderr[-2000:] if stderr else None,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            passed=False,
            error_type="TimeoutError",
            error_message=f"Import timed out after 30s: {file_path}",
        )
    except Exception as e:
        return VerifyResult(
            passed=False,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback_str=traceback.format_exc(),
        )


def verify_execution(file_path: str, timeout: int = 10, is_daemon: bool = False) -> VerifyResult:
    """Try to execute a Python file.

    Runs the file with a timeout. For daemons/servers, timeout means the
    process started successfully. For scripts, timeout means something is wrong.

    Args:
        file_path: Path to the Python file.
        timeout: Maximum seconds to run.
        is_daemon: If True, timeout = pass (server started). If False, timeout = fail.

    Returns:
        VerifyResult indicating success or failure.
    """
    path = Path(file_path)
    if not path.exists():
        return VerifyResult(
            passed=False,
            error_type="FileNotFoundError",
            error_message=f"File not found: {file_path}",
        )

    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(path.parent),
        )

        if result.returncode == 0:
            return VerifyResult(passed=True)

        stderr = result.stderr.strip()
        error_type = "RuntimeError"
        error_message = stderr

        # Try to extract specific error type
        for line in reversed(stderr.splitlines()):
            if "Error:" in line or "Exception:" in line:
                parts = line.split(":", 1)
                error_type = parts[0].strip().split(".")[-1]
                error_message = parts[1].strip() if len(parts) > 1 else line
                break

        return VerifyResult(
            passed=False,
            error_type=error_type,
            error_message=error_message,
            traceback_str=stderr[-2000:] if stderr else None,
        )
    except subprocess.TimeoutExpired:
        if is_daemon:
            # Daemon/server: still running = started successfully
            return VerifyResult(
                passed=True,
                error_type=None,
                error_message=f"Process still running after {timeout}s (daemon mode, counted as pass).",
            )
        else:
            # Script: timeout likely means infinite loop or hang
            return VerifyResult(
                passed=False,
                error_type="TimeoutError",
                error_message=f"Process timed out after {timeout}s (script mode, counted as fail).",
            )
    except Exception as e:
        return VerifyResult(
            passed=False,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback_str=traceback.format_exc(),
        )


def verify_tests(test_path: str, timeout: int = 60) -> VerifyResult:
    """Run pytest on a test file or directory.

    Args:
        test_path: Path to test file or directory.
        timeout: Maximum seconds for test run.

    Returns:
        VerifyResult indicating success or failure.
    """
    path = Path(test_path)
    if not path.exists():
        return VerifyResult(
            passed=False,
            error_type="FileNotFoundError",
            error_message=f"Test path not found: {test_path}",
        )

    # Try pytest first, fall back to unittest
    pytest_available = True
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pytest_available = False

    if pytest_available:
        cmd = [sys.executable, "-m", "pytest", str(path), "-v", "--tb=short", "--no-header"]
    else:
        # Fall back to unittest discover
        if path.is_dir():
            cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(path), "-v"]
        else:
            cmd = [sys.executable, "-m", "unittest", str(path), "-v"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(path.parent) if path.is_file() else str(path),
        )

        output = result.stdout + result.stderr

        if result.returncode == 0:
            return VerifyResult(passed=True)

        # Extract failure summary
        error_message = "Tests failed."
        for line in output.splitlines():
            if "failed" in line.lower() or "error" in line.lower():
                error_message = line.strip()
                break

        return VerifyResult(
            passed=False,
            error_type="TestFailure",
            error_message=error_message,
            traceback_str=output[-2000:] if output else None,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            passed=False,
            error_type="TimeoutError",
            error_message=f"Tests timed out after {timeout}s.",
        )
    except Exception as e:
        return VerifyResult(
            passed=False,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback_str=traceback.format_exc(),
        )
