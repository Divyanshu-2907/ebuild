"""Regression tests for the command-injection fix in _create_initramfs().

_create_initramfs() used to build a single shell string
(``cd {rootfs} && find . | cpio ... > {initramfs}``) and execute it with
``subprocess.run(cmd, shell=True, ...)``. Both ``rootfs`` and ``build_dir``
flow in from the ``--build-dir`` CLI option (an unrestricted click.Path()),
so a directory name containing shell metacharacters was executed as shell
syntax rather than treated as a literal path. These tests prove the fix
(an argv-list Popen pipeline with no shell involved) both blocks the
injection and still produces a correct initramfs.

Note on the injection check: a directory name can never contain "/" (that's
a filesystem-level restriction on any POSIX path component, not just a
Python one), so a marker command like ``touch /abs/path/marker`` can't be
embedded as a literal directory name for a mkdir-based PoC. Instead these
tests rely on a more direct and fully deterministic signal: with the old
``shell=True`` code, the final ``> {initramfs}`` redirect target itself
would be corrupted by shell metacharacters injected via ``build_dir``,
so the initramfs would fail to land at the exact literal path we asked
for. The fix must produce a valid initramfs at exactly that path, with no
shell ever getting a chance to reinterpret it.
"""

import gzip
import shutil
import subprocess

import pytest

from ebuild.cli.integration import _create_initramfs

# _create_initramfs() drives find(1) and cpio(1) directly. Neither exists on a
# stock Windows runner, so these fail with WinError 2 before reaching anything
# they mean to test. Building a Linux initramfs is not a Windows operation;
# skipping is the honest outcome, matching how test_ninja_backend.py skips when
# no host C compiler is present.
requires_cpio = pytest.mark.skipif(
    shutil.which("cpio") is None or shutil.which("find") is None,
    reason="find(1)/cpio(1) not available on this host",
)


@requires_cpio
def test_create_initramfs_produces_valid_gzip_with_expected_content(tmp_path):
    """Functional regression: the pipeline must still work correctly."""
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    (rootfs / "hello.txt").write_text("hi from rootfs\n")

    build_dir = tmp_path / "build"
    build_dir.mkdir()

    initramfs = _create_initramfs(rootfs, build_dir)

    assert initramfs == build_dir / "initramfs.cpio.gz"
    assert initramfs.exists()
    assert initramfs.stat().st_size > 0

    # Valid gzip stream.
    with gzip.open(initramfs, "rb") as f:
        cpio_data = f.read()
    assert cpio_data.startswith(b"07070")  # newc cpio magic

    # cpio -t lists member paths; our test file must be in there.
    result = subprocess.run(
        ["cpio", "-t"],
        input=cpio_data,
        capture_output=True,
    )
    assert b"hello.txt" in result.stdout


@requires_cpio
def test_create_initramfs_build_dir_with_shell_metacharacters_is_not_interpreted(tmp_path):
    """A build_dir name containing shell syntax must be treated as a plain
    literal path component, never parsed as shell syntax. Pre-fix, a name
    like ``build; touch pwned #`` would corrupt the shell's ``>`` redirect
    target, so the initramfs would NOT land at the exact literal path
    requested."""
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    (rootfs / "f.txt").write_text("data\n")

    evil_build_dir = tmp_path / "build; touch pwned_marker #"
    evil_build_dir.mkdir()

    initramfs = _create_initramfs(rootfs, evil_build_dir)

    expected = evil_build_dir / "initramfs.cpio.gz"
    assert initramfs == expected
    assert expected.exists(), "initramfs did not land at the exact literal path -- shell reinterpreted it"
    assert expected.stat().st_size > 0

    with gzip.open(expected, "rb") as f:
        assert f.read().startswith(b"07070")

    # No stray file from an injected `touch` anywhere near the test area.
    assert not (tmp_path / "pwned_marker").exists()
    assert not (rootfs / "pwned_marker").exists()


@requires_cpio
def test_create_initramfs_rootfs_with_shell_metacharacters_is_not_interpreted(tmp_path):
    """Same check for the ``rootfs`` argument (the ``cd {rootfs}`` half of
    the old shell string)."""
    evil_rootfs = tmp_path / "rootfs; touch pwned_marker2 #"
    evil_rootfs.mkdir()
    (evil_rootfs / "f.txt").write_text("data\n")

    build_dir = tmp_path / "build2"
    build_dir.mkdir()

    initramfs = _create_initramfs(evil_rootfs, build_dir)

    assert initramfs == build_dir / "initramfs.cpio.gz"
    assert initramfs.exists()
    assert initramfs.stat().st_size > 0

    with gzip.open(initramfs, "rb") as f:
        cpio_data = f.read()
    assert cpio_data.startswith(b"07070")

    # The pipeline must have actually cd'd into the evil rootfs (via `cwd=`,
    # not a shell `cd`) and archived its real content.
    result = subprocess.run(["cpio", "-t"], input=cpio_data, capture_output=True)
    assert b"f.txt" in result.stdout

    assert not (tmp_path / "pwned_marker2").exists()
    assert not (build_dir / "pwned_marker2").exists()
