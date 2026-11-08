"""Process entry point: ``python -m lirisync_worker`` / ``lirisync-worker``."""

import io
import os
import subprocess
import sys

# Importing the protocol module is safe (stdlib + pydantic); anything heavier
# must be imported only after ``redirect_stdout`` has run inside ``main``.
from lirisync_worker.protocol import redirect_stdout

TEST_NOISE_ENV = "LIRISYNC_WORKER_TEST_NOISE"


def _emit_test_noise() -> None:
    """Test-only: write to stdout the way a noisy library would.

    Enabled solely by ``LIRISYNC_WORKER_TEST_NOISE=1``. It lets the test suite
    prove that stray output, including a child process's, ends up on stderr
    instead of the protocol channel.
    """
    print("noise-print")
    os.write(1, b"noise-fd1\n")
    # No stdout argument: the child inherits whatever the process stdout is now.
    subprocess.run([sys.executable, "-c", "print('noise-child')"], check=True)


def main() -> int:
    channel = redirect_stdout()
    if os.environ.get(TEST_NOISE_ENV) == "1":
        _emit_test_noise()

    from lirisync_worker.server import Server  # noqa: PLC0415 - must follow the redirect

    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="\n")
    return Server().serve(stdin, channel)


if __name__ == "__main__":
    sys.exit(main())
