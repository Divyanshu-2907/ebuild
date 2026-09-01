# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Tests for ebuild.packages.fetcher.PackageFetcher.

No test here touches the network: ``urlretrieve`` is replaced with a stub
that synthesises a small tarball whose contents identify the URL it was
asked for. That makes cross-package contamination observable — a package
extracted from the wrong archive carries the wrong marker.
"""

import hashlib
import gzip
import io
import tarfile

import pytest

from ebuild.packages.fetcher import FetchError, PackageFetcher
from ebuild.packages.recipe import PackageRecipe

# Two real-world recipe URLs whose basenames collide. GitHub tag archives
# reduce to the tag name alone, which carries no package identity —
# recipes/littlefs.yaml already uses this form.
LITTLEFS_URL = "https://github.com/littlefs-project/littlefs/archive/refs/tags/v2.9.3.tar.gz"
OTHERLIB_URL = "https://github.com/example-org/otherlib/archive/refs/tags/v2.9.3.tar.gz"

# The same package at two versions behind a version-less filename.
LWIP_220_URL = "https://example.org/lwip/releases/2.2.0/source.tar.gz"
LWIP_230_URL = "https://example.org/lwip/releases/2.3.0/source.tar.gz"


#: Placeholder digest for tests that never reach checksum verification (bad
#: URL, unsupported format). Real-looking so it passes recipe validation.
DUMMY_SHA256 = "sha256:" + "a" * 64


def make_recipe(name, version="2.9.3", url=None, checksum=None):
    """Build a recipe.

    ``checksum`` defaults to the digest of the archive ``fake_download``
    serves for ``url``, so tests about caching and extraction get past
    verification. Pass an explicit value to exercise the checksum paths, or
    ``""`` to exercise a recipe with no pin at all.
    """
    resolved_url = url if url is not None else LITTLEFS_URL
    if checksum is None:
        try:
            checksum = "sha256:" + sha256_of(targz_bytes(resolved_url))
        except Exception:
            checksum = DUMMY_SHA256
    return PackageRecipe(
        name=name,
        version=version,
        url=resolved_url,
        checksum=checksum,
    )


def targz_bytes(marker):
    """A valid .tar.gz containing a single file whose body is *marker*.

    Byte-for-byte reproducible. Both the tar header and the gzip header carry a
    timestamp, and the defaults are "now" -- so two calls with the same marker
    produced different bytes, and therefore different SHA-256, if they landed on
    opposite sides of a second boundary. That made every checksum derived from
    this helper a coin flip: the digest computed for the recipe had to match the
    bytes handed out by fake_download later. It held on fast Linux runners and
    failed on Windows. Pinning both timestamps to 0 removes the race.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        data = marker.encode("utf-8")
        info = tarfile.TarInfo("pkg/marker.txt")
        info.size = len(data)
        info.mtime = 0
        tar.addfile(info, io.BytesIO(data))

    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def marker_in(src_dir):
    return (src_dir / "pkg" / "marker.txt").read_text(encoding="utf-8")


@pytest.fixture
def fake_download(monkeypatch):
    """Serve a URL-identifying tarball instead of hitting the network.

    Returns the list of URLs actually requested, so tests can distinguish
    "served from cache" from "downloaded again".
    """
    calls = []

    def _urlretrieve(url, filename):
        calls.append(url)
        with open(filename, "wb") as f:
            f.write(targz_bytes(url))

    monkeypatch.setattr("ebuild.packages.fetcher.urlretrieve", _urlretrieve)
    return calls


# ── Download cache keying ────────────────────────────────────

def test_colliding_url_basenames_do_not_cross_contaminate(tmp_path, fake_download):
    """Regression: a package must not be built from another's sources.

    Both URLs end in ``v2.9.3.tar.gz``. Keyed on the basename alone, the
    second fetch is served the first package's archive from cache.
    """
    fetcher = PackageFetcher(tmp_path / "dl")
    littlefs_src = tmp_path / "src-littlefs"
    otherlib_src = tmp_path / "src-otherlib"

    fetcher.fetch(make_recipe("littlefs", url=LITTLEFS_URL), littlefs_src)
    fetcher.fetch(make_recipe("otherlib", url=OTHERLIB_URL), otherlib_src)

    assert marker_in(littlefs_src) == LITTLEFS_URL
    assert marker_in(otherlib_src) == OTHERLIB_URL
    assert fake_download == [LITTLEFS_URL, OTHERLIB_URL]


def test_versions_sharing_a_basename_do_not_collide(tmp_path, fake_download):
    """Two versions of one package behind version-less filenames."""
    fetcher = PackageFetcher(tmp_path / "dl")
    old_src = tmp_path / "src-2.2.0"
    new_src = tmp_path / "src-2.3.0"

    fetcher.fetch(make_recipe("lwip", version="2.2.0", url=LWIP_220_URL), old_src)
    fetcher.fetch(make_recipe("lwip", version="2.3.0", url=LWIP_230_URL), new_src)

    assert marker_in(old_src) == LWIP_220_URL
    assert marker_in(new_src) == LWIP_230_URL


def test_is_downloaded_is_per_package(tmp_path, fake_download):
    fetcher = PackageFetcher(tmp_path / "dl")
    littlefs = make_recipe("littlefs", url=LITTLEFS_URL)
    otherlib = make_recipe("otherlib", url=OTHERLIB_URL)

    fetcher.fetch(littlefs, tmp_path / "src")

    assert fetcher.is_downloaded(littlefs) is True
    assert fetcher.is_downloaded(otherlib) is False


def test_archive_is_cached_under_the_package_slug(tmp_path, fake_download):
    fetcher = PackageFetcher(tmp_path / "dl")

    fetcher.fetch(make_recipe("littlefs"), tmp_path / "src")

    assert (tmp_path / "dl" / "littlefs-2.9.3" / "v2.9.3.tar.gz").is_file()


