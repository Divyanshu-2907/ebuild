# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Unit tests for ebuild.build.ninja_backend.NinjaBackend."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

from ebuild.build.ninja_backend import NinjaBackend
from ebuild.build.toolchain import ResolvedToolchain
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


@pytest.mark.ebuild
class TestObjectPathNamespacing:
    """Object files are namespaced by target: ``obj/<target>/<source>.o``.

    Two targets may legitimately list the same source -- a library and a test
    binary sharing a helper, or one source built twice with different defines.
    Naming an object from the source alone makes both targets claim one
    output, which ninja rejects with "multiple rules generate ...", and
    silently drops one target's cflags before it ever gets there.
    """

    @staticmethod
    def _shared_source_config(tmp_path, app_sources):
        return ProjectConfig(
            name="shared_source",
            version="1.0.0",
            targets=[
                TargetConfig(
                    name="util",
                    target_type="static_library",
                    sources=["src/util.c"],
                    defines=["BUILD_LIB=1"],
                ),
                TargetConfig(
                    name="app",
                    target_type="executable",
                    sources=app_sources,
                    defines=["BUILD_APP=1"],
                ),
            ],
            source_dir=tmp_path,
        )

    def test_shared_source_gets_one_object_per_target(self, tmp_path):
        """A source used by two targets must compile to two distinct objects."""
        config = self._shared_source_config(tmp_path, ["src/main.c", "src/util.c"])

        build_dir = tmp_path / "_build"
        NinjaBackend(config, build_dir, ResolvedToolchain()).generate()

        ninja_content = (build_dir / "build.ninja").read_text(encoding="utf-8")

        # Split on the rule separator rather than the first colon: on Windows
        # the object path starts with a drive letter.
        outputs = [
            line[len("build "):].split(": cc ", 1)[0].strip()
            for line in ninja_content.splitlines()
            if line.startswith("build ") and ": cc " in line
        ]
        assert len(outputs) == 3, f"expected 3 compile edges, got {outputs}"
        assert len(set(outputs)) == 3, f"duplicate object outputs: {outputs}"

        # Each target's defines must survive onto its own object.
        assert "-DBUILD_LIB=1" in ninja_content
        assert "-DBUILD_APP=1" in ninja_content

    def test_shared_source_manifest_is_valid_ninja(self, tmp_path, monkeypatch):
        """The generated manifest must load in real ninja, not just look right.

        Ninja treats two edges producing one output as an error, so this is
        the check that actually proves the generated build is usable.

        The build directory is relative and the working directory is the
        project root, mirroring how ``ebuild build`` invokes the backend.
        """
        pytest.importorskip("ninja", reason="ninja package not installed")

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "util.c").write_text(
            "int util_answer(void) { return 42; }\n", encoding="utf-8"
        )
        (src_dir / "main.c").write_text(
            "int util_answer(void);\n"
            "int main(void) { return util_answer() == 42 ? 0 : 1; }\n",
            encoding="utf-8",
        )

        config = self._shared_source_config(tmp_path, ["src/main.c", "src/util.c"])

        monkeypatch.chdir(tmp_path)
        build_dir = Path("_build")
        NinjaBackend(config, build_dir, ResolvedToolchain()).generate()

        # -n parses and validates the manifest without running the compiler,
        # so this test needs no toolchain on the machine running it.
        result = subprocess.run(
            [sys.executable, "-m", "ninja", "-f", str(build_dir / "build.ninja"), "-n"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "ninja rejected the generated manifest:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_compile_commands_distinguishes_shared_source_entries(self, tmp_path):
        """compile_commands.json entries for a shared source must differ.

        Two targets compiling one file legitimately produce two entries; each
        needs its own -o so a consumer can tell them apart.
        """
        config = self._shared_source_config(tmp_path, ["src/util.c"])

        build_dir = tmp_path / "_build"
        NinjaBackend(config, build_dir, ResolvedToolchain()).generate()

        cc_data = json.loads(
            (build_dir / "compile_commands.json").read_text(encoding="utf-8")
        )
        shared = [e for e in cc_data if e["file"] == "src/util.c"]
        assert len(shared) == 2
        assert shared[0]["command"] != shared[1]["command"]

        # Differing commands alone are not enough -- the per-target defines
        # would differ regardless. It is the object each entry names that has
        # to be distinct, which is what a consumer keys on.
        objects = [e["command"].split(" -o ", 1)[1].strip() for e in shared]
        assert len(set(objects)) == 2, f"entries name the same object: {objects}"


if __name__ == "__main__":
    unittest.main()
