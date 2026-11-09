"""Finds the eval songs and their audio, and writes the ASR files."""

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

_ASR_NAME = re.compile(r"[A-Za-z0-9._-]+")
# `<name>.meta.json` sits next to `<name>.json`; a name ending in this would make
# its words file look like another transcript's meta file.
_META_SUFFIX = ".meta"


class SongSetError(Exception):
    """A problem with the song set or its files, reported to the user as is."""


def validate_name(name: str) -> None:
    """Checks an ASR name the way the eval runner does: it becomes a path segment."""
    if _ASR_NAME.fullmatch(name) is None or name in {".", ".."}:
        raise SongSetError(
            f'Invalid ASR name "{name}": use letters, digits, ".", "_" and "-"',
        )
    if name.endswith(_META_SUFFIX):
        raise SongSetError(f'Invalid ASR name "{name}": it must not end in "{_META_SUFFIX}"')


def list_songs(songs_dir: Path) -> list[Path]:
    """Song directories under ``songs_dir``, sorted. Dot directories belong to tools."""
    if not songs_dir.is_dir():
        raise SongSetError(f"The songs directory is not a directory: {songs_dir}")
    songs = sorted(
        (p for p in songs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name,
    )
    if not songs:
        raise SongSetError(f"No songs found under {songs_dir}")
    return songs


def find_audio(song_dir: Path, stem: str) -> Path:
    """The one file ``audio/<stem>.<ext>`` of a song. The stem is compared
    without case, as Windows file names are."""
    audio_dir = song_dir / "audio"
    candidates = (
        sorted(
            p for p in audio_dir.glob("*") if p.is_file() and p.stem.casefold() == stem.casefold()
        )
        if audio_dir.is_dir()
        else []
    )
    if not candidates:
        raise SongSetError(f'Song "{song_dir.name}" has no audio file audio/{stem}.*')
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise SongSetError(
            f'Song "{song_dir.name}" has more than one audio/{stem}.* file: {names}',
        )
    return candidates[0]


def asr_exists(song_dir: Path, name: str) -> bool:
    """Whether ``asr/<name>.json`` is there. It is written last, so it means "finished"."""
    validate_name(name)
    return (song_dir / "asr" / f"{name}.json").exists()


def ensure_writable(song_dir: Path, name: str, *, overwrite: bool) -> None:
    """Fails early, before a long transcription, if ``asr/<name>.json`` is in the way."""
    if asr_exists(song_dir, name) and not overwrite:
        raise SongSetError(
            f"{song_dir / 'asr' / f'{name}.json'} already exists; pass --overwrite to replace it"
        )


def write_asr(
    song_dir: Path,
    name: str,
    words: Sequence[Mapping[str, int | str]],
    meta: Mapping[str, str | int | bool],
    *,
    overwrite: bool,
) -> Path:
    """Writes ``asr/<name>.meta.json`` and then ``asr/<name>.json``; returns the latter.

    The words file goes last on purpose: if it exists, the song finished, which
    is what ``--skip-existing`` relies on to resume after a failure. For the same
    reason an overwrite deletes the old words file before the new meta is written,
    so a crash never leaves new meta beside old words.
    """
    ensure_writable(song_dir, name, overwrite=overwrite)
    asr_dir = song_dir / "asr"
    asr_dir.mkdir(parents=True, exist_ok=True)
    words_path = asr_dir / f"{name}.json"
    words_path.unlink(missing_ok=True)
    (asr_dir / f"{name}.meta.json").write_text(_dump(dict(meta)), encoding="utf-8", newline="\n")
    # Serialise before opening: opening for writing would create an empty file
    # that looks finished if serialising failed.
    text = _dump({"words": list(words)})
    try:
        with words_path.open("x", encoding="utf-8", newline="\n") as file:
            file.write(text)
    except FileExistsError:
        raise SongSetError(f"{words_path} already exists; pass --overwrite to replace it") from None
    return words_path


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
