# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Unit tests for BackendDispatcher.

Regression coverage for: dispatching an unhandled backend name (e.g.
"ninja", which is routed elsewhere by the CLI and never implemented here)
used to silently do nothing in configure()/build() and let the caller
report a false "Build completed successfully" instead of failing loudly.
"""

import pytest

from ebuild.build.dispatch import BackendDispatcher


@pytest.mark.ebuild
class TestBackendDispatcherUnknownBackend:
    """configure()/build() must fail loudly on backends they don't
    implement."""

    def test_configure_unknown_backend_raises(self, tmp_path):
        dispatcher = BackendDispatcher(tmp_path / "src", tmp_path / "build")
        with pytest.raises(RuntimeError, match="ninja"):
            dispatcher.configure(backend="ninja")

    def test_build_unknown_backend_raises(self, tmp_path):
        dispatcher = BackendDispatcher(tmp_path / "src", tmp_path / "build")
        with pytest.raises(RuntimeError, match="ninja"):
            dispatcher.build(backend="ninja")

    def test_configure_typo_backend_raises(self, tmp_path):
        """Any unrecognized backend name should raise, not just 'ninja'."""
        dispatcher = BackendDispatcher(tmp_path / "src", tmp_path / "build")
        with pytest.raises(RuntimeError, match="cmka"):
            dispatcher.configure(backend="cmka")


@pytest.mark.ebuild
class TestBackendDispatcherCargoConfigure:
    """cargo has no configure step and should remain a documented no-op."""

    def test_cargo_configure_is_noop(self, tmp_path):
        dispatcher = BackendDispatcher(tmp_path / "src", tmp_path / "build")
        # Should not raise, and should not require any external tool.
        dispatcher.configure(backend="cargo")
