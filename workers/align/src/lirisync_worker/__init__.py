"""Lirisync alignment worker.

Keep this module free of heavy imports: it is loaded before the stdout
redirect in ``__main__`` has run.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lirisync-worker")
except PackageNotFoundError:  # pragma: no cover - only when run from a bare source tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
