import hashlib
import re
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest

import fetch_aligner_model as aligner
import fetch_common as common


class _Response:
    """A response with a fixed body and no announced length."""

    def __init__(self, body: bytes) -> None:
        self.headers: dict[str, str] = {}
        self._body = body

    def read(self, size: int, /) -> bytes:
        block, self._body = self._body[:size], self._body[size:]
        return block


class _Opener:
    """Serves `body` for any URL and remembers the URLs asked for."""

    def __init__(self, body: bytes = b"not the pinned content") -> None:
        self.body = body
        self.urls: list[str] = []

    def __call__(self, url: str) -> AbstractContextManager[common.Response]:
        self.urls.append(url)
        return nullcontext(_Response(self.body))


def test_the_url_names_the_pinned_revision() -> None:
    assert aligner.url_for("vocab.json") == (
        "https://huggingface.co/parseh/aligner-ja/resolve/"
        "66eb48c224294f16a5aae3500964b756d9d23354/vocab.json"
    )


def test_default_files_are_the_model_the_vocabulary_and_the_license_texts() -> None:
    assert set(aligner.select_files(None)) == {
        "model.int8.onnx",
        "vocab.json",
        "meta.json",
        "LICENSE",
        "NOTICE",
    }


def test_named_files_replace_the_defaults() -> None:
    assert aligner.select_files(["vocab.json"]) == ["vocab.json"]


def test_a_file_named_twice_is_fetched_once() -> None:
    assert aligner.select_files(["vocab.json", "vocab.json"]) == ["vocab.json"]


def test_an_unknown_file_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        aligner.select_files(["other.bin"])


def test_every_pinned_hash_is_a_sha256_hex_digest() -> None:
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in aligner.PINNED_SHA256.values())


def test_every_default_file_has_a_pinned_hash() -> None:
    assert set(aligner.DEFAULT_FILES) == set(aligner.PINNED_SHA256)


def test_main_reports_an_unknown_file_name_as_a_failure(tmp_path: Path) -> None:
    assert aligner.main(["--dest", str(tmp_path), "--files", "other.bin"], _Opener()) == 1


def test_main_reports_a_hash_mismatch_as_a_failure(tmp_path: Path) -> None:
    assert aligner.main(["--dest", str(tmp_path), "--files", "NOTICE"], _Opener()) == 1


def test_main_asks_only_for_the_named_file(tmp_path: Path) -> None:
    opener = _Opener()

    aligner.main(["--dest", str(tmp_path), "--files", "NOTICE"], opener)

    assert opener.urls == [aligner.url_for("NOTICE")]


def test_main_succeeds_when_the_download_matches_the_pinned_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"notice text"
    monkeypatch.setitem(aligner.PINNED_SHA256, "NOTICE", hashlib.sha256(body).hexdigest())

    assert aligner.main(["--dest", str(tmp_path), "--files", "NOTICE"], _Opener(body)) == 0
