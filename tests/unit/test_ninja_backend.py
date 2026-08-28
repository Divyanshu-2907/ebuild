# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Unit tests for ebuild.build.ninja_backend.NinjaBackend."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ebuild.build.ninja_backend import NinjaBackend, _ninja_path
from ebuild.core.config import ProjectConfig, TargetConfig


def _toolchain():
    return SimpleNamespace(cc="cc", cxx="c++", ar="ar")


class TestNinjaBackendSharedLibrary(unittest.TestCase):
    """A shared_library target must link with the platform's shared-object
    flag and get the same -L/-l wiring as executables. Previously it fell
    through to the generic `link` rule with no flags and no libs at all,
    silently producing a broken artifact."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def _generate(self, name: str, target: TargetConfig, package_paths=None) -> str:
        build_dir = Path(self._tmpdir.name) / name
        config = ProjectConfig(name="proj", version="1.0", targets=[target], source_dir=build_dir)
        backend = NinjaBackend(config, build_dir, _toolchain(), package_paths=package_paths)
        backend.generate()
        return (build_dir / "build.ninja").read_text(encoding="utf-8")

    def test_shared_library_gets_shared_flag(self):
        target = TargetConfig(name="mylib", target_type="shared_library", sources=["lib.c"])
        ninja = self._generate("shared", target)

        shared_flag = "-dynamiclib" if sys.platform == "darwin" else "-shared"
        self.assertIn(shared_flag, ninja)
        # It must use the `link` rule (compiler driver), not `ar_rule`.
        lib_line = next(line for line in ninja.splitlines() if "libmylib" in line and line.startswith("build"))
        self.assertIn(": link ", lib_line)

    def test_shared_library_gets_lib_dirs_and_libs(self):
        target = TargetConfig(
            name="mylib", target_type="shared_library", sources=["lib.c"], uses=["zlib"]
        )
        lib_dir = Path(self._tmpdir.name) / "zlib-lib"
        package_paths = {
            "zlib": SimpleNamespace(include_dirs=[], lib_dirs=[lib_dir], libraries=["z"])
        }
        ninja = self._generate("shared_libs", target, package_paths=package_paths)

        self.assertIn(f"-L{lib_dir}", ninja)
        self.assertIn("libs = -lz", ninja)

    def test_static_library_unaffected(self):
        target = TargetConfig(name="mylib", target_type="static_library", sources=["lib.c"])
        ninja = self._generate("static", target)

        self.assertIn(": ar_rule", ninja)
        self.assertNotIn("-shared", ninja)
        self.assertNotIn("-dynamiclib", ninja)


class TestNinjaPathEscaping(unittest.TestCase):
    """Ninja splits build statements on unescaped spaces and colons.

    A Windows absolute path puts a drive-letter colon into the output field, so
    Ninja read the statement as a rule separator and every generated file was
    rejected with "expected build command name" -- the backend produced no
    usable build on Windows at all. Paths in build statements must be escaped;
    variable values must not be, or the flags reach the compiler mangled.
    """

    def test_colons_and_spaces_in_paths_are_escaped(self):
        self.assertEqual(_ninja_path(r"C:\build\main.o"), r"C$:\build\main.o")
        self.assertEqual(_ninja_path("/tmp/my project/main.o"), "/tmp/my$ project/main.o")

    def test_dollar_is_escaped_before_the_escapes_it_introduces(self):
        self.assertEqual(_ninja_path("a$b"), "a$$b")
        self.assertEqual(_ninja_path("a$b:c"), "a$$b$:c")

    def test_ordinary_posix_paths_are_unchanged(self):
        self.assertEqual(_ninja_path("/tmp/build/obj/app/src/main.o"),
                         "/tmp/build/obj/app/src/main.o")


class TestNinjaWindowsStylePaths(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def test_build_statement_output_is_escaped(self):
        build_dir = Path(self._tmpdir.name) / "b"
        target = TargetConfig(name="app", target_type="executable", sources=["main.c"])
        config = ProjectConfig(name="proj", version="1.0", targets=[target],
                               source_dir=build_dir)
        NinjaBackend(config, build_dir, _toolchain()).generate()
        ninja = (build_dir / "build.ninja").read_text(encoding="utf-8")

        for line in ninja.splitlines():
            if not line.startswith("build "):
                continue
            # Exactly one unescaped colon per build statement: the one that
            # separates outputs from the rule name.
            without_escapes = line.replace("$:", "").replace("$$", "")
            self.assertEqual(without_escapes.count(":"), 1, line)


if __name__ == "__main__":
    unittest.main()
