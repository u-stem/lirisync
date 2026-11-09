"""Small tests for the `separate` handler with fake decoder, encoder and model."""

import gc
import os
import re
import weakref
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.protocol import ProtocolError
from lirisync_worker.separate import Decoder, Encoder, ModelLoader, make_separate
from lirisync_worker.separation.stft import CHUNK, SAMPLE_RATE
from lirisync_worker.server import Registry, Session

Audio = npt.NDArray[np.float32]
Progress = tuple[str, float, int | None]

ONE_CHUNK = CHUNK  # two process calls
LONG = 2 * CHUNK  # six process calls


def _audio(samples: int) -> Audio:
    return np.full((2, samples), 0.25, dtype=np.float32)


def _identity(chunk: Audio) -> Audio:
    return chunk


def _ticking(step: float = 2.0) -> Callable[[], float]:
    """A clock that advances by `step` seconds on every reading."""
    readings: Iterator[float] = iter(float(k) * step for k in range(1000))
    return lambda: next(readings)


class _Run:
    def __init__(self, tmp_path: Path, samples: int = ONE_CHUNK) -> None:
        self.tmp_path = tmp_path
        self.samples = samples
        self.progress: list[Progress] = []
        self.decoded: list[Path] = []
        self.written: list[tuple[Path, Audio]] = []
        self.loaded: list[Path] = []
        self.model = tmp_path / "sep.onnx"
        self.model.write_bytes(b"x")
        self.input = tmp_path / "song.mp3"
        self.output = tmp_path / "vocals.wav"

    def decoder(self, path: Path) -> Audio:
        self.decoded.append(path)
        return _audio(self.samples)

    def encoder(self, audio: Audio, path: Path) -> None:
        path.write_bytes(b"wav")
        self.written.append((path, audio))

    def loader(self, path: Path) -> Callable[[Audio], Audio]:
        self.loaded.append(path)
        return _identity

    def params(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "input": str(self.input),
            "output": str(self.output),
            "model": str(self.model),
        }
        return {**base, **overrides}

    def session(self) -> Session:
        session = Session(registry=Registry())
        session.progress_sink = lambda stage, ratio, eta: self.progress.append((stage, ratio, eta))
        return session

    def handler(
        self,
        *,
        decoder: Decoder | None = None,
        encoder: Encoder | None = None,
        model_loader: ModelLoader | None = None,
        clock: Callable[[], float] | None = None,
    ) -> Callable[[Session, Mapping[str, object]], dict[str, object]]:
        return make_separate(
            decoder=decoder or self.decoder,
            encoder=encoder or self.encoder,
            model_loader=model_loader or self.loader,
            clock=clock or _ticking(),
        )

    def call(self, **overrides: object) -> dict[str, object]:
        return self.handler()(self.session(), self.params(**overrides))


