"""Small tests for the parts of audio_io that need no ffmpeg."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from lirisync_worker.audio_io import (
    FFMPEG_ENV,
    FFMPEG_TIMEOUT_SECONDS,
    decode_audio,
    encode_wav,
    ffmpeg_executable,
    stderr_tail,
)
from lirisync_worker.protocol import ProtocolError


def test_ffmpeg_defaults_to_the_name_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FFMPEG_ENV, raising=False)

    assert ffmpeg_executable() == "ffmpeg"


def test_ffmpeg_executable_follows_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FFMPEG_ENV, "/opt/ffmpeg/bin/ffmpeg")

    assert ffmpeg_executable() == "/opt/ffmpeg/bin/ffmpeg"


def test_an_empty_environment_value_means_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FFMPEG_ENV, "")

    assert ffmpeg_executable() == "ffmpeg"


def test_stderr_tail_keeps_the_end_of_long_output() -> None:
    assert stderr_tail(b"a" * 1000 + b"END").endswith("END")


def test_stderr_tail_is_bounded() -> None:
    assert len(stderr_tail(b"a" * 5000)) == 500


def test_stderr_tail_strips_whitespace() -> None:
    assert stderr_tail(b"\n  error here \n\n") == "error here"


def test_stderr_tail_survives_bytes_that_are_not_utf8() -> None:
    assert stderr_tail(b"bad \xff byte").startswith("bad")


def test_decoding_without_ffmpeg_is_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FFMPEG_ENV, str(tmp_path / "no-such-ffmpeg"))

    with pytest.raises(ProtocolError) as error:
        decode_audio(tmp_path / "song.mp3")

    assert error.value.code == "ffmpeg_missing"


def test_encoding_without_ffmpeg_is_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FFMPEG_ENV, str(tmp_path / "no-such-ffmpeg"))

    with pytest.raises(ProtocolError) as error:
        encode_wav(np.zeros((2, 10), dtype=np.float32), tmp_path / "out.wav")

    assert error.value.code == "ffmpeg_missing"


def test_the_ffmpeg_missing_message_names_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FFMPEG_ENV, str(tmp_path / "no-such-ffmpeg"))

    with pytest.raises(ProtocolError) as error:
        decode_audio(tmp_path / "song.mp3")

    assert FFMPEG_ENV in error.value.message


ONE_FRAME = np.zeros(2, dtype="<f4").tobytes()


class _FakeFfmpeg:
    """Replaces `subprocess.run` inside audio_io with a canned ffmpeg outcome."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: bytes, stderr: bytes
    ) -> None:
        self.argv: list[str] = []
        self.kwargs: dict[str, object] = {}
        self._outcome = (returncode, stdout, stderr)
        monkeypatch.setattr("lirisync_worker.audio_io.subprocess.run", self._run)

    def _run(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        self.argv = argv
        self.kwargs = kwargs
        returncode, stdout, stderr = self._outcome
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def _fake(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int = 0,
    stdout: bytes = ONE_FRAME,
    stderr: bytes = b"",
) -> _FakeFfmpeg:
    return _FakeFfmpeg(monkeypatch, returncode, stdout, stderr)


def _decode_code(tmp_path: Path) -> str:
    with pytest.raises(ProtocolError) as error:
        decode_audio(tmp_path / "song.mp3")
    return error.value.code


def test_decoding_restricts_ffmpeg_to_the_file_protocol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake(monkeypatch)
    decode_audio(tmp_path / "song.mp3")
    i = fake.argv.index("-protocol_whitelist")

    assert fake.argv[i : i + 2] == ["-protocol_whitelist", "file"]


def test_decoding_sets_the_whitelist_before_the_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake(monkeypatch)
    decode_audio(tmp_path / "song.mp3")

    assert fake.argv.index("-protocol_whitelist") < fake.argv.index("-i")


def test_a_clean_decode_with_stderr_output_keeps_the_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake(monkeypatch, stderr=b"Header missing")

    assert decode_audio(tmp_path / "song.mp3").shape == (2, 1)


def test_a_decode_that_warned_logs_the_stderr_tail_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake(monkeypatch, stderr=b"\nHeader missing\n")
    decode_audio(tmp_path / "song.mp3")

    assert "Header missing" in capsys.readouterr().err


def test_a_decode_that_warned_writes_nothing_to_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake(monkeypatch, stderr=b"Header missing")
    decode_audio(tmp_path / "song.mp3")

    assert capsys.readouterr().out == ""


def test_a_quiet_decode_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake(monkeypatch)
    decode_audio(tmp_path / "song.mp3")

    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("returncode", [-9, -11, 126, 127])
def test_a_killed_or_unrunnable_ffmpeg_is_internal_on_decode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, returncode: int
) -> None:
    _fake(monkeypatch, returncode=returncode, stdout=b"")

    assert _decode_code(tmp_path) == "internal"


