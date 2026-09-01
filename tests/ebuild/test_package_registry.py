from ebuild.packages.recipe import PackageRecipe
from ebuild.packages.registry import PackageRegistry


def make_recipe(version: str) -> PackageRecipe:
    return PackageRecipe(
        name="demo",
        version=version,
        url="https://example.com/demo.tar.gz",
    )


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
