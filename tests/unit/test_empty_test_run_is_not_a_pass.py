# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""`ebuild test` must not report success for a project with no tests.

ctest exits 0 when it finds nothing to run. A CMakeLists.txt with
`enable_testing()` and no `add_test()` still produces a CTestTestfile.cmake, so
`_resolve_test_runner()` finds ctest, ctest prints "No tests were found!!!",
exits 0, and trusting that exit status reports a green suite for a project
containing no tests at all.

Measured on master before this change, against a project with a configured
build tree and zero registered tests:

    $ ctest --test-dir _build
    No tests were found!!!
    ctest exit=0

    $ ebuild test
    [ok] All tests passed.
    exit=0

That is worse than having no test command, because it actively reassures.
"""

import pytest

from ebuild.cli.commands import _parse_test_counts, _ran_no_tests


class TestEmptyRunDetection:
    def test_ctest_no_tests_marker(self):
        assert _ran_no_tests("ctest", "No tests were found!!!") is True

    def test_meson_no_tests_marker(self):
        assert _ran_no_tests("meson test", "No tests defined.") is True

    def test_cargo_zero_tests_marker(self):
        assert _ran_no_tests("cargo test", "running 0 tests") is True

    def test_zero_totals_are_caught_without_a_marker(self):
        # A runner that prints a well-formed summary adding up to nothing is
        # the same situation by a different route.
        assert _ran_no_tests("ctest",
                             "100% tests passed, 0 tests failed out of 0") is True

    def test_a_real_run_is_not_flagged(self):
        assert _ran_no_tests("ctest",
                             "100% tests passed, 0 tests failed out of 17") is False

    def test_a_failing_run_is_not_flagged(self):
        # Failures are already handled by the exit status; this must not
        # reclassify them as "nothing ran".
        assert _ran_no_tests("ctest",
                             "50% tests passed, 3 tests failed out of 6") is False

    def test_make_has_no_marker_and_is_not_flagged(self):
        assert _ran_no_tests("make test", "anything at all") is False


class TestCountParsing:
    """Counts come from the runner's own summary, never from the exit status."""

    def test_ctest_summary(self):
        assert _parse_test_counts(
            "ctest", "100% tests passed, 0 tests failed out of 17") == (17, 0)

    def test_ctest_summary_with_failures(self):
        assert _parse_test_counts(
            "ctest", "50% tests passed, 3 tests failed out of 6") == (3, 3)

    def test_cargo_summary(self):
        assert _parse_test_counts(
            "cargo test", "test result: ok. 12 passed; 0 failed; 0 ignored") == (12, 0)

    def test_meson_summary(self):
        out = "Ok:                 12\nExpected Fail:      0\nFail:               2\n"
        assert _parse_test_counts("meson test", out) == (12, 2)

    def test_make_has_no_standard_summary(self):
        # Rather than invent a format for make, the counts stay unknown and the
        # exit status carries the verdict. A made-up number would be worse than
        # none.
        assert _parse_test_counts("make test", "anything at all") is None

    def test_unrecognised_output_yields_no_counts(self):
        assert _parse_test_counts("ctest", "something else entirely") is None
