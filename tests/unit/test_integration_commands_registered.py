# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""The documented integration commands must exist on the installed CLI.

`integration`, `qemu`, `sdk`, `package` and `models` are defined in
ebuild/cli/integration.py and attached to the group by register_commands().
That call used to live only in ebuild/__main__.py, so the five commands
existed under `python -m ebuild` and were absent from the `ebuild` console
script that pyproject.toml installs on PATH -- the invocation the README,
docs/architecture.md, docs/qms/quality_management_system.md and
examples/eradar360/eos.yaml all use.

These tests assert against the `cli` object named by [project.scripts], which
is the thing the entry point actually runs, so the gap cannot come back.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from ebuild.cli.commands import cli


# Defined in ebuild/cli/integration.py and referenced by the docs.
INTEGRATION_COMMANDS = ["integration", "qemu", "sdk", "package", "models"]


@pytest.mark.ebuild
class TestIntegrationCommandsRegistered:
    """Every integration command must be on the console-script group."""

    @pytest.mark.parametrize("name", INTEGRATION_COMMANDS)
    def test_command_is_registered(self, name):
        assert name in cli.commands, (
            f"'ebuild {name}' is defined in ebuild/cli/integration.py and "
            f"documented, but is not registered on the group that "
            f"[project.scripts] points at"
        )

    @pytest.mark.parametrize("name", INTEGRATION_COMMANDS)
    def test_command_help_runs(self, name):
        result = CliRunner().invoke(cli, [name, "--help"])
        assert result.exit_code == 0, result.output

    def test_entry_point_and_module_expose_the_same_commands(self):
        """`ebuild <cmd>` and `python -m ebuild <cmd>` must not diverge.

        __main__.py imports the same group object, so this asserts that
        importing it adds nothing the console script does not already have.
        """
        console_script_commands = set(cli.commands)

        import ebuild.__main__ as module_entry_point

        assert set(module_entry_point.cli.commands) == console_script_commands

    def test_documented_commands_are_reachable(self):
        """`ebuild --help` must list the commands the docs tell users to run."""
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0, result.output
        for name in INTEGRATION_COMMANDS:
            assert name in result.output, (
                f"'{name}' is missing from `ebuild --help`"
            )


@pytest.mark.ebuild
def test_entry_point_target_is_the_registered_group():
    """[project.scripts] must keep pointing at the group under test.

    If the entry point is ever re-pointed somewhere else, these tests would
    keep passing while the installed `ebuild` command lost the commands
    again. Pin the target so that change is caught here.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    assert 'ebuild = "ebuild.cli.commands:cli"' in content, (
        "the console script no longer points at ebuild.cli.commands:cli, so "
        "these tests no longer cover the installed command"
    )
