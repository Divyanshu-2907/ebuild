# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Tests for ebuild.packages.cache.PackageCache."""

import shutil

from ebuild.packages.cache import PackageCache
from ebuild.packages.recipe import PackageRecipe


def make_recipe():
    return PackageRecipe(
        name="demo",
        version="1.0.0",
        url="https://example.com/demo.tar.gz",
        checksum="sha256:" + "a" * 64,
    )


def test_is_built_is_false_when_install_dir_is_missing(tmp_path):
    """Regression: a valid .built marker is not enough if install/ is gone.

    Callers treat is_built() as "the cached install prefix is usable".
    A leftover marker after a deleted install directory must not skip rebuild.
    """
    cache = PackageCache(tmp_path / "packages")
    recipe = make_recipe()
    cache.ensure_dirs(recipe)
    cache.mark_built(recipe)

    assert cache.is_built(recipe) is True

    shutil.rmtree(cache.install_dir(recipe))

    assert cache.is_built(recipe) is False
