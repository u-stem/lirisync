"""Medium tests: the `separate` handler with the real ffmpeg and an identity-mask model.

Skipped when ffmpeg is not installed. The model is a fake onnx session that
returns the identity mask, so the real STFT, the demix, the decoder and the
encoder run, and the output should be the input again.
"""

import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.audio_io import FFMPEG_ENV, decode_audio, encode_wav, ffmpeg_executable
from lirisync_worker.protocol import ProtocolError
from lirisync_worker.separate import make_separate
from lirisync_worker.separation.model import MODEL_SHAPE, MaskModel
from lirisync_worker.separation.stft import SAMPLE_RATE
from lirisync_worker.server import Registry
from lirisync_worker.server import Session as ServerSession

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "protocol" / "worker.schema.json"
SECONDS = 3

Audio = npt.NDArray[np.float32]


class _Node:
    def __init__(self, name: str) -> None:
        self.name = name
        self.shape: Sequence[Any] = list(MODEL_SHAPE)


class _OnesSession:
    """Stands in for onnxruntime: the complex mask 1+0i, which keeps the input as it is."""

    def get_inputs(self) -> Sequence[_Node]:
        return [_Node("spec")]

    def get_outputs(self) -> Sequence[_Node]:
        return [_Node("mask")]

    def run(
        self, output_names: Sequence[str] | None, input_feed: dict[str, npt.NDArray[np.float32]]
    ) -> Sequence[Any]:
        mask = np.zeros_like(input_feed["spec"])
        mask[:, 0::2] = 1.0  # the real planes of the layout (L.re, L.im, R.re, R.im)
        return [mask]


def _identity_model(path: Path) -> MaskModel:
    return MaskModel(path, session_factory=lambda _path, _providers: _OnesSession())


@pytest.fixture(autouse=True)
def _require_ffmpeg() -> None:
    if shutil.which(ffmpeg_executable()) is None:
        pytest.skip("ffmpeg is not installed")


