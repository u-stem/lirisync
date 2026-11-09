"""Download the separation model and its reference files for the Medium test.

Nothing here is shipped: the model is fetched into a local directory that the
reference test reads through ``LIRISYNC_SEPARATOR_DIR``. Every file comes from a
pinned revision and is checked against a pinned SHA-256 before it is moved into
place, so a truncated or changed download never ends up next to good files.

    uv --directory workers/align run python tools/fetch_separator_model.py --dest DIR
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from http.client import HTTPException
from pathlib import Path
from typing import Protocol

REPOSITORY = "redbaty/ytm-vocal-separator"
REVISION = "d9d3f27d58c4f9c0286a07ed541b18ceaa91f107"

PINNED_SHA256 = {
    "sep-all-int8.onnx": "e9570dac2ae14382c99357a547a6739777a029ad7f2b5f6e6bc22e9b0e7b2580",
    "sep-all-fp16.onnx": "df90c280c5a19183c7f51979b3904bae38e89195f77e5fe890976bddddb21f62",
    "ref-input.f32": "1eb9a90925f2e11ec5b1908d8e7bf219ea302ea371aa01cf6a261d514b275758",
    "ref-stems-all-int8.f32": "5ec98fdb9770eadba51e4bb6e2dbd7d336f9a5c74868378f8a1a3cc7ddc14d1d",
    "ref-stems-all-fp16.f32": "b60491965e5edf935102bb6581f6b2dbc20b7191a0dd2a3662691d5b362974cc",
}
DEFAULT_FILES = ("sep-all-int8.onnx", "ref-input.f32", "ref-stems-all-int8.f32")
FP16_FILES = ("sep-all-fp16.onnx", "ref-stems-all-fp16.f32")

_BLOCK = 1024 * 1024
_PROGRESS_STEP = 16 * _BLOCK
_TIMEOUT_SECONDS = 60


class Headers(Protocol):
    def get(self, name: str, failobj: None = None, /) -> str | None: ...


class Response(Protocol):
    """The part of an HTTP response that is used: its headers and a body to read."""

    @property
    def headers(self) -> Headers: ...

    def read(self, size: int, /) -> bytes: ...


Opener = Callable[[str], AbstractContextManager[Response]]
Log = Callable[[str], None]


def url_for(name: str) -> str:
    return f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"


def open_url(url: str) -> AbstractContextManager[Response]:
    response: AbstractContextManager[Response] = urllib.request.urlopen(
        url, timeout=_TIMEOUT_SECONDS
    )
    return response


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def select_files(names: Sequence[str] | None, *, with_fp16: bool) -> list[str]:
    """The files to fetch: `names` if given, else the defaults; plus fp16 on request."""
    extra = FP16_FILES if with_fp16 else ()
    chosen = [*DEFAULT_FILES, *extra] if names is None else [*names, *extra]
    unknown = [name for name in chosen if name not in PINNED_SHA256]
    if unknown:
        raise ValueError(f"unknown file(s) {unknown}; known: {sorted(PINNED_SHA256)}")
    return chosen


def fetch_file(url: str, target: Path, sha256: str, opener: Opener, log: Log) -> bool:
    """Download `url` to `target` unless `target` already has `sha256`.

    Returns True when a download happened. The bytes go to a temporary file in
    the same directory, are flushed to disk, and are renamed over `target` only
    after the whole body arrived and the hash matches. A body shorter than the
    announced Content-Length raises `ValueError("truncated download ...")`, a
    wrong hash raises `ValueError("... SHA-256 mismatch ...")`; in every
    failure the temporary file is removed and `target` is left as it was.
    """
    if target.exists() and sha256_of(target) == sha256:
        log(f"{target.name}: already present, skipped")
        return False

    digest = hashlib.sha256()
    received = 0
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f"{target.name}.", suffix=".part", delete=False
    ) as out:
        partial = Path(out.name)
        try:
            with opener(url) as response:
                announced = _announced_length(response)
                while block := response.read(_BLOCK):
                    out.write(block)
                    digest.update(block)
                    before, received = received, received + len(block)
                    if received // _PROGRESS_STEP > before // _PROGRESS_STEP:
                        log(f"{target.name}: {received / _BLOCK:.0f} MiB")
            if announced is not None and received != announced:
                raise ValueError(
                    f"{target.name}: truncated download (got {received} of {announced} bytes)"
                )
            if digest.hexdigest() != sha256:
                raise ValueError(
                    f"{target.name}: SHA-256 mismatch (expected {sha256}, got {digest.hexdigest()})"
                )
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.close()
            partial.unlink(missing_ok=True)
            raise
    partial.replace(target)
    log(f"{target.name}: downloaded {received} bytes")
    return True


def _announced_length(response: Response) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None or not value.isdigit():
        return None
    return int(value)


def main(argv: Sequence[str] | None = None, opener: Opener = open_url) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dest", type=Path, required=True, help="directory to put the files in")
    parser.add_argument(
        "--files",
        nargs="+",
        metavar="NAME",
        help=f"files to fetch (default: {', '.join(DEFAULT_FILES)}); known: "
        f"{', '.join(PINNED_SHA256)}",
    )
    parser.add_argument(
        "--fp16",
        action="store_true",
        help="also fetch the fp16 model (460 MB, for GPU) and its reference",
    )
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        print(message, file=sys.stderr)

    try:
        names = select_files(args.files, with_fp16=args.fp16)
        args.dest.mkdir(parents=True, exist_ok=True)
        for name in names:
            fetch_file(url_for(name), args.dest / name, PINNED_SHA256[name], opener, log)
    except (ValueError, OSError, HTTPException) as error:
        print(f"fetch failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
