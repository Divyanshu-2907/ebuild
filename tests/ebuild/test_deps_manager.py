# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Host tests for DepsManager sibling path resolution."""

from pathlib import Path

import pytest

from ebuild.deps.manager import DepsManager, SIBLING_DIR_NAMES


@pytest.fixture
def isolated_deps(tmp_path, monkeypatch):
    """Keep get_repo_path off the real ~/.ebuild cache and config."""
    home = tmp_path / "ebuild-home"
    repos = home / "repos"
    config = home / "config.yaml"
    monkeypatch.setattr("ebuild.deps.manager.ensure_ebuild_home", lambda: home)
    monkeypatch.setattr("ebuild.deps.manager.EBUILD_CONFIG_PATH", config)
    monkeypatch.setenv("EBUILD_REPOS_DIR", str(repos))
    monkeypatch.delenv("EBUILD_EOS_PATH", raising=False)
    monkeypatch.delenv("EBUILD_EBOOT_PATH", raising=False)
    home.mkdir()
    repos.mkdir()
    return tmp_path


def _case_sensitive_is_dir(self: Path) -> bool:
    """Treat directory names as case-sensitive, as Linux does."""
    try:
        names = {child.name for child in self.parent.iterdir()}
    except OSError:
        return False
    return self.name in names


def test_eboot_aliases_include_github_casing():
    assert SIBLING_DIR_NAMES["eboot"] == ("eboot", "eBoot")


def test_sibling_eboot_resolves_camel_case(isolated_deps, monkeypatch):
    workspace = isolated_deps / "ws"
    project = workspace / "ebuild"
    camel = workspace / "eBoot"
    project.mkdir(parents=True)
    camel.mkdir()
    monkeypatch.setattr(Path, "is_dir", _case_sensitive_is_dir)

    resolved = DepsManager().get_repo_path("eboot", project_dir=project)

    assert resolved is not None
    assert resolved.name == "eBoot"


def test_sibling_eboot_still_resolves_lowercase(isolated_deps, monkeypatch):
    workspace = isolated_deps / "ws"
    project = workspace / "ebuild"
    lower = workspace / "eboot"
    project.mkdir(parents=True)
    lower.mkdir()
    monkeypatch.setattr(Path, "is_dir", _case_sensitive_is_dir)

    resolved = DepsManager().get_repo_path("eboot", project_dir=project)

    assert resolved is not None
    assert resolved.name == "eboot"


def test_sibling_eboot_missing_returns_none(isolated_deps, monkeypatch):
    workspace = isolated_deps / "ws"
    project = workspace / "ebuild"
    project.mkdir(parents=True)
    monkeypatch.setattr(Path, "is_dir", _case_sensitive_is_dir)

    resolved = DepsManager().get_repo_path("eboot", project_dir=project)

    assert resolved is None
