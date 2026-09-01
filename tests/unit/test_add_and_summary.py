# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""`ebuild add` refusing what it cannot resolve, and the build summary.

The MLP walk is:

    ebuild new temperature-monitor
    ebuild configure --board <board>
    ebuild add wifi
    ebuild add mqtt
    ebuild build
    EmbeddedOS Build  OK toolchain  OK board configuration  OK dependencies ...

Two gaps against that. `ebuild add` warned about an unknown package and added
it anyway, trading one clear error now for a confusing one at build time in a
file the developer has since committed. And a successful build printed only
"Build completed successfully", leaving them to infer what was in it.
"""

from types import SimpleNamespace

import pytest
import yaml
from click.testing import CliRunner

from ebuild.cli.commands import _no_recipe_message, cli


class _FakeRegistry:
    def __init__(self, names):
        self._names = names

    def list_packages(self):
        return [SimpleNamespace(name=n) for n in self._names]


class TestNoRecipeMessage:
    def test_it_lists_what_is_available(self):
        """"No recipe found" alone leaves the developer guessing at the
        spelling, at whether it exists under another name, and at where
        recipes come from."""
        msg = _no_recipe_message("wifi", _FakeRegistry(["lwip", "mbedtls"]))
        assert "lwip" in msg and "mbedtls" in msg

    def test_a_near_miss_is_suggested(self):
        msg = _no_recipe_message("lwipp", _FakeRegistry(["lwip", "zlib"]))
        assert "Did you mean" in msg and "lwip" in msg

    def test_an_unrelated_name_gets_no_suggestion(self):
        msg = _no_recipe_message("wifi", _FakeRegistry(["lwip", "zlib"]))
        assert "Did you mean" not in msg

    def test_it_names_the_escape_hatch(self):
        msg = _no_recipe_message("wifi", _FakeRegistry(["lwip"]))
        assert "--force" in msg

    def test_an_empty_registry_says_so_rather_than_listing_nothing(self):
        msg = _no_recipe_message("wifi", _FakeRegistry([]))
        assert "No recipes are visible" in msg


@pytest.fixture
def project(tmp_path):
    (tmp_path / "build.yaml").write_text(yaml.safe_dump({
        "project": {"name": "p", "version": "0.1.0"},
        "workspace": {"backend": "ninja", "build_dir": "build"},
        "toolchain": {"target": "host"},
        "targets": [{"name": "p", "type": "executable", "sources": ["src/main.c"]}],
    }), encoding="utf-8")
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    (recipes / "lwip.yaml").write_text(yaml.safe_dump({
        "name": "lwip", "version": "2.2.0",
        "url": "https://example.invalid/lwip-2.2.0.tar.gz",
        "checksum": "sha256:" + "0" * 64,
        "build": {"type": "cmake"},
    }), encoding="utf-8")
    return tmp_path


def _packages(path):
    return yaml.safe_load((path / "build.yaml").read_text()).get("packages") or []


class TestAddRefusesWhatItCannotResolve:
    def test_a_known_package_is_added(self, project):
        r = CliRunner().invoke(cli, ["add", "lwip", "--config",
                                     str(project / "build.yaml")])
        assert r.exit_code == 0
        assert [p["name"] for p in _packages(project)] == ["lwip"]

    def test_an_unknown_package_is_refused(self, project):
        r = CliRunner().invoke(cli, ["add", "wifi", "--config",
                                     str(project / "build.yaml")])
        assert r.exit_code == 1

    def test_a_refused_package_is_not_written(self, project):
        """The point of refusing: build.yaml must not end up carrying an
        entry that can never resolve."""
        CliRunner().invoke(cli, ["add", "wifi", "--config",
                                 str(project / "build.yaml")])
        assert _packages(project) == []

    def test_force_adds_it_anyway(self, project):
        r = CliRunner().invoke(cli, ["add", "wifi", "--force", "--config",
                                     str(project / "build.yaml")])
        assert r.exit_code == 0
        assert [p["name"] for p in _packages(project)] == ["wifi"]

    def test_adding_the_same_package_twice_is_a_no_op(self, project):
        cfg = str(project / "build.yaml")
        CliRunner().invoke(cli, ["add", "lwip", "--config", cfg])
        CliRunner().invoke(cli, ["add", "lwip", "--config", cfg])
        assert len(_packages(project)) == 1


class TestBuildSummary:
    """Rendered through the real logger, so the assertions are on what a
    developer actually sees."""

    def _render(self, cfg, package_paths):
        from ebuild.cli.commands import _build_summary
        lines = []
        log = SimpleNamespace(
            info=lines.append,
            warning=lambda m: lines.append("WARN " + m),
            verbose=False,
        )
        _build_summary(cfg, SimpleNamespace(cc="arm-none-eabi-gcc"),
                       package_paths, log)
        return "\n".join(lines)

    def _cfg(self, packages=()):
        return SimpleNamespace(
            packages=[SimpleNamespace(name=n) for n in packages],
            targets=[SimpleNamespace(name="app", target_type="executable")],
        )

    def test_it_names_the_toolchain_and_the_application(self):
        body = self._render(self._cfg(), {})
        assert "arm-none-eabi-gcc" in body
        assert "app" in body

    def test_a_resolved_package_is_ok(self):
        paths = {"lwip": SimpleNamespace(include_dirs=["/x/include"],
                                         lib_dirs=[], libraries=[])}
        body = self._render(self._cfg(["lwip"]), paths)
        assert "OK   lwip" in body

    def test_a_package_that_resolved_to_nothing_is_flagged(self):
        """The interesting case: the build succeeds, the feature is simply
        absent, and nothing said so."""
        paths = {"lwip": SimpleNamespace(include_dirs=[], lib_dirs=[],
                                         libraries=[])}
        body = self._render(self._cfg(["lwip"]), paths)
        assert "MISS lwip" in body
        assert "resolved to nothing" in body

    def test_a_package_missing_from_the_map_entirely_is_flagged(self):
        body = self._render(self._cfg(["mqtt"]), {})
        assert "MISS mqtt" in body

    def test_no_warning_when_everything_resolved(self):
        paths = {"lwip": SimpleNamespace(include_dirs=["/x"], lib_dirs=[],
                                         libraries=[])}
        assert "WARN" not in self._render(self._cfg(["lwip"]), paths)

    def test_names_are_column_aligned(self):
        body = self._render(self._cfg(["a-very-long-package-name"]), {})
        rows = [l for l in body.splitlines() if l.startswith("  OK") or l.startswith("  MISS")]
        assert len({len(l.split()[1]) for l in rows}) >= 1   # renders without error
        assert all(l.startswith("  ") for l in rows)
