"""Download the separation model and its reference files for the Medium test.

Nothing here is shipped: the model is fetched into a local directory that the
reference test reads through ``LIRISYNC_SEPARATOR_DIR``. Every file comes from a
pinned revision and is checked against a pinned SHA-256 before it is moved into
place, so a truncated or changed download never ends up next to good files.

    uv --directory workers/align run python tools/fetch_separator_model.py --dest DIR
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from fetch_common import Opener, fetch_all, open_url

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


def url_for(name: str) -> str:
    return f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"


def select_files(names: Sequence[str] | None, *, with_fp16: bool) -> list[str]:
    """The files to fetch: `names` if given, else the defaults; plus fp16 on request."""
    extra = FP16_FILES if with_fp16 else ()
    # Keep the order but fetch (and hash) each file once.
    chosen = list(dict.fromkeys([*DEFAULT_FILES, *extra] if names is None else [*names, *extra]))
    unknown = [name for name in chosen if name not in PINNED_SHA256]
    if unknown:
        raise ValueError(f"unknown file(s) {unknown}; known: {sorted(PINNED_SHA256)}")
    return chosen


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
    except ValueError as error:
        log(f"fetch failed: {error}")
        return 1
    urls = {name: url_for(name) for name in names}
    return fetch_all(urls, PINNED_SHA256, args.dest, opener, log)


if __name__ == "__main__":
    sys.exit(main())