def test_the_internal_decode_message_names_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake(monkeypatch, returncode=-9, stdout=b"", stderr=b"Killed")
    with pytest.raises(ProtocolError) as error:
        decode_audio(tmp_path / "song.mp3")

    assert "ffmpeg" in error.value.message


@pytest.mark.parametrize("returncode", [1, 2, 183, 255])
def test_other_failing_exit_codes_are_audio_unreadable_on_decode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, returncode: int
) -> None:
    _fake(monkeypatch, returncode=returncode, stdout=b"", stderr=b"Invalid data")

    assert _decode_code(tmp_path) == "audio_unreadable"


@pytest.mark.parametrize("returncode", [-9, 1, 126, 127])
def test_a_failing_encode_is_internal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, returncode: int
) -> None:
    _fake(monkeypatch, returncode=returncode, stdout=b"")
    with pytest.raises(ProtocolError) as error:
        encode_wav(np.zeros((2, 10), dtype=np.float32), tmp_path / "out.wav")

    assert error.value.code == "internal"


@pytest.mark.parametrize("returncode", [-9, 127])
def test_the_internal_encode_message_names_ffmpeg_for_a_killed_or_unrunnable_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, returncode: int
) -> None:
    _fake(monkeypatch, returncode=returncode, stdout=b"")
    with pytest.raises(ProtocolError) as error:
        encode_wav(np.zeros((2, 10), dtype=np.float32), tmp_path / "out.wav")

    assert "ffmpeg was killed or could not run" in error.value.message


def _hang(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(argv, float(str(kwargs["timeout"])))

    monkeypatch.setattr("lirisync_worker.audio_io.subprocess.run", run)


def test_decoding_gives_ffmpeg_a_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _fake(monkeypatch)
    decode_audio(tmp_path / "song.mp3")

    assert fake.kwargs["timeout"] == FFMPEG_TIMEOUT_SECONDS


def test_encoding_gives_ffmpeg_a_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _fake(monkeypatch, stdout=b"")
    encode_wav(np.zeros((2, 10), dtype=np.float32), tmp_path / "out.wav")

    assert fake.kwargs["timeout"] == FFMPEG_TIMEOUT_SECONDS


def test_the_timeout_is_ten_minutes() -> None:
    assert FFMPEG_TIMEOUT_SECONDS == 600


def test_a_decode_that_times_out_is_internal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _hang(monkeypatch)

    assert _decode_code(tmp_path) == "internal"


def test_the_decode_timeout_message_names_ffmpeg_and_the_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _hang(monkeypatch)
    with pytest.raises(ProtocolError) as error:
        decode_audio(tmp_path / "song.mp3")

    assert "ffmpeg did not finish within 600 s" in error.value.message


def test_an_encode_that_times_out_is_internal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _hang(monkeypatch)
    with pytest.raises(ProtocolError) as error:
        encode_wav(np.zeros((2, 10), dtype=np.float32), tmp_path / "out.wav")

    assert (error.value.code, "ffmpeg did not finish" in error.value.message) == ("internal", True)
