import pytest

from ebuild.packages.recipe import PackageRecipe
from ebuild.packages.registry import PackageRegistry, version_sort_key


def make_recipe(version: str) -> PackageRecipe:
    return PackageRecipe(
        name="demo",
        version=version,
        url="https://example.com/demo.tar.gz",
    )


def registry_with(*versions: str) -> PackageRegistry:
    registry = PackageRegistry()
    for version in versions:
        registry._register(make_recipe(version))
    return registry


def test_list_all_versions_uses_numeric_version_order():
    registry = PackageRegistry()

    registry._register(make_recipe("1.2.0"))
    registry._register(make_recipe("1.10.0"))
    registry._register(make_recipe("1.9.0"))

    versions = registry.list_all_versions("demo")

    assert [recipe.version for recipe in versions] == [
        "1.2.0",
        "1.9.0",
        "1.10.0",
    ]


# --- Versions that are not dotted integers -----------------------------------
#
# PackageRecipe.validate() accepts any non-empty version string, so these all
# load and register. Ordering used to be [int(x) for x in v.split('.')], which
# raised ValueError on every one of them.


@pytest.mark.parametrize(
    "version",
    [
        "v2.9.3",        # littlefs publishes its releases with a leading v
        "3.6.0-rc1",     # pre-release tag
        "1.3.1+patch2",  # build metadata
        "2024.06",       # date-stamped release
        "main",          # a branch, not a release
        "",              # degenerate, but reachable through _register()
    ],
)
def test_lookup_survives_a_non_numeric_version(version):
    registry = registry_with(version)

    assert registry.get("demo").version == version
    assert [r.version for r in registry.list_packages()] == [version]
    assert [r.version for r in registry.list_all_versions("demo")] == [version]


def test_one_odd_version_does_not_break_lookup_of_the_rest():
    """A single unparseable version used to take down the whole registry.

    get() with no version scans every version of the package, and
    list_packages() scans every package -- which the resolver calls to build
    its 'package not found' message. One recipe with a 'v' prefix therefore
    turned an ordinary lookup anywhere in the project into a ValueError.
    """
    registry = registry_with("1.0.0", "v9.9.9", "1.2.0")

    assert registry.get("demo").version == "v9.9.9"
    assert registry.get("demo", "1.2.0").version == "1.2.0"
    assert len(registry.list_all_versions("demo")) == 3


def test_leading_v_does_not_change_precedence():
    registry = registry_with("v2.9.3", "2.10.0")

    assert registry.get("demo").version == "2.10.0"


def test_prerelease_sorts_below_its_release():
    registry = registry_with("3.6.0", "3.6.0-rc1", "3.6.0-rc2")

    assert [r.version for r in registry.list_all_versions("demo")] == [
        "3.6.0-rc1",
        "3.6.0-rc2",
        "3.6.0",
    ]
    assert registry.get("demo").version == "3.6.0"


def test_build_metadata_does_not_outrank_the_next_release():
    registry = registry_with("1.3.1+patch2", "1.3.2")

    assert registry.get("demo").version == "1.3.2"


def test_version_ordering_is_total_and_never_raises():
    """Every pair must be comparable, in both directions, without raising."""
    versions = [
        "1.0.0", "1.0", "1.0.1", "v1.0.1", "2024.06", "1.0.0-rc1",
        "1.0.0+meta", "main", "", "1.0.0-alpha.1", "10.0.0",
    ]
    keys = [version_sort_key(v) for v in versions]

    for left in keys:
        for right in keys:
            assert (left < right) or (left >= right)

    assert sorted(versions, key=version_sort_key) == sorted(
        versions, key=version_sort_key
    )
