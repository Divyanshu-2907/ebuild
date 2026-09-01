# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Backend auto-detection must not outrank targets declared in build.yaml.

``detect_backend()`` sees only the filesystem. A Makefile kept for `make
flash`, or a CMakeLists.txt belonging to one subcomponent, therefore used to
win over a build.yaml that declared its own targets: the dispatcher ran the
external tool, none of the declared targets were built, and `ebuild build`
still printed "Build completed successfully" and exited 0.

An explicit backend -- `backend:` in build.yaml, or --backend -- is still
honoured, so a project can keep both a target list and an external build.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from ebuild.cli import commands


pytestmark = pytest.mark.needs_yaml

# Every marker file detect_backend() recognises, with the backend it yields.
MARKERS = [
    ("cmake", "CMakeLists.txt", "cmake_minimum_required(VERSION 3.16)\n"),
    ("meson", "meson.build", "project('demo', 'c')\n"),
    ("cargo", "Cargo.toml", "[package]\nname = 'demo'\nversion = '0.1.0'\n"),
    ("make", "Makefile", "all:\n\t@echo flash-helper\n"),
    ("kbuild", "Kconfig", 'config DEMO\n\tbool "demo"\n'),
]

_CONFIG_WITH_TARGETS = "\n".join(
    [
        "project:",
        "  name: demo",
        '  version: "1.0.0"',
        "targets:",
        "  - name: demo",
        "    type: executable",
        '    sources: ["main.c"]',
    ]
) + "\n"


def _project(tmp_path: Path, marker_file: str, marker_content: str,
             *, extra_config_lines: str = "") -> Path:
    config_path = tmp_path / "build.yaml"
    config_path.write_text(_CONFIG_WITH_TARGETS + extra_config_lines,
                           encoding="utf-8")
    (tmp_path / "main.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
    (tmp_path / marker_file).write_text(marker_content, encoding="utf-8")
    return config_path


def _patch_ninja(monkeypatch):
    """Record ninja generation; never touch a real toolchain or dispatcher."""
    generated = {}

    def fake_generate(self):
        generated["build_dir"] = self.build_dir
        self.build_dir.mkdir(parents=True, exist_ok=True)
        (self.build_dir / "build.ninja").write_text("# generated\n", encoding="utf-8")
        (self.build_dir / "compile_commands.json").write_text("[]\n", encoding="utf-8")

    def fail_configure(self, backend, config=None):
        raise AssertionError(
            f"dispatcher.configure({backend!r}) ran, but build.yaml declares targets"
        )

    monkeypatch.setattr(commands, "resolve_toolchain",
                        lambda toolchain: SimpleNamespace(cc="gcc", cxx="g++", ar="ar"))
    monkeypatch.setattr(commands, "_install_packages", lambda *a, **k: {})
    monkeypatch.setattr(commands.NinjaBackend, "generate", fake_generate)
    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure",
                        fail_configure)
    return generated


@pytest.mark.parametrize(("backend", "marker_file", "marker_content"), MARKERS)
def test_declared_targets_win_over_auto_detected_backend(
    tmp_path, monkeypatch, backend, marker_file, marker_content
):
    config_path = _project(tmp_path, marker_file, marker_content)
    generated = _patch_ninja(monkeypatch)

    result = CliRunner().invoke(
        commands.cli, ["configure", "--config", str(config_path)]
    )

    assert result.exit_code == 0, result.output
    # The detected backend is still reported, then explicitly overridden.
    assert f"Auto-detected backend: {backend}" in result.output
    assert "declares 1 target(s)" in result.output
    assert f"instead of the detected {backend}" in result.output
    # The decisive assertion: ebuild's own backend actually ran.
    assert "build_dir" in generated
    assert (generated["build_dir"] / "build.ninja").is_file()


