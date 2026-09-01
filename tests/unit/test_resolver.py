# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Tests for :mod:`ebuild.packages.resolver`.

Covers version-constraint handling in particular: an explicitly requested
version must be honoured no matter where in the graph the package is first
reached, and two mutually exclusive requests must fail loudly rather than
silently picking one.

These live in tests/unit/ rather than tests/ebuild/ because the "Run unit
tests" CI step runs tests/unit/; no workflow references tests/ebuild/.
Importing the registry pulls in pyyaml, which is a declared runtime
dependency of the package (pyproject.toml), so it is always available.
"""

import pytest

from ebuild.packages.registry import PackageRegistry
from ebuild.packages.resolver import PackageResolver, ResolveError

pytestmark = pytest.mark.ebuild


def make_registry(tmp_path, recipes):
    """Build a PackageRegistry from ``{filename: recipe-dict}``.

    Versions are written quoted so YAML keeps them as strings ("1.3" would
    otherwise load as a float).
    """
    for filename, fields in recipes.items():
        lines = [
            f"package: {fields['package']}",
            f"version: '{fields['version']}'",
            f"url: https://example.invalid/{fields['package']}.tar.gz",
        ]
        if fields.get("dependencies"):
            lines.append("dependencies: [%s]" % ", ".join(fields["dependencies"]))
        (tmp_path / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")

    registry = PackageRegistry()
    registry.add_search_path(tmp_path)
    registry.scan()
    return registry


@pytest.fixture
def registry(tmp_path):
    """app-1.0.0 depends on zlib; zlib exists at 1.2.13 and 1.3.0."""
    return make_registry(tmp_path, {
        "app.yaml": {"package": "app", "version": "1.0.0", "dependencies": ["zlib"]},
        "zlib-1213.yaml": {"package": "zlib", "version": "1.2.13"},
        "zlib-130.yaml": {"package": "zlib", "version": "1.3.0"},
    })


def versions_of(order):
    return {recipe.name: recipe.version for recipe in order}


# ── Version constraint handling ──────────────────────────────

def test_explicit_version_survives_transitive_resolution(registry):
    """An explicit request must win even when a dependency reached it first.

    Regression: ``_collect`` memoized by name only, so resolving 'app' pulled
    in the newest zlib and the later explicit 1.2.13 request hit the
    ``if name in resolved`` early return and was silently dropped.
    """
    order = PackageResolver(registry).resolve(
        [{"name": "app"}, {"name": "zlib", "version": "1.2.13"}]
    )

    assert versions_of(order)["zlib"] == "1.2.13"


def test_resolution_is_independent_of_request_order(registry):
    """The same request set must resolve identically regardless of ordering."""
    requests = [{"name": "app"}, {"name": "zlib", "version": "1.2.13"}]

    forward = versions_of(PackageResolver(registry).resolve(requests))
    reverse = versions_of(PackageResolver(registry).resolve(list(reversed(requests))))

    assert forward == reverse


def test_conflicting_explicit_versions_raise(registry):
    """Two mutually exclusive explicit versions must fail loudly."""
    resolver = PackageResolver(registry)

    with pytest.raises(ResolveError) as excinfo:
        resolver.resolve(
            [{"name": "zlib", "version": "1.3.0"}, {"name": "zlib", "version": "1.2.13"}]
        )

    message = str(excinfo.value)
    assert "zlib" in message
    assert "1.3.0" in message and "1.2.13" in message


def test_repeated_identical_version_is_not_a_conflict(registry):
    """Requesting the same version twice is harmless, not an error."""
    order = PackageResolver(registry).resolve(
        [{"name": "zlib", "version": "1.2.13"}, {"name": "zlib", "version": "1.2.13"}]
    )

    assert versions_of(order) == {"zlib": "1.2.13"}


def test_unconstrained_request_still_selects_latest(registry):
    """Existing behaviour: no version specified means newest available."""
    order = PackageResolver(registry).resolve([{"name": "zlib"}])

    assert versions_of(order)["zlib"] == "1.3.0"


def test_explicit_version_applies_to_transitive_use(registry):
    """A pin on a package reached only transitively is still honoured."""
    order = PackageResolver(registry).resolve(
        [{"name": "zlib", "version": "1.2.13"}, {"name": "app"}]
    )

    resolved = versions_of(order)
    assert resolved["zlib"] == "1.2.13"
    assert resolved["app"] == "1.0.0"


# ── Pre-existing behaviour that must not regress ─────────────

def test_build_order_places_dependencies_first(registry):
    order = [recipe.name for recipe in PackageResolver(registry).resolve([{"name": "app"}])]

    assert order.index("zlib") < order.index("app")


def test_unknown_package_raises(registry):
    with pytest.raises(ResolveError, match="not found in registry"):
        PackageResolver(registry).resolve([{"name": "nonexistent"}])


def test_unknown_version_of_known_package_raises(registry):
    with pytest.raises(ResolveError, match="not found in registry"):
        PackageResolver(registry).resolve([{"name": "zlib", "version": "9.9.9"}])


def test_dependency_cycle_raises(tmp_path):
    registry = make_registry(tmp_path, {
        "a.yaml": {"package": "a", "version": "1.0.0", "dependencies": ["b"]},
        "b.yaml": {"package": "b", "version": "1.0.0", "dependencies": ["a"]},
    })

    with pytest.raises(ResolveError, match="cycle"):
        PackageResolver(registry).resolve([{"name": "a"}])


def test_resolve_single_is_unaffected(registry):
    recipe = PackageResolver(registry).resolve_single("zlib", "1.2.13")

    assert recipe.version == "1.2.13"