def test_cached_archive_is_reused_not_redownloaded(tmp_path, fake_download):
    fetcher = PackageFetcher(tmp_path / "dl")
    recipe = make_recipe("littlefs")

    fetcher.fetch(recipe, tmp_path / "src-a")
    fetcher.fetch(recipe, tmp_path / "src-b")

    assert fake_download == [LITTLEFS_URL]
    assert marker_in(tmp_path / "src-b") == LITTLEFS_URL


# ── Checksum handling ────────────────────────────────────────

def test_checksum_mismatch_removes_the_cached_archive(tmp_path, fake_download):
    """Regression: a bad archive must not poison every later build.

    ``_download`` short-circuits on existence, so an archive left behind
    after a failed verification is returned again by every later fetch —
    the build stays broken until someone deletes it by hand.
    """
    fetcher = PackageFetcher(tmp_path / "dl")
    recipe = make_recipe("littlefs", checksum="sha256:" + "0" * 64)

    with pytest.raises(FetchError, match="Checksum mismatch"):
        fetcher.fetch(recipe, tmp_path / "src")

    assert fetcher.is_downloaded(recipe) is False

    with pytest.raises(FetchError, match="Checksum mismatch"):
        fetcher.fetch(recipe, tmp_path / "src")

    # The retry re-downloaded rather than re-reading the rejected file.
    assert fake_download == [LITTLEFS_URL, LITTLEFS_URL]


def test_matching_checksum_keeps_the_archive(tmp_path, fake_download):
    """The cleanup must not fire on a good archive."""
    fetcher = PackageFetcher(tmp_path / "dl")
    recipe = make_recipe("littlefs", checksum="sha256:" + sha256_of(targz_bytes(LITTLEFS_URL)))

    fetcher.fetch(recipe, tmp_path / "src")

    assert fetcher.is_downloaded(recipe) is True


def test_bare_checksum_without_sha256_prefix_is_accepted(tmp_path, fake_download):
    fetcher = PackageFetcher(tmp_path / "dl")
    recipe = make_recipe("littlefs", checksum=sha256_of(targz_bytes(LITTLEFS_URL)))

    fetcher.fetch(recipe, tmp_path / "src")

    assert marker_in(tmp_path / "src") == LITTLEFS_URL


def test_recipe_without_a_checksum_is_refused(tmp_path, fake_download):
    """A recipe with no checksum used to be fetched and extracted unverified.

    The URL alone is "whatever that host serves today". Refusing is the only
    honest outcome: there is nothing to check the download against.
    """
    fetcher = PackageFetcher(tmp_path / "dl")

    with pytest.raises(FetchError, match="no checksum"):
        fetcher.fetch(make_recipe("littlefs", checksum=""), tmp_path / "src")

    # And nothing was downloaded or extracted on the way to that refusal.
    assert not (tmp_path / "src").exists()


def test_plaintext_http_is_refused(tmp_path, fake_download):
    """https only: a pin is worth much less over a transport anyone can rewrite."""
    fetcher = PackageFetcher(tmp_path / "dl")
    recipe = make_recipe("littlefs", url="http://example.org/lib.tar.gz",
                         checksum=DUMMY_SHA256)

    with pytest.raises(FetchError, match="https"):
        fetcher.fetch(recipe, tmp_path / "src")


# ── Extraction ───────────────────────────────────────────────

def test_fetch_extracts_into_the_requested_directory(tmp_path, fake_download):
    fetcher = PackageFetcher(tmp_path / "dl")
    src_dir = tmp_path / "src"

    result = fetcher.fetch(make_recipe("littlefs"), src_dir)

    assert result == src_dir
    assert marker_in(src_dir) == LITTLEFS_URL


def test_unsupported_archive_format_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ebuild.packages.fetcher.urlretrieve",
        lambda url, filename: open(filename, "wb").write(b"not an archive"),
    )
    fetcher = PackageFetcher(tmp_path / "dl")
    # Checksum of the bytes the patched urlretrieve writes, so the fetch gets
    # past verification and reaches the format check this test is about.
    recipe = make_recipe(
        "littlefs",
        url="https://example.org/littlefs/v2.9.3.rar",
        checksum="sha256:6bbf954ab0045bc546f16a6db16c95afef820dccd807348411ea924dabb972e9",
    )

    with pytest.raises(FetchError, match="Unsupported archive format"):
        fetcher.fetch(recipe, tmp_path / "src")


# ── URL validation (pre-existing behaviour, kept covered) ────

def test_missing_url_is_rejected(tmp_path):
    fetcher = PackageFetcher(tmp_path / "dl")

    with pytest.raises(FetchError, match="No URL specified"):
        fetcher.fetch(make_recipe("littlefs", url=""), tmp_path / "src")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x.tar.gz"])
def test_non_http_url_schemes_are_rejected(tmp_path, url):
    fetcher = PackageFetcher(tmp_path / "dl")

    with pytest.raises(FetchError, match="Invalid URL scheme"):
        fetcher.fetch(make_recipe("littlefs", url=url), tmp_path / "src")


def test_failed_download_leaves_no_partial_archive(tmp_path, monkeypatch):
    def _boom(url, filename):
        with open(filename, "wb") as f:
            f.write(b"partial")
        raise OSError("connection reset")

    monkeypatch.setattr("ebuild.packages.fetcher.urlretrieve", _boom)
    fetcher = PackageFetcher(tmp_path / "dl")
    recipe = make_recipe("littlefs")

    with pytest.raises(FetchError, match="Failed to download"):
        fetcher.fetch(recipe, tmp_path / "src")

    assert fetcher.is_downloaded(recipe) is False
