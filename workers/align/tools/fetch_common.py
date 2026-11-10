"""Shared parts of the model fetch tools: a verified, atomic file download.

Every file is checked against a pinned SHA-256 before it is moved into place, so
a truncated or changed download never ends up next to good files. The tools that
pin a revision and a file list (`fetch_separator_model.py`,
`fetch_aligner_model.py`) build on `fetch_file`.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from http.client import HTTPException
from pathlib import Path
from typing import Protocol

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


def fetch_all(
    urls: Mapping[str, str],
    pinned_sha256: Mapping[str, str],
    dest: Path,
    opener: Opener,
    log: Log,
) -> int:
    """Fetch each file of `urls` (name to URL) into `dest`; 0 on success, 1 on failure.

    A failure is logged as `fetch failed: ...` and stops the run; files already
    fetched stay in place.
    """
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for name, url in urls.items():
            fetch_file(url, dest / name, pinned_sha256[name], opener, log)
    except (ValueError, OSError, HTTPException) as error:
        log(f"fetch failed: {error}")
        return 1
    return 0
