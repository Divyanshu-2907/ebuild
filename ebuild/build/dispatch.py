# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Build backend dispatcher for ebuild.

Auto-detects and dispatches to external build systems:
CMake, Make, Meson, Cargo, Kbuild.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

TIER_1 = {"make", "kbuild"}

TIER_2 = {"cmake", "meson"}

TIER_3 = {"cargo"}

ALL_BACKENDS = {"cmake", "make", "meson", "cargo", "kbuild", "ninja"}
SUPPORTED_BACKENDS = TIER_1 | TIER_2 | TIER_3


class BackendError(RuntimeError):
    """Raised when the external dispatcher cannot handle a backend."""


def _validate_backend(backend: str, supported: Set[str]) -> None:
    """Reject values that the requested dispatcher operation cannot handle."""
    if backend in supported:
        return

    if backend in ALL_BACKENDS:
        message = f"BackendDispatcher cannot handle backend '{backend}'."
    else:
        message = f"Unknown build backend '{backend}'."

    supported_names = ", ".join(sorted(supported))
    raise BackendError(f"{message} Supported backends: {supported_names}.")

#: Backends this dispatcher actually drives. "ninja" is ebuild's own backend --
#: the CLI invokes NinjaBackend directly and never routes it through here.
DISPATCHED_BACKENDS = {"cmake", "make", "meson", "cargo", "kbuild"}


class UnknownBackendError(ValueError, RuntimeError):
    """Raised when a backend reaches the dispatcher that it cannot drive.

    Subclasses both ValueError and RuntimeError: callers treat an unrecognized
    backend name as a bad argument, while the CLI treats a backend it failed to
    route (notably "ninja") as a routing failure. Silently doing nothing here is
    what made `ebuild build` report "Build completed successfully" without ever
    running a compiler.
    """


def _unknown_backend(backend: str, step: str) -> UnknownBackendError:
    return UnknownBackendError(
        f"Unknown build backend '{backend}'. "
        f"Supported backends: {', '.join(sorted(DISPATCHED_BACKENDS))}. "
        "ebuild's own 'ninja' backend is invoked directly by the CLI and is "
        f"not dispatched here, so it cannot be {step} through BackendDispatcher."
    )


def ninja_command():
    """Return the argv prefix that runs ninja on this machine.

    Prefer a `ninja` executable on PATH -- that is what a developer who
    followed any ordinary install guide has, and what CMake and Meson already
    use. Fall back to the `ninja` PyPI wheel only when no binary is present.

    ebuild used to invoke `sys.executable -m ninja` unconditionally, so a
    machine with ninja correctly installed still failed with "No module named
    ninja" on the first build of a new project.
    """
    import shutil

    exe = shutil.which("ninja")
    return [exe] if exe else [sys.executable, "-m", "ninja"]


def detect_backend(source_dir: Path) -> str:
    """Auto-detect the build system from project files.

    Returns:
        One of: cmake, make, meson, cargo, kbuild, ninja
    """
    if (source_dir / "CMakeLists.txt").exists():
        return "cmake"
    if (source_dir / "meson.build").exists():
        return "meson"
    if (source_dir / "Cargo.toml").exists():
        return "cargo"
    if (source_dir / "Kconfig").exists() or (source_dir / "Kbuild").exists():
        return "kbuild"
    if (source_dir / "Makefile").exists() or (source_dir / "makefile").exists():
        return "make"
    return "ninja"


def _run_or_log(
    cmd: List[str],
    dry_run: bool,
    *,
    check: bool = True,
    cwd: Optional[str] = None,
) -> Optional[subprocess.CompletedProcess]:
    """Run a command or log it in dry-run mode.

    Args:
        cmd: Command and arguments to execute.
        dry_run: If True, log the command instead of executing it.
        check: If True, raise on non-zero exit (passed to subprocess.run).
        cwd: Working directory for the command.

    Returns:
        The CompletedProcess result, or None in dry-run mode.
    """
    if dry_run:
        cmd_str = " ".join(cmd)
        if cwd:
            logger.info("[dry-run] cd %s && %s", cwd, cmd_str)
        else:
            logger.info("[dry-run] %s", cmd_str)
        return None
    return subprocess.run(cmd, check=check, cwd=cwd)