def _code(
    run: _Run,
    handler: Callable[[Session, Mapping[str, object]], dict[str, object]] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> str:
    call = handler or run.handler()
    with pytest.raises(ProtocolError) as error:
        call(run.session(), run.params(**(overrides or {})))
    return error.value.code


# --- result -----------------------------------------------------------------


def test_result_reports_the_duration_in_whole_milliseconds(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=3 * SAMPLE_RATE + 100)

    assert run.call()["durationMs"] == 3002


def test_result_duration_rounds_down(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=44)  # 0.9977 ms

    assert run.call()["durationMs"] == 0


def test_result_reports_the_sample_rate(tmp_path: Path) -> None:
    assert _Run(tmp_path).call()["sampleRate"] == 44100


def test_result_reports_stereo(tmp_path: Path) -> None:
    assert _Run(tmp_path).call()["channels"] == 2


def test_result_has_exactly_the_schema_keys(tmp_path: Path) -> None:
    assert set(_Run(tmp_path).call()) == {"durationMs", "sampleRate", "channels"}


def test_the_decoder_receives_the_resolved_input_path(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.decoded == [run.input.resolve()]


def test_the_output_is_the_demixed_audio_with_the_input_length(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=1000)
    run.call()

    assert run.written[0][1].shape == (2, 1000)


def test_the_output_file_exists_after_the_call(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.output.read_bytes() == b"wav"


# --- progress ---------------------------------------------------------------


def test_progress_starts_at_ratio_zero_without_an_estimate(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.progress[0] == ("separate", 0.0, None)


def test_progress_ends_at_ratio_one(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=LONG)
    run.call()

    assert run.progress[-1][1] == 1.0


def test_progress_has_one_report_per_chunk_plus_the_start(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=LONG)
    run.call()

    assert len(run.progress) == 7


def test_progress_ratios_increase_strictly(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=LONG)
    run.call()
    ratios = [ratio for _, ratio, _ in run.progress]

    assert ratios == sorted(set(ratios))


def test_progress_ratio_is_chunks_done_over_total(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=LONG)
    run.call()

    assert [ratio for _, ratio, _ in run.progress][1:3] == [1 / 6, 2 / 6]


def test_progress_eta_is_mean_chunk_time_times_chunks_left(tmp_path: Path) -> None:
    # The clock reads 0 at the start and 2 s more at each chunk: 2 s per chunk.
    run = _Run(tmp_path, samples=LONG)
    run.call()

    assert [eta for _, _, eta in run.progress] == [None, 10000, 8000, 6000, 4000, 2000, 0]


def test_progress_eta_is_an_integer(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=LONG)
    run.handler(clock=_ticking(0.3333))(run.session(), run.params())

    assert all(isinstance(eta, int) for _, _, eta in run.progress[1:])


def test_progress_uses_the_separate_stage(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert {stage for stage, _, _ in run.progress} == {"separate"}


# --- parameters -------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"input": 1},
        {"output": None},
        {"model": ["a"]},
        {"input": ""},
        {"output": ""},
        {"model": ""},
        {"extra": "x"},
    ],
    ids=str,
)
def test_bad_param_values_are_invalid_requests(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    assert _code(_Run(tmp_path), overrides=overrides) == "invalid_request"


@pytest.mark.parametrize("missing", ["input", "output", "model"])
def test_a_missing_param_is_an_invalid_request(tmp_path: Path, missing: str) -> None:
    run = _Run(tmp_path)
    params = {k: v for k, v in run.params().items() if k != missing}

    with pytest.raises(ProtocolError) as error:
        run.handler()(run.session(), params)

    assert error.value.code == "invalid_request"


def test_an_output_without_a_wav_extension_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)

    assert _code(run, overrides={"output": str(tmp_path / "vocals.flac")}) == "invalid_request"


def test_a_wav_extension_in_capitals_is_accepted(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call(output=str(tmp_path / "VOCALS.WAV"))

    assert (tmp_path / "VOCALS.WAV").exists()


def test_an_output_whose_parent_is_missing_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)

    assert (
        _code(run, overrides={"output": str(tmp_path / "nope" / "vocals.wav")}) == "invalid_request"
    )


def test_an_output_that_is_a_directory_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    (tmp_path / "dir.wav").mkdir()

    assert _code(run, overrides={"output": str(tmp_path / "dir.wav")}) == "invalid_request"


def test_an_output_equal_to_the_input_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.input = tmp_path / "song.wav"

    assert _code(run, overrides={"output": str(run.input)}) == "invalid_request"


def test_invalid_params_do_not_decode_or_load_anything(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    _code(run, overrides={"output": "vocals.txt"})

    assert (run.decoded, run.loaded) == ([], [])


# --- errors -----------------------------------------------------------------


def test_a_missing_model_file_is_model_missing(tmp_path: Path) -> None:
    run = _Run(tmp_path)

    assert _code(run, overrides={"model": str(tmp_path / "gone.onnx")}) == "model_missing"


def test_the_missing_model_message_names_the_file(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    with pytest.raises(ProtocolError) as error:
        run.handler()(run.session(), run.params(model=str(tmp_path / "gone.onnx")))

    assert "gone.onnx" in error.value.message


def test_a_model_that_fails_to_load_is_model_missing(tmp_path: Path) -> None:
    def broken(_path: Path) -> Callable[[Audio], Audio]:
        raise ValueError("expected one input named 'spec'\nmore")

    run = _Run(tmp_path)

    assert _code(run, run.handler(model_loader=broken)) == "model_missing"


def _load_failure_message(tmp_path: Path) -> str:
    def broken(_path: Path) -> Callable[[Audio], Audio]:
        raise ValueError("expected one input named 'spec'\nmore")

    run = _Run(tmp_path)
    with pytest.raises(ProtocolError) as error:
        run.handler(model_loader=broken)(run.session(), run.params())
    return error.value.message


def test_the_load_failure_message_names_the_file(tmp_path: Path) -> None:
    assert "sep.onnx" in _load_failure_message(tmp_path)


def test_the_load_failure_message_gives_the_first_line_of_the_cause(tmp_path: Path) -> None:
    assert "expected one input named 'spec'" in _load_failure_message(tmp_path)


def test_the_load_failure_message_drops_later_lines_of_the_cause(tmp_path: Path) -> None:
    assert "more" not in _load_failure_message(tmp_path)


def test_a_decoder_error_passes_through_with_its_code(tmp_path: Path) -> None:
    def unreadable(_path: Path) -> Audio:
        raise ProtocolError("audio_unreadable", "ffmpeg could not decode song.mp3")

    run = _Run(tmp_path)

    assert _code(run, run.handler(decoder=unreadable)) == "audio_unreadable"


def test_ffmpeg_missing_from_the_decoder_passes_through(tmp_path: Path) -> None:
    def absent(_path: Path) -> Audio:
        raise ProtocolError("ffmpeg_missing", "cannot run ffmpeg")

    run = _Run(tmp_path)

    assert _code(run, run.handler(decoder=absent)) == "ffmpeg_missing"


def test_zero_decoded_samples_are_audio_unreadable(tmp_path: Path) -> None:
    run = _Run(tmp_path, samples=0)

    assert _code(run) == "audio_unreadable"


def test_a_model_failure_midway_is_not_swallowed(tmp_path: Path) -> None:
    def broken(_path: Path) -> Callable[[Audio], Audio]:
        def process(_chunk: Audio) -> Audio:
            raise RuntimeError("inference failed")

        return process

    run = _Run(tmp_path)

    with pytest.raises(RuntimeError):
        run.handler(model_loader=broken)(run.session(), run.params())


# --- atomic write -----------------------------------------------------------


def _failing_encoder(audio: Audio, path: Path) -> None:
    path.write_bytes(b"partial")
    raise ProtocolError("internal", "ffmpeg could not write")


def test_an_encoder_failure_leaves_no_output(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    _code(run, run.handler(encoder=_failing_encoder))

    assert not run.output.exists()


def test_an_encoder_failure_leaves_no_temporary_file(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    _code(run, run.handler(encoder=_failing_encoder))

    assert sorted(p.name for p in tmp_path.iterdir()) == ["sep.onnx"]


def test_an_encoder_failure_keeps_the_previous_output(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.output.write_bytes(b"previous")
    _code(run, run.handler(encoder=_failing_encoder))

    assert run.output.read_bytes() == b"previous"


def test_an_unexpected_encoder_exception_leaves_no_temporary_file(tmp_path: Path) -> None:
    def crash(_audio: Audio, path: Path) -> None:
        path.write_bytes(b"partial")
        raise RuntimeError("crash")

    run = _Run(tmp_path)
    with pytest.raises(RuntimeError):
        run.handler(encoder=crash)(run.session(), run.params())

    assert sorted(p.name for p in tmp_path.iterdir()) == ["sep.onnx"]


def test_the_encoder_writes_beside_the_output(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.written[0][0].parent == run.output.resolve().parent


def test_the_encoder_writes_under_another_name_than_the_output(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.written[0][0] != run.output.resolve()


def test_the_temporary_name_ends_in_wav_for_the_encoder(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.written[0][0].suffix == ".wav"


def test_a_successful_run_leaves_only_the_output(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert sorted(p.name for p in tmp_path.iterdir()) == ["sep.onnx", "vocals.wav"]


def test_an_existing_output_is_replaced(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.output.write_bytes(b"old")
    run.call()

    assert run.output.read_bytes() == b"wav"


# --- model cache ------------------------------------------------------------


def test_the_model_is_loaded_once_across_calls(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    handler = run.handler()
    handler(run.session(), run.params())
    handler(run.session(), run.params())

    assert len(run.loaded) == 1


def test_a_relative_path_to_the_same_model_hits_the_cache(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    handler = run.handler()
    handler(run.session(), run.params())
    handler(run.session(), run.params(model=str(tmp_path / "." / "sep.onnx")))

    assert len(run.loaded) == 1


def test_a_different_model_file_is_loaded_separately(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    other = tmp_path / "other.onnx"
    other.write_bytes(b"y")
    handler = run.handler()
    handler(run.session(), run.params())
    handler(run.session(), run.params(model=str(other)))

    assert len(run.loaded) == 2


def test_a_failed_load_is_not_cached(tmp_path: Path) -> None:
    attempts: list[Path] = []

    def flaky(path: Path) -> Callable[[Audio], Audio]:
        attempts.append(path)
        if len(attempts) == 1:
            raise ValueError("bad")
        return _identity

    run = _Run(tmp_path)
    handler = run.handler(model_loader=flaky)
    _code(run, handler)
    handler(run.session(), run.params())

    assert len(attempts) == 2


# --- path errors ------------------------------------------------------------


@pytest.mark.parametrize("field", ["input", "output", "model"])
@pytest.mark.parametrize("bad", ["a\x00b.wav", "\ud800.wav"], ids=["nul", "lone-surrogate"])
def test_unusable_path_text_is_an_invalid_request(tmp_path: Path, field: str, bad: str) -> None:
    run = _Run(tmp_path)

    assert _code(run, overrides={field: bad}) == "invalid_request"


# --- input kinds ------------------------------------------------------------


def test_an_input_that_is_a_directory_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.input.mkdir()

    assert _code(run) == "invalid_request"


def test_an_input_that_is_a_directory_is_never_decoded(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.input.mkdir()
    _code(run)

    assert run.decoded == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes need POSIX")
def test_an_input_that_is_a_fifo_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    os.mkfifo(run.input)

    assert _code(run) == "invalid_request"


def test_a_regular_input_file_is_accepted(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.input.write_bytes(b"audio")
    run.call()

    assert run.decoded == [run.input.resolve()]


# --- same file --------------------------------------------------------------


def test_an_output_that_is_a_hard_link_of_the_input_is_an_invalid_request(
    tmp_path: Path,
) -> None:
    run = _Run(tmp_path)
    run.input.write_bytes(b"audio")
    os.link(run.input, run.output)

    assert _code(run) == "invalid_request"


def test_a_hard_linked_output_is_left_untouched(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.input.write_bytes(b"audio")
    os.link(run.input, run.output)
    _code(run)

    assert run.input.read_bytes() == b"audio"


def test_an_output_that_differs_from_the_input_only_in_case_is_an_invalid_request(
    tmp_path: Path,
) -> None:
    run = _Run(tmp_path)
    run.input = tmp_path / "Song.wav"
    run.input.write_bytes(b"audio")
    if not (tmp_path / "song.wav").exists():
        pytest.skip("the file system is case-sensitive")

    assert _code(
        run, overrides={"input": str(run.input), "output": str(tmp_path / "song.wav")}
    ) == ("invalid_request")


# --- model cache keyed by file state ----------------------------------------


class _Marked:
    """A model that can be told apart and observed for garbage collection."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __call__(self, chunk: Audio) -> Audio:
        return chunk


def test_a_model_file_that_changed_is_loaded_again(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    handler = run.handler()
    handler(run.session(), run.params())
    run.model.write_bytes(b"a different, longer model file")
    handler(run.session(), run.params())

    assert len(run.loaded) == 2


def test_a_model_file_replaced_by_one_of_the_same_size_is_loaded_again(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    handler = run.handler()
    handler(run.session(), run.params())
    stat = run.model.stat()
    run.model.write_bytes(b"y")
    os.utime(run.model, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    handler(run.session(), run.params())

    assert len(run.loaded) == 2


def test_an_unchanged_model_file_is_not_loaded_again(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    handler = run.handler()
    handler(run.session(), run.params())
    handler(run.session(), run.params())

    assert len(run.loaded) == 1


def test_the_replaced_model_is_the_one_that_runs(tmp_path: Path) -> None:
    used: list[str] = []

    def loader(path: Path) -> Callable[[Audio], Audio]:
        label = path.read_bytes().decode()

        def process(chunk: Audio) -> Audio:
            used.append(label)
            return chunk

        return process

    run = _Run(tmp_path, samples=1000)
    handler = run.handler(model_loader=loader)
    run.model.write_bytes(b"old")
    handler(run.session(), run.params())
    run.model.write_bytes(b"newer")
    handler(run.session(), run.params())

    assert used[-1] == "newer"


def test_the_previous_model_of_a_path_is_released_when_the_file_changes(tmp_path: Path) -> None:
    created: list[weakref.ref[_Marked]] = []

    def loader(_path: Path) -> Callable[[Audio], Audio]:
        model = _Marked("m")
        created.append(weakref.ref(model))
        return model

    run = _Run(tmp_path, samples=1000)
    handler = run.handler(model_loader=loader)
    handler(run.session(), run.params())
    run.model.write_bytes(b"a different, longer model file")
    handler(run.session(), run.params())
    gc.collect()

    assert created[0]() is None


def test_a_model_file_that_vanished_after_loading_is_model_missing(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    handler = run.handler()
    handler(run.session(), run.params())
    run.model.unlink()

    assert _code(run, handler) == "model_missing"


# --- missing runtime --------------------------------------------------------


def test_an_import_error_while_loading_the_model_is_internal(tmp_path: Path) -> None:
    def no_runtime(_path: Path) -> Callable[[Audio], Audio]:
        raise ImportError("No module named 'onnxruntime'")

    run = _Run(tmp_path)

    assert _code(run, run.handler(model_loader=no_runtime)) == "internal"


def test_the_import_error_message_gives_the_cause(tmp_path: Path) -> None:
    def no_runtime(_path: Path) -> Callable[[Audio], Audio]:
        raise ImportError("No module named 'onnxruntime'")

    run = _Run(tmp_path)
    with pytest.raises(ProtocolError) as error:
        run.handler(model_loader=no_runtime)(run.session(), run.params())

    assert "onnxruntime" in error.value.message


# --- load order -------------------------------------------------------------


def test_the_model_is_not_loaded_when_decoding_fails(tmp_path: Path) -> None:
    def unreadable(_path: Path) -> Audio:
        raise ProtocolError("audio_unreadable", "bad")

    run = _Run(tmp_path)
    _code(run, run.handler(decoder=unreadable))

    assert run.loaded == []


# --- temporary file name ----------------------------------------------------


def test_a_long_output_name_does_not_overflow_the_temporary_name(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    long_output = tmp_path / ("x" * 240 + ".wav")
    run.call(output=str(long_output))

    assert long_output.exists()


def test_the_temporary_name_is_short_and_fixed_in_form(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call(output=str(tmp_path / ("x" * 100 + ".wav")))

    assert re.fullmatch(r"\.lirisync-[0-9a-f]{16}\.tmp\.wav", run.written[0][0].name) is not None
