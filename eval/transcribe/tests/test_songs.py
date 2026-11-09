import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from lirisync_transcribe.songs import (
    SongSetError,
    asr_exists,
    ensure_writable,
    find_audio,
    list_songs,
    validate_name,
    write_asr,
)

WORDS: list[dict[str, int | str]] = [{"startMs": 0, "endMs": 500, "text": "風が"}]
META: dict[str, str | int | bool] = {"model": "tiny", "beamSize": 5, "vad": False}


@pytest.mark.parametrize("name", ["large-v3", "tiny.en", "run_1", "A.B-c_9"])
def test_validate_name_accepts_path_safe_names(name: str) -> None:
    validate_name(name)


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "a b", "日本語", "a..b/"])
def test_validate_name_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(SongSetError, match="Invalid ASR name"):
        validate_name(name)


def test_list_songs_returns_sorted_directories(tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()

    assert [p.name for p in list_songs(tmp_path)] == ["a", "b"]


def test_list_songs_skips_dot_directories_and_files(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / ".tool").mkdir()
    (tmp_path / "notes.txt").write_text("x")

    assert [p.name for p in list_songs(tmp_path)] == ["a"]


def test_list_songs_rejects_an_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(SongSetError, match="No songs"):
        list_songs(tmp_path)


def test_list_songs_rejects_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(SongSetError, match="not a directory"):
        list_songs(tmp_path / "missing")


def test_find_audio_returns_the_single_matching_file(tmp_path: Path) -> None:
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "vocals.wav").write_bytes(b"")
    (tmp_path / "audio" / "mix.wav").write_bytes(b"")

    assert find_audio(tmp_path, "vocals") == tmp_path / "audio" / "vocals.wav"


def test_find_audio_does_not_match_a_longer_stem(tmp_path: Path) -> None:
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "vocals_old.wav").write_bytes(b"")

    with pytest.raises(SongSetError, match="no audio"):
        find_audio(tmp_path, "vocals")


def test_find_audio_names_the_song_when_there_is_none(tmp_path: Path) -> None:
    song = tmp_path / "my-song"
    (song / "audio").mkdir(parents=True)

    with pytest.raises(SongSetError, match="my-song"):
        find_audio(song, "vocals")


def test_find_audio_rejects_several_candidates(tmp_path: Path) -> None:
    song = tmp_path / "my-song"
    (song / "audio").mkdir(parents=True)
    (song / "audio" / "vocals.wav").write_bytes(b"")
    (song / "audio" / "vocals.flac").write_bytes(b"")

    with pytest.raises(SongSetError, match="more than one"):
        find_audio(song, "vocals")


def test_find_audio_rejects_a_missing_audio_directory(tmp_path: Path) -> None:
    with pytest.raises(SongSetError, match="no audio"):
        find_audio(tmp_path, "vocals")


def test_write_asr_writes_the_words_file_in_the_eval_format(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    assert json.loads((tmp_path / "asr" / "tiny.json").read_text("utf-8")) == {"words": WORDS}


def test_write_asr_keeps_non_ascii_text_readable(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    assert "風が" in (tmp_path / "asr" / "tiny.json").read_text("utf-8")


def test_write_asr_ends_the_words_file_with_a_newline(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    assert (tmp_path / "asr" / "tiny.json").read_text("utf-8").endswith("}\n")


def test_write_asr_writes_the_meta_file(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    assert json.loads((tmp_path / "asr" / "tiny.meta.json").read_text("utf-8")) == META


def test_write_asr_returns_the_words_file_path(tmp_path: Path) -> None:
    path = write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    assert path == tmp_path / "asr" / "tiny.json"


def test_write_asr_refuses_to_overwrite_without_the_flag(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    with pytest.raises(SongSetError, match="already exists"):
        write_asr(tmp_path, "tiny", [], META, overwrite=False)


def test_write_asr_keeps_the_old_file_when_it_refuses(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)
    with pytest.raises(SongSetError):
        write_asr(tmp_path, "tiny", [], META, overwrite=False)

    assert json.loads((tmp_path / "asr" / "tiny.json").read_text("utf-8")) == {"words": WORDS}


def test_write_asr_overwrites_with_the_flag(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)
    write_asr(tmp_path, "tiny", [], META, overwrite=True)

    assert json.loads((tmp_path / "asr" / "tiny.json").read_text("utf-8")) == {"words": []}


def test_write_asr_rejects_an_unsafe_name(tmp_path: Path) -> None:
    with pytest.raises(SongSetError, match="Invalid ASR name"):
        write_asr(tmp_path, "../x", WORDS, META, overwrite=False)


def test_ensure_writable_passes_for_a_new_name(tmp_path: Path) -> None:
    ensure_writable(tmp_path, "tiny", overwrite=False)


def test_ensure_writable_rejects_an_existing_file_without_the_flag(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    with pytest.raises(SongSetError, match="already exists"):
        ensure_writable(tmp_path, "tiny", overwrite=False)


def test_ensure_writable_accepts_an_existing_file_with_the_flag(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    ensure_writable(tmp_path, "tiny", overwrite=True)


@pytest.mark.parametrize("name", ["x.meta", "large-v3.meta"])
def test_validate_name_rejects_the_side_file_suffix(name: str) -> None:
    with pytest.raises(SongSetError, match=r"\.meta"):
        validate_name(name)


def test_validate_name_accepts_meta_inside_a_name() -> None:
    validate_name("meta-run")


def test_asr_exists_is_false_for_a_new_name(tmp_path: Path) -> None:
    assert asr_exists(tmp_path, "tiny") is False


def test_asr_exists_is_true_once_the_words_file_is_written(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)

    assert asr_exists(tmp_path, "tiny") is True


def test_write_asr_keeps_the_old_meta_file_when_it_refuses(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)
    with pytest.raises(SongSetError):
        write_asr(tmp_path, "tiny", [], {"model": "other"}, overwrite=False)

    assert json.loads((tmp_path / "asr" / "tiny.meta.json").read_text("utf-8")) == META


class UnwritableWord(Mapping[str, int | str]):
    """A word record that json cannot serialise, to fail the words write."""

    def __getitem__(self, key: str) -> int | str:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def test_write_asr_writes_the_meta_file_before_the_words_file(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        write_asr(tmp_path, "tiny", [UnwritableWord()], META, overwrite=False)

    assert (tmp_path / "asr" / "tiny.meta.json").is_file()


def test_write_asr_leaves_no_words_file_when_the_words_write_fails(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        write_asr(tmp_path, "tiny", [UnwritableWord()], META, overwrite=False)

    assert not (tmp_path / "asr" / "tiny.json").exists()


def test_write_asr_removes_the_old_words_file_when_an_overwrite_fails(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)
    with pytest.raises(TypeError):
        write_asr(tmp_path, "tiny", [UnwritableWord()], META, overwrite=True)

    assert not (tmp_path / "asr" / "tiny.json").exists()


def test_write_asr_replaces_the_meta_file_on_overwrite(tmp_path: Path) -> None:
    write_asr(tmp_path, "tiny", WORDS, META, overwrite=False)
    write_asr(tmp_path, "tiny", WORDS, {"model": "other"}, overwrite=True)

    assert json.loads((tmp_path / "asr" / "tiny.meta.json").read_text("utf-8")) == {
        "model": "other"
    }
