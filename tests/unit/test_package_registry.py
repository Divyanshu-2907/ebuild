# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Unit tests for package version ordering in the registry.

The registry picks the "latest" version of a package by sorting version
strings. These tests cover the version strings that occur upstream but are not
purely numeric, which previously raised ValueError.
"""

from types import SimpleNamespace

import pytest

from ebuild.packages.registry import PackageRegistry, version_sort_key


def _recipe(name: str, version: str):
    """Minimal stand-in for a PackageRecipe — the registry indexes on these two."""
    return SimpleNamespace(name=name, version=version)


def _registry_with(name: str, *versions: str) -> PackageRegistry:
    registry = PackageRegistry()
    for version in versions:
        registry._register(_recipe(name, version))
    return registry


class TestVersionKey:
    def test_numeric_versions_compare_numerically(self):
        """Plain string ordering would put 11.1.0 below 2.9.3."""
        versions = ["2.9.3", "11.1.0", "1.3.1"]
        assert sorted(versions, key=version_sort_key) == ["1.3.1", "2.9.3", "11.1.0"]

    @pytest.mark.parametrize(
        "version",
        ["3.6.0-rc1", "1.2.11b", "2.9.3p1", "2024.01", "1.0.0-alpha.2"],
        ids=["release-candidate", "letter-suffix", "patch-suffix", "date", "alpha"],
    )
    def test_non_numeric_versions_do_not_raise(self, version):
        """Any of these previously raised ValueError from int()."""
        assert version_sort_key(version)

    def test_pre_release_sorts_below_its_release(self):
        """Semver precedence: 3.6.0-rc1 comes before 3.6.0."""
        assert version_sort_key("3.6.0-rc1") < version_sort_key("3.6.0")

    def test_letter_suffix_sorts_above_its_base(self):
        """A patch respin such as 1.2.11b supersedes 1.2.11."""
        assert version_sort_key("1.2.11") < version_sort_key("1.2.11b")

    def test_successive_respins_order_among_themselves(self):
        """1.2.11b supersedes 1.2.11a, and both supersede 1.2.11."""
        assert version_sort_key("1.2.11a") < version_sort_key("1.2.11b")
        assert version_sort_key("1.2.11") < version_sort_key("1.2.11a")

    def test_respin_still_ranks_above_a_textual_component(self):
        """A respin keeps its numeric rank, so it beats a non-numeric one."""
        assert version_sort_key("1.2.beta") < version_sort_key("1.2.11b")

    def test_shorter_version_sorts_below_longer(self):
        assert version_sort_key("1.2") < version_sort_key("1.2.1")


class TestRegistryVersionSelection:
    def test_get_latest_with_a_release_candidate_present(self):
        """Regression: this raised ValueError: invalid literal for int()."""
        registry = _registry_with("mbedtls", "3.6.0", "3.6.0-rc1")
        assert registry.get("mbedtls").version == "3.6.0"

    def test_get_latest_compares_numerically(self):
        registry = _registry_with("freertos", "2.9.3", "11.1.0")
        assert registry.get("freertos").version == "11.1.0"

    def test_get_explicit_version_still_works(self):
        registry = _registry_with("mbedtls", "3.6.0", "3.6.0-rc1")
        assert registry.get("mbedtls", "3.6.0-rc1").version == "3.6.0-rc1"

    def test_list_packages_with_a_release_candidate_present(self):
        """Regression: `ebuild list-packages` exited with a traceback."""
        registry = _registry_with("mbedtls", "3.6.0", "3.6.0-rc1")
        assert [r.version for r in registry.list_packages()] == ["3.6.0"]

    def test_list_all_versions_is_ordered_oldest_first(self):
        registry = _registry_with("zlib", "11.1.0", "2.9.3", "3.6.0-rc1", "3.6.0")
        assert [r.version for r in registry.list_all_versions("zlib")] == [
            "2.9.3",
            "3.6.0-rc1",
            "3.6.0",
            "11.1.0",
        ]

    def test_unknown_package_returns_none(self):
        assert PackageRegistry().get("nonexistent") is None
