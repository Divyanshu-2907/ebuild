# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""CLI tests for backend resolution and configure behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from ebuild.cli import commands


pytestmark = pytest.mark.needs_yaml


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_config(path: Path, *extra_lines: str) -> None:
    lines = [
        "project:",
        "  name: demo",
        '  version: "1.0.0"',
    ]
    lines.extend(extra_lines)
    _write_file(path, "\n".join(lines) + "\n")


def _invoke_configure(config_path: Path, *extra_args: str):
    runner = CliRunner()
    return runner.invoke(
        commands.cli,
        ["configure", "--config", str(config_path), *extra_args],
    )


def _patch_ninja_generation(monkeypatch):
    generate_calls = {}

    def fake_resolve_toolchain(toolchain):
        return SimpleNamespace(cc="gcc", cxx="g++", ar="ar")

    def fake_generate(self):
        generate_calls["build_dir"] = self.build_dir
        self.build_dir.mkdir(parents=True, exist_ok=True)
        (self.build_dir / "build.ninja").write_text("# generated\n", encoding="utf-8")
        (self.build_dir / "compile_commands.json").write_text("[]\n", encoding="utf-8")

    monkeypatch.setattr(commands, "resolve_toolchain", fake_resolve_toolchain)
    monkeypatch.setattr(commands, "_install_packages", lambda *args, **kwargs: {})
    monkeypatch.setattr(commands.NinjaBackend, "generate", fake_generate)
    return generate_calls


def test_configure_uses_explicit_cmake_backend_and_passes_config(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(
        config_path,
        "backend: cargo",
        "cmake:",
        "  generator: Ninja",
        "  defines:",
        "    FOO: BAR",
    )

    calls = []

    def fake_configure(self, backend, config=None):
        calls.append((backend, config or {}))

    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fake_configure)

    result = _invoke_configure(config_path, "--backend", "cmake")

    assert result.exit_code == 0
    assert calls == [("cmake", {"generator": "Ninja", "defines": {"FOO": "BAR"}})]
    assert "Using cmake backend..." in result.output


def test_configure_auto_detects_cmake_backend(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(config_path)
    _write_file(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.16)\n")

    calls = []

    def fake_configure(self, backend, config=None):
        calls.append((backend, config or {}))

    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fake_configure)

    result = _invoke_configure(config_path)

    assert result.exit_code == 0
    assert calls == [("cmake", {})]
    assert "Auto-detected backend: cmake" in result.output


def test_configure_uses_explicit_meson_backend(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(config_path)

    calls = []

    def fake_configure(self, backend, config=None):
        calls.append((backend, config or {}))

    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fake_configure)

    result = _invoke_configure(config_path, "--backend", "meson")

    assert result.exit_code == 0
    assert calls == [("meson", {})]
    assert "Using meson backend..." in result.output


def test_configure_auto_detects_meson_backend(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(config_path)
    _write_file(tmp_path / "meson.build", "project('demo', 'c')\n")

    calls = []

    def fake_configure(self, backend, config=None):
        calls.append((backend, config or {}))

    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fake_configure)

    result = _invoke_configure(config_path)

    assert result.exit_code == 0
    assert calls == [("meson", {})]
    assert "Auto-detected backend: meson" in result.output


