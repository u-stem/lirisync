import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lirisync_transcribe.cli import Options, Transcriber, main, parse_args


@dataclass(frozen=True)
class FakeWord:
    start: float
    end: float
    word: str


@dataclass(frozen=True)
class FakeSegment:
    words: list[FakeWord] | None


@dataclass(frozen=True)
class FakeCtranslateModel:
    device: str = "cuda"
    compute_type: str = "float16"


@dataclass
class FakeModel:
    segments: list[FakeSegment]
    model: FakeCtranslateModel = field(default_factory=FakeCtranslateModel)
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def transcribe(self, audio: str, **kwargs: object) -> tuple[Iterable[FakeSegment], object]:
        self.calls.append((audio, kwargs))
        return iter(self.segments), None


@dataclass
class Loader:
    model: FakeModel
    loaded: list[Options] = field(default_factory=list)

    def __call__(self, options: Options) -> Transcriber:
        self.loaded.append(options)
        return self.model


SEGMENTS = [
    FakeSegment([FakeWord(0.0, 0.5, " 風が"), FakeWord(0.5, 1.0, "吹く")]),
    FakeSegment(None),
    FakeSegment([FakeWord(2.0, 2.5, " line")]),
]


BACKWARDS = [FakeSegment([FakeWord(2.0, 2.5, "x"), FakeWord(1.0, 1.5, "y")])]
# Meta values that are settings, not library versions.
SETTING_KEYS = {"model", "device", "computeType", "language", "audio"}


def make_song(songs: Path, slug: str, audio: str | None = "vocals.wav") -> Path:
    song = songs / slug
    (song / "audio").mkdir(parents=True)
    if audio is not None:
        (song / "audio" / audio).write_bytes(b"")
    return song


def run(
    songs: Path,
    *extra: str,
    segments: list[FakeSegment] | None = None,
) -> tuple[int, Loader]:
    loader = Loader(FakeModel(SEGMENTS if segments is None else segments))
    argv = ["--songs-dir", str(songs), "--model", "tiny", "--name", "t1", *extra]
    return main(argv, load_model=loader), loader


def read_json(path: Path) -> object:
    return json.loads(path.read_text("utf-8"))


def test_parse_args_defaults_the_songs_dir_next_to_the_project() -> None:
    assert parse_args(["--model", "m", "--name", "n"]).songs_dir == Path("../songs")


def test_parse_args_defaults() -> None:
    options = parse_args(["--model", "m", "--name", "n"])

    assert (options.audio, options.device, options.compute_type, options.beam_size) == (
        "vocals",
        "auto",
        "default",
        5,
    )


def test_parse_args_leaves_vad_and_overwrite_off_by_default() -> None:
    options = parse_args(["--model", "m", "--name", "n"])

    assert (options.vad, options.overwrite) == (False, False)


def test_parse_args_leaves_skip_existing_off_by_default() -> None:
    assert parse_args(["--model", "m", "--name", "n"]).skip_existing is False


def test_parse_args_accepts_skip_existing() -> None:
    assert parse_args(["--model", "m", "--name", "n", "--skip-existing"]).skip_existing is True


def test_parse_args_rejects_skip_existing_with_overwrite() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--model", "m", "--name", "n", "--skip-existing", "--overwrite"])


@pytest.mark.parametrize("beam_size", ["0", "-1", "1.5", "many", ""])
def test_parse_args_rejects_a_beam_size_that_is_not_a_positive_integer(beam_size: str) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--model", "m", "--name", "n", "--beam-size", beam_size])


def test_parse_args_accepts_a_beam_size_of_one() -> None:
    assert parse_args(["--model", "m", "--name", "n", "--beam-size", "1"]).beam_size == 1


def test_parse_args_collects_repeated_song_filters() -> None:
    options = parse_args(["--model", "m", "--name", "n", "--song", "a", "--song", "b"])

    assert options.songs == ["a", "b"]


@pytest.mark.parametrize("missing", ["--model", "--name"])
def test_parse_args_requires_model_and_name(missing: str) -> None:
    argv = [a for pair in (("--model", "m"), ("--name", "n")) if pair[0] != missing for a in pair]

    with pytest.raises(SystemExit):
        parse_args(argv)