@pytest.fixture
def sine_wav(tmp_path: Path) -> Path:
    path = tmp_path / "sine.wav"
    subprocess.run(
        [
            ffmpeg_executable(),
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate={SAMPLE_RATE}:duration={SECONDS}",
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def model_file(tmp_path: Path) -> Path:
    path = tmp_path / "identity.onnx"
    path.write_bytes(b"not read by the fake session")
    return path


def _call(params: Mapping[str, object]) -> dict[str, object]:
    handler = make_separate(model_loader=_identity_model)
    return handler(ServerSession(registry=Registry()), params)


def _params(source: Path, model: Path, output: Path) -> dict[str, object]:
    return {"input": str(source), "output": str(output), "model": str(model)}


def test_the_result_reports_the_decoded_length(
    sine_wav: Path, model_file: Path, tmp_path: Path
) -> None:
    result = _call(_params(sine_wav, model_file, tmp_path / "vocals.wav"))

    assert result == {"durationMs": 3000, "sampleRate": 44100, "channels": 2}


def test_the_result_validates_against_the_schema(
    sine_wav: Path, model_file: Path, tmp_path: Path
) -> None:
    result = _call(_params(sine_wav, model_file, tmp_path / "vocals.wav"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    wrapper = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/SeparateResult",
    }

    assert jsonschema.Draft202012Validator(wrapper).is_valid(result)


def test_the_output_decodes_to_the_input_length(
    sine_wav: Path, model_file: Path, tmp_path: Path
) -> None:
    output = tmp_path / "vocals.wav"
    _call(_params(sine_wav, model_file, output))

    assert decode_audio(output).shape == decode_audio(sine_wav).shape


def test_an_identity_mask_gives_back_the_input_values(
    sine_wav: Path, model_file: Path, tmp_path: Path
) -> None:
    output = tmp_path / "vocals.wav"
    _call(_params(sine_wav, model_file, output))

    # The model zeroes the DC bin of the (zero-padded) chunk, which moves the
    # samples by the chunk mean, about 0.0014 here for an amplitude of 0.088.
    np.testing.assert_allclose(decode_audio(output), decode_audio(sine_wav), atol=3e-3)


def test_the_sine_is_not_silent(sine_wav: Path) -> None:
    assert float(np.abs(decode_audio(sine_wav)).max()) > 0.05


def test_a_mono_input_is_widened_to_stereo(tmp_path: Path) -> None:
    mono = tmp_path / "mono.wav"
    subprocess.run(
        [
            ffmpeg_executable(),
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ac",
            "1",
            str(mono),
        ],
        check=True,
    )

    assert decode_audio(mono).shape[0] == 2


def test_an_input_that_is_not_audio_is_audio_unreadable(model_file: Path, tmp_path: Path) -> None:
    text = tmp_path / "notes.mp3"
    text.write_text("this is not audio")

    with pytest.raises(ProtocolError) as error:
        _call(_params(text, model_file, tmp_path / "vocals.wav"))

    assert error.value.code == "audio_unreadable"


def test_the_audio_unreadable_message_carries_ffmpegs_complaint(
    model_file: Path, tmp_path: Path
) -> None:
    text = tmp_path / "notes.mp3"
    text.write_text("this is not audio")

    with pytest.raises(ProtocolError) as error:
        _call(_params(text, model_file, tmp_path / "vocals.wav"))

    assert "notes.mp3" in error.value.message


def test_a_missing_input_is_audio_unreadable(model_file: Path, tmp_path: Path) -> None:
    with pytest.raises(ProtocolError) as error:
        _call(_params(tmp_path / "gone.mp3", model_file, tmp_path / "vocals.wav"))

    assert error.value.code == "audio_unreadable"


# An HLS playlist on disk whose only segment is a URL. ffmpeg opens the
# playlist (a file) and then tries the segment, which the protocol whitelist
# must refuse. Nothing listens on port 9, so a connection failure would also
# end as audio_unreadable; the message tells the two apart: ffmpeg names the
# whitelist it applied, `file` when `-protocol_whitelist file` is passed and its
# own default `file,crypto,data` when it is not.
PLAYLIST_WITH_URL_SEGMENT = (
    "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n"
    "#EXTINF:1.0,\nhttp://127.0.0.1:9/seg.ts\n#EXT-X-ENDLIST\n"
)


def test_a_playlist_that_points_at_a_url_is_refused_by_the_file_only_whitelist(
    model_file: Path, tmp_path: Path
) -> None:
    playlist = tmp_path / "list.m3u8"
    playlist.write_text(PLAYLIST_WITH_URL_SEGMENT)

    with pytest.raises(ProtocolError) as error:
        _call(_params(playlist, model_file, tmp_path / "vocals.wav"))

    assert "not on whitelist 'file'!" in error.value.message


def test_a_playlist_that_points_at_a_url_is_audio_unreadable(
    model_file: Path, tmp_path: Path
) -> None:
    playlist = tmp_path / "list.m3u8"
    playlist.write_text(PLAYLIST_WITH_URL_SEGMENT)

    with pytest.raises(ProtocolError) as error:
        _call(_params(playlist, model_file, tmp_path / "vocals.wav"))

    assert error.value.code == "audio_unreadable"


def test_a_failed_run_leaves_no_output_file(model_file: Path, tmp_path: Path) -> None:
    with pytest.raises(ProtocolError):
        _call(_params(tmp_path / "gone.mp3", model_file, tmp_path / "vocals.wav"))

    assert sorted(p.name for p in tmp_path.iterdir()) == ["identity.onnx"]


def test_a_missing_ffmpeg_is_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch, sine_wav: Path, model_file: Path, tmp_path: Path
) -> None:
    monkeypatch.setenv(FFMPEG_ENV, str(tmp_path / "no-such-ffmpeg"))

    with pytest.raises(ProtocolError) as error:
        _call(_params(sine_wav, model_file, tmp_path / "vocals.wav"))

    assert error.value.code == "ffmpeg_missing"


def test_encoding_fails_cleanly_when_the_destination_cannot_be_written(tmp_path: Path) -> None:
    with pytest.raises(ProtocolError) as error:
        encode_wav(np.zeros((2, 100), dtype=np.float32), tmp_path / "missing-dir" / "out.wav")

    assert error.value.code == "internal"
