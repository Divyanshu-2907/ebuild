# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Regression tests for external build backend dispatch."""

import pytest

from ebuild.build.dispatch import BackendDispatcher, BackendError


@pytest.mark.parametrize("operation", ["configure", "build", "clean"])
def test_unsupported_backend_fails_closed(tmp_path, operation):
    dispatcher = BackendDispatcher(tmp_path, tmp_path / "build")

    with pytest.raises(
        BackendError,
        match="Unknown build backend 'system'",
    ):
        getattr(dispatcher, operation)("system")


def test_tier_one_configure_is_a_supported_noop(tmp_path):
    build_dir = tmp_path / "build"
    dispatcher = BackendDispatcher(tmp_path, build_dir)

    dispatcher.configure("make")

    assert build_dir.is_dir()
