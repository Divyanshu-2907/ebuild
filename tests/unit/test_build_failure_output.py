# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Regression tests for diagnostics reporting when the Ninja backend fails.

ninja writes the output of the commands it runs -- compiler diagnostics -- to
stdout, and reserves stderr for its own messages. `ebuild build` captures both
streams, so a failure handler that replays only stderr leaves the user with
"Build failed." and no indication of what went wrong.

These tests drive the failure path with a stubbed subprocess so they need no
compiler and no ninja binary.
"""

import subprocess
import textwrap

import pytest
from click.testing import CliRunner

from ebuild.cli.commands import cli

COMPILER_ERROR = "src/main.c:3:24: error: expected declaration specifiers before '(' token"
NINJA_NOTE = "ninja: build stopped: subcommand failed."


def _all_output(result):
    """Every stream the runner captured, as one string.

    Click moved stderr out of ``Result.output`` in 8.2, and this project only
    pins ``click>=8.0``, so read both and tolerate either layout.
    """
    text = result.output or ""
    try:
        if result.stderr:
            text += result.stderr
    except ValueError:
        # Older Click raises when stderr was not captured separately.
        pass
    return text


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A minimal single-target project that reaches the Ninja backend."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "build.yaml").write_text(textwrap.dedent("""\
        project:
          name: demo
          version: "1.0.0"

        targets:
          - name: demo
            type: executable
            sources: ["src/main.c"]

        toolchain:
          compiler: gcc
          arch: x86_64
        """))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def failing_ninja(monkeypatch):
    """Make the ninja invocation fail the way a real compile error does."""
    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            returncode=1,
            stdout=f"[1/2] CC demo.o\nFAILED: demo.o\n{COMPILER_ERROR}\n{NINJA_NOTE}\n".encode(),
            stderr=b"",
        )

    monkeypatch.setattr("ebuild.cli.commands.subprocess.run", fake_run)


@pytest.mark.ebuild
class TestBuildFailureOutput:
    """`ebuild build` must show why the build failed."""

    def test_compiler_diagnostics_from_stdout_are_reported(self, project, failing_ninja):
        """The compiler error reaches the user even though ninja sent it to stdout."""
        result = CliRunner().invoke(cli, ["build"], catch_exceptions=False)

        assert result.exit_code == 1
        output = _all_output(result)
        assert COMPILER_ERROR in output, (
            "compiler diagnostics were dropped; the user only sees 'Build failed.'"
        )
        assert NINJA_NOTE in output

    def test_stderr_is_still_reported(self, project, monkeypatch):
        """Diagnostics that do arrive on stderr are not lost by the stdout fix."""
        def fake_run(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout=b"", stderr=b"ninja: fatal: pipe failed\n"
            )

        monkeypatch.setattr("ebuild.cli.commands.subprocess.run", fake_run)
        result = CliRunner().invoke(cli, ["build"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "ninja: fatal: pipe failed" in _all_output(result)