def test_main_returns_zero_on_success(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    status, _ = run(tmp_path)

    assert status == 0


def test_main_writes_the_words_of_all_segments_in_order(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    run(tmp_path)

    assert read_json(tmp_path / "a" / "asr" / "t1.json") == {
        "words": [
            {"startMs": 0, "endMs": 500, "text": " 風が"},
            {"startMs": 500, "endMs": 1000, "text": "吹く"},
            {"startMs": 2000, "endMs": 2500, "text": " line"},
        ],
    }


def test_main_transcribes_japanese_with_word_timestamps(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    _, loader = run(tmp_path)

    assert loader.model.calls == [
        (
            str(tmp_path / "a" / "audio" / "vocals.wav"),
            {"language": "ja", "word_timestamps": True, "vad_filter": False, "beam_size": 5},
        ),
    ]


def test_main_turns_vad_on_with_the_flag(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    _, loader = run(tmp_path, "--vad", "--beam-size", "1")

    assert loader.model.calls[0][1]["vad_filter"] is True


def test_main_loads_the_model_once_for_all_songs(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    make_song(tmp_path, "b")

    _, loader = run(tmp_path)

    assert len(loader.loaded) == 1


def test_main_writes_every_song(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    make_song(tmp_path, "b")

    run(tmp_path)

    assert (tmp_path / "b" / "asr" / "t1.json").is_file()


def test_main_only_processes_the_selected_songs(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    make_song(tmp_path, "b")

    run(tmp_path, "--song", "b")

    assert not (tmp_path / "a" / "asr").exists()


def test_main_uses_another_audio_stem(tmp_path: Path) -> None:
    song = make_song(tmp_path, "a", audio="mix.flac")

    _, loader = run(tmp_path, "--audio", "mix")

    assert loader.model.calls[0][0] == str(song / "audio" / "mix.flac")


def test_main_records_the_settings_in_the_meta_file(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    run(tmp_path, "--device", "cpu", "--compute-type", "int8", "--beam-size", "3")

    meta = read_json(tmp_path / "a" / "asr" / "t1.meta.json")
    assert isinstance(meta, dict)
    assert {k: v for k, v in meta.items() if not isinstance(v, str) or k in SETTING_KEYS} == {
        "model": "tiny",
        "device": "cpu",
        "computeType": "int8",
        "beamSize": 3,
        "vad": False,
        "language": "ja",
        "audio": "vocals.wav",
        "clampedStarts": 0,
    }


def test_main_records_the_device_and_compute_type_actually_used(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    run(tmp_path, "--device", "auto")

    meta = read_json(tmp_path / "a" / "asr" / "t1.meta.json")
    assert isinstance(meta, dict)
    assert (meta["deviceUsed"], meta["computeTypeUsed"]) == ("cuda", "float16")


@pytest.mark.parametrize("key", ["fasterWhisper", "ctranslate2", "av"])
def test_main_records_library_versions_in_the_meta_file(tmp_path: Path, key: str) -> None:
    make_song(tmp_path, "a")

    run(tmp_path)

    meta = read_json(tmp_path / "a" / "asr" / "t1.meta.json")
    assert isinstance(meta, dict)
    assert isinstance(meta[key], str)


def test_main_records_the_clamped_starts_in_the_meta_file(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    run(tmp_path, segments=BACKWARDS)

    meta = read_json(tmp_path / "a" / "asr" / "t1.meta.json")
    assert isinstance(meta, dict)
    assert meta["clampedStarts"] == 1


def test_main_reports_progress_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")

    run(tmp_path)

    assert "a" in capsys.readouterr().err


def test_main_keeps_stdout_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_song(tmp_path, "a")

    run(tmp_path)

    assert capsys.readouterr().out == ""


def test_main_fails_on_an_unknown_song_before_loading_the_model(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    status, loader = run(tmp_path, "--song", "nope")

    assert (status, loader.loaded) == (1, [])


def test_main_names_the_unknown_song_in_the_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")

    run(tmp_path, "--song", "nope")

    assert capsys.readouterr().err.startswith('error: Unknown song "nope"')


def test_main_fails_on_missing_audio_before_loading_the_model(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    make_song(tmp_path, "b", audio=None)

    status, loader = run(tmp_path)

    assert (status, loader.loaded) == (1, [])


def test_main_writes_nothing_when_any_audio_is_missing(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    make_song(tmp_path, "b", audio=None)

    run(tmp_path)

    assert not (tmp_path / "a" / "asr").exists()


def test_main_fails_on_an_invalid_name_before_loading_the_model(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    loader = Loader(FakeModel(SEGMENTS))

    status = main(
        ["--songs-dir", str(tmp_path), "--model", "m", "--name", "../x"], load_model=loader
    )

    assert (status, loader.loaded) == (1, [])


def test_main_fails_on_an_existing_file_before_loading_the_model(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    run(tmp_path)

    status, loader = run(tmp_path)

    assert (status, loader.loaded) == (1, [])


def test_main_replaces_an_existing_file_with_overwrite(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    run(tmp_path)

    run(tmp_path, "--overwrite", segments=[])

    assert read_json(tmp_path / "a" / "asr" / "t1.json") == {"words": []}


def test_main_writes_a_song_whose_word_starts_go_backwards(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    status, _ = run(tmp_path, segments=BACKWARDS)

    assert (status, (tmp_path / "a" / "asr" / "t1.json").is_file()) == (0, True)


def test_main_warns_about_clamped_starts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")

    run(tmp_path, segments=BACKWARDS)

    assert "warning: a: 1 word starts clamped\n" in capsys.readouterr().err


def test_main_does_not_warn_when_no_start_is_clamped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")

    run(tmp_path)

    assert "clamped" not in capsys.readouterr().err


def test_main_warns_when_a_song_yields_no_words(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")

    run(tmp_path, segments=[])

    assert "warning: a: no words\n" in capsys.readouterr().err


def test_main_still_succeeds_when_a_song_yields_no_words(tmp_path: Path) -> None:
    make_song(tmp_path, "a")

    status, _ = run(tmp_path, segments=[])

    assert status == 0


def test_main_does_not_warn_about_words_when_there_are_some(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")

    run(tmp_path)

    assert "no words" not in capsys.readouterr().err


def test_main_names_the_song_when_its_words_are_unusable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")
    broken = [FakeSegment([FakeWord(0.0, 0.5, "x"), FakeWord(math.nan, 1.0, "y")])]

    run(tmp_path, segments=broken)

    assert 'error: Song "a": word 2' in capsys.readouterr().err


def test_main_skips_a_song_that_already_has_the_transcript(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    make_song(tmp_path, "b")
    run(tmp_path, "--song", "a")

    _, loader = run(tmp_path, "--skip-existing")

    assert [Path(call[0]).parent.parent.name for call in loader.model.calls] == ["b"]


def test_main_leaves_a_skipped_transcript_untouched(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    run(tmp_path)

    run(tmp_path, "--skip-existing", segments=[])

    assert read_json(tmp_path / "a" / "asr" / "t1.json") != {"words": []}


def test_main_does_not_load_the_model_when_every_song_is_skipped(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    run(tmp_path)

    status, loader = run(tmp_path, "--skip-existing")

    assert (status, loader.loaded) == (0, [])


def test_main_does_not_need_the_audio_of_a_skipped_song(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    run(tmp_path)
    (tmp_path / "a" / "audio" / "vocals.wav").unlink()

    status, _ = run(tmp_path, "--skip-existing")

    assert status == 0


def test_main_reports_a_skipped_song_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_song(tmp_path, "a")
    run(tmp_path)
    capsys.readouterr()

    run(tmp_path, "--skip-existing")

    assert "a: skipped" in capsys.readouterr().err


def test_main_rejects_a_bad_beam_size_before_loading_the_model(tmp_path: Path) -> None:
    make_song(tmp_path, "a")
    loader = Loader(FakeModel(SEGMENTS))
    argv = ["--songs-dir", str(tmp_path), "--model", "m", "--name", "n", "--beam-size", "0"]

    with pytest.raises(SystemExit):
        main(argv, load_model=loader)

    assert loader.loaded == []