class BackendDispatcher:
    """Dispatch configure/build/clean to external build systems.

    Args:
        source_dir: Project source directory.
        build_dir: Build output directory.
    """

    def __init__(self, source_dir: Path, build_dir: Path) -> None:
        self.source_dir = source_dir
        self.build_dir = build_dir

    def configure(
        self,
        backend: str,
        config: Optional[Dict[str, Any]] = None,
        *,
        dry_run: bool = False,
    ) -> None:
        """Run the configure step for the given backend.

        Args:
            backend: Build backend name (cmake, meson, cargo, etc.).
            config: Optional backend-specific configuration dict.
            dry_run: If True, log commands instead of executing them.

        Raises:
            BackendError: If the backend cannot be configured here.
        """
        _validate_backend(backend, SUPPORTED_BACKENDS)
        config = config or {}
        self.build_dir.mkdir(parents=True, exist_ok=True)

        if backend == "cmake":
            cmd = ["cmake", "-B", str(self.build_dir), "-S", str(self.source_dir)]
            generator = config.get("generator")
            if generator:
                cmd.extend(["-G", generator])
            for key, val in config.get("defines", {}).items():
                cmd.append(f"-D{key}={val}")
            _run_or_log(cmd, dry_run)

        elif backend == "meson":
            cmd = ["meson", "setup", str(self.build_dir), str(self.source_dir)]
            _run_or_log(cmd, dry_run)

        elif backend == "cargo":
            pass  # Cargo does not have a separate configure step

        elif backend in ("make", "kbuild"):
            pass  # No separate configure step

    def build(
        self,
        backend: str,
        config: Optional[Dict[str, Any]] = None,
        *,
        dry_run: bool = False,
    ) -> None:
        """Run the build step for the given backend.

        Args:
            backend: Build backend name (cmake, make, meson, cargo, kbuild).
            config: Optional backend-specific configuration dict.
            dry_run: If True, log commands instead of executing them.

        Raises:
            BackendError: If the backend cannot be built here.
        """
        _validate_backend(backend, SUPPORTED_BACKENDS)
        config = config or {}

        if backend == "cmake":
            cmd = ["cmake", "--build", str(self.build_dir)]
            jobs = config.get("jobs")
            if jobs:
                cmd.extend(["-j", str(jobs)])
            _run_or_log(cmd, dry_run)

        elif backend == "make":
            make_cmd = "nmake" if sys.platform == "win32" else "make"
            cmd = [make_cmd, "-C", str(self.source_dir)]
            _run_or_log(cmd, dry_run)

        elif backend == "meson":
            cmd = ["meson", "compile", "-C", str(self.build_dir)]
            _run_or_log(cmd, dry_run)

        elif backend == "cargo":
            cmd = ["cargo", "build"]
            if config.get("release"):
                cmd.append("--release")
            _run_or_log(cmd, dry_run, cwd=str(self.source_dir))

        elif backend == "kbuild":
            cmd = ["make", "-C", str(self.source_dir)]
            _run_or_log(cmd, dry_run)

    def clean(
        self,
        backend: str,
        *,
        dry_run: bool = False,
    ) -> None:
        """Run the clean step for the given backend.

        Args:
            backend: Build backend name.
            dry_run: If True, log commands instead of executing them.

        Raises:
            BackendError: If the backend cannot be cleaned here.
        """
        _validate_backend(backend, ALL_BACKENDS)
        if backend == "cmake":
            _run_or_log(
                ["cmake", "--build", str(self.build_dir), "--target", "clean"],
                dry_run,
                check=False,
            )
        elif backend in ("make", "kbuild"):
            _run_or_log(
                ["make", "-C", str(self.source_dir), "clean"],
                dry_run,
                check=False,
            )
        elif backend == "meson":
            _run_or_log(
                ["meson", "compile", "-C", str(self.build_dir), "--clean"],
                dry_run,
                check=False,
            )
        elif backend == "cargo":
            _run_or_log(
                ["cargo", "clean"],
                dry_run,
                check=False,
                cwd=str(self.source_dir),
            )
        elif backend == "ninja":
            _run_or_log(
                ninja_command() + ["-C", str(self.build_dir), "-t", "clean"],
                dry_run,
                check=False,
            )