@pytest.mark.parametrize(("backend", "marker_file", "marker_content"), MARKERS)
def test_explicit_yaml_backend_still_beats_declared_targets(
    tmp_path, monkeypatch, backend, marker_file, marker_content
):
    """`backend:` in build.yaml is an explicit choice and must be honoured."""
    config_path = _project(tmp_path, marker_file, marker_content,
                           extra_config_lines=f"backend: {backend}\n")

    calls = []
    monkeypatch.setattr(
        "ebuild.build.dispatch.BackendDispatcher.configure",
        lambda self, backend, config=None: calls.append(backend),
    )
    monkeypatch.setattr(
        commands.NinjaBackend, "generate",
        lambda self: (_ for _ in ()).throw(
            AssertionError("ninja ran despite an explicit backend")),
    )

    result = CliRunner().invoke(
        commands.cli, ["configure", "--config", str(config_path)]
    )

    assert result.exit_code == 0, result.output
    assert "Auto-detected" not in result.output
    if backend in ("cargo", "make", "kbuild"):
        assert f"No separate configure step for {backend}." in result.output
        assert calls == []
    else:
        assert calls == [backend]


@pytest.mark.parametrize(("backend", "marker_file", "marker_content"), MARKERS)
def test_cli_backend_flag_still_beats_declared_targets(
    tmp_path, monkeypatch, backend, marker_file, marker_content
):
    """--backend is the operator's explicit choice and must be honoured."""
    config_path = _project(tmp_path, marker_file, marker_content)

    calls = []
    monkeypatch.setattr(
        "ebuild.build.dispatch.BackendDispatcher.configure",
        lambda self, backend, config=None: calls.append(backend),
    )
    monkeypatch.setattr(
        commands.NinjaBackend, "generate",
        lambda self: (_ for _ in ()).throw(
            AssertionError("ninja ran despite --backend")),
    )

    result = CliRunner().invoke(
        commands.cli,
        ["configure", "--config", str(config_path), "--backend", backend],
    )

    assert result.exit_code == 0, result.output
    assert "Auto-detected" not in result.output
    if backend in ("cargo", "make", "kbuild"):
        assert calls == []
    else:
        assert calls == [backend]


@pytest.mark.parametrize(("backend", "marker_file", "marker_content"), MARKERS)
def test_marker_still_wins_when_no_targets_are_declared(
    tmp_path, monkeypatch, backend, marker_file, marker_content
):
    """Without targets there is nothing to protect; detection is unchanged."""
    config_path = tmp_path / "build.yaml"
    config_path.write_text(
        'project:\n  name: demo\n  version: "1.0.0"\n', encoding="utf-8"
    )
    (tmp_path / marker_file).write_text(marker_content, encoding="utf-8")

    calls = []
    monkeypatch.setattr(
        "ebuild.build.dispatch.BackendDispatcher.configure",
        lambda self, backend, config=None: calls.append(backend),
    )
    monkeypatch.setattr(
        commands.NinjaBackend, "generate",
        lambda self: (_ for _ in ()).throw(
            AssertionError("ninja ran for a project with no targets")),
    )

    result = CliRunner().invoke(
        commands.cli, ["configure", "--config", str(config_path)]
    )

    assert result.exit_code == 0, result.output
    assert f"Auto-detected backend: {backend}" in result.output
    assert "declares" not in result.output
    if backend in ("cargo", "make", "kbuild"):
        assert calls == []
    else:
        assert calls == [backend]


# ── `ebuild build`: the end-to-end symptom ──────────────────


@pytest.mark.parametrize(("backend", "marker_file", "marker_content"), MARKERS)
def test_build_does_not_report_success_without_building_targets(
    tmp_path, monkeypatch, backend, marker_file, marker_content
):
    """`ebuild build` used to exit 0 having built none of the declared targets.

    The dispatcher ran the external tool, ebuild's own backend never ran, and
    no build.ninja was generated -- yet the command printed
    "Build completed successfully" and exited 0.
    """
    _project(tmp_path, marker_file, marker_content)
    monkeypatch.chdir(tmp_path)

    generated = _patch_ninja(monkeypatch)

    # Stand in for the real ninja process so no toolchain is needed.
    ninja_invocations = []

    def fake_run(cmd, *args, **kwargs):
        ninja_invocations.append(cmd)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("ebuild.cli.commands.subprocess.run", fake_run)

    result = CliRunner().invoke(commands.cli, ["build"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "Build completed successfully." in result.output
    # Success is only truthful if ebuild's backend actually generated a build.
    assert "build_dir" in generated, (
        f"reported success but the ninja backend never ran ({backend} took over)"
    )
    assert (generated["build_dir"] / "build.ninja").is_file()
    assert ninja_invocations, "reported success without invoking ninja"