def test_configure_generates_ninja_for_explicit_ninja_backend(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(
        config_path,
        "backend: ninja",
        "targets:",
        "  - name: demo",
        "    type: executable",
        '    sources: ["main.c"]',
    )

    generate_calls = _patch_ninja_generation(monkeypatch)

    result = _invoke_configure(config_path)

    assert result.exit_code == 0
    # A relative --build-dir is anchored to the project, not the process cwd.
    assert generate_calls["build_dir"] == tmp_path / "_build"
    assert "Generated" in result.output


def test_configure_auto_detects_ninja_when_no_backend_markers_exist(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(
        config_path,
        "targets:",
        "  - name: demo",
        "    type: executable",
        '    sources: ["main.c"]',
    )

    generate_calls = _patch_ninja_generation(monkeypatch)

    result = _invoke_configure(config_path)

    assert result.exit_code == 0
    # A relative --build-dir is anchored to the project, not the process cwd.
    assert generate_calls["build_dir"] == tmp_path / "_build"
    assert "Auto-detected backend: ninja" in result.output


@pytest.mark.parametrize(
    ("backend", "marker_file", "marker_content"),
    [
        ("cargo", "Cargo.toml", "[package]\nname = 'demo'\nversion = '0.1.0'\n"),
        ("make", "Makefile", "all:\n\t@echo demo\n"),
        ("kbuild", "Kconfig", "config DEMO\n\tbool \"demo\"\n"),
    ],
)
def test_configure_reports_noop_for_auto_detected_no_configure_backends(
    tmp_path,
    monkeypatch,
    backend,
    marker_file,
    marker_content,
):
    config_path = tmp_path / "build.yaml"
    _write_config(config_path)
    _write_file(tmp_path / marker_file, marker_content)

    def fail_generate(self):
        raise AssertionError("Ninja backend should not run for no-configure backends")

    def fail_configure(self, backend_name, config=None):
        raise AssertionError("Dispatcher configure should not run for no-configure backends")

    monkeypatch.setattr(commands.NinjaBackend, "generate", fail_generate)
    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fail_configure)

    result = _invoke_configure(config_path)

    assert result.exit_code == 0
    assert f"Auto-detected backend: {backend}" in result.output
    assert f"No separate configure step for {backend}." in result.output


@pytest.mark.parametrize("backend", ["cargo", "make", "kbuild"])
def test_configure_reports_noop_for_explicit_no_configure_backends(tmp_path, monkeypatch, backend):
    config_path = tmp_path / "build.yaml"
    _write_config(config_path, f"backend: {backend}")

    def fail_generate(self):
        raise AssertionError("Ninja backend should not run for no-configure backends")

    def fail_configure(self, backend_name, config=None):
        raise AssertionError("Dispatcher configure should not run for no-configure backends")

    monkeypatch.setattr(commands.NinjaBackend, "generate", fail_generate)
    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fail_configure)

    result = _invoke_configure(config_path)

    assert result.exit_code == 0
    assert f"No separate configure step for {backend}." in result.output


def test_cli_override_beats_configured_backend(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(config_path, "backend: cargo")

    calls = []

    def fake_configure(self, backend, config=None):
        calls.append((backend, config or {}))

    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fake_configure)

    result = _invoke_configure(config_path, "--backend", "meson")

    assert result.exit_code == 0
    assert calls == [("meson", {})]
    assert "Using meson backend..." in result.output


def test_configure_fails_for_invalid_project_config(tmp_path):
    config_path = tmp_path / "build.yaml"
    _write_file(config_path, 'project:\n  version: "1.0.0"\n')

    result = _invoke_configure(config_path)

    assert result.exit_code == 1
    assert "Configuration error" in result.output


def test_configure_fails_cleanly_for_invalid_yaml(tmp_path):
    config_path = tmp_path / "build.yaml"
    _write_file(
        config_path,
        "\n".join(
            [
                "project:",
                "  name: demo",
                '  version: "1.0.0"',
                "targets:",
                "  - name: demo",
                "    type: executable",
                '    sources: ["main.c"',
            ]
        )
        + "\n",
    )

    result = _invoke_configure(config_path)

    assert result.exit_code == 1
    assert "Configuration error" in result.output
    assert "Invalid YAML" in result.output
    assert "line " in result.output
    assert "column " in result.output


def test_configure_fails_for_invalid_ninja_target_schema(tmp_path):
    config_path = tmp_path / "build.yaml"
    _write_config(
        config_path,
        "backend: ninja",
        "targets:",
        "  - name: demo",
        "    type: executable",
    )

    result = _invoke_configure(config_path)

    assert result.exit_code == 1
    assert "Configuration error" in result.output


def test_configure_reports_external_backend_command_failure(tmp_path, monkeypatch):
    config_path = tmp_path / "build.yaml"
    _write_config(config_path, "backend: cmake")

    def fake_configure(self, backend, config=None):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["cmake", "-B", "_build", "-S", str(tmp_path)],
        )

    monkeypatch.setattr("ebuild.build.dispatch.BackendDispatcher.configure", fake_configure)

    result = _invoke_configure(config_path)

    assert result.exit_code == 1
    assert "Command failed (exit code 1)" in result.output
    assert "cmake -B _build" in result.output
