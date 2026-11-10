"""Download the character CTC model and its vocabulary for the Medium test.

Nothing here is shipped: the model is fetched into a local directory that the
test reads through ``LIRISYNC_ALIGNER_DIR``. Every file comes from a pinned
revision and is checked against a pinned SHA-256 before it is moved into place
(see `fetch_common.py`).

    uv --directory workers/align run python tools/fetch_aligner_model.py --dest DIR
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from fetch_common import Opener, fetch_all, open_url

REPOSITORY = "parseh/aligner-ja"
REVISION = "66eb48c224294f16a5aae3500964b756d9d23354"

PINNED_SHA256 = {
    "model.int8.onnx": "90b0e01385f90809f7818ffcc14d7ba18070b63e58af0aa64cc86cb3e703a24c",
    "vocab.json": "223300c979885b08b6a44f18b6b76cae49099c6de1a0bc2d5694a32827b3a7ab",
    "meta.json": "6e4c288df8d20dcc6c015452b3a193b61b328a38f068b40fdcd175a70b775199",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "NOTICE": "350699e5b7964e11ca27a9cf9f79ba830e9263f9f4929715212d4c57a198261f",
}
DEFAULT_FILES = tuple(PINNED_SHA256)


def url_for(name: str) -> str:
    return f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"


def select_files(names: Sequence[str] | None) -> list[str]:
    """The files to fetch: `names` if given, else all of them, each once."""
    chosen = list(dict.fromkeys(DEFAULT_FILES if names is None else names))
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
        help=f"files to fetch (default: all); known: {', '.join(PINNED_SHA256)}",
    )
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        print(message, file=sys.stderr)

    try:
        names = select_files(args.files)
    except ValueError as error:
        log(f"fetch failed: {error}")
        return 1
    urls = {name: url_for(name) for name in names}
    return fetch_all(urls, PINNED_SHA256, args.dest, opener, log)


if __name__ == "__main__":
    sys.exit(main())
