"""Command line: transcribes each eval song with faster-whisper into ``asr/<name>.json``.

Evaluation only. faster-whisper pulls in PyAV (bundled FFmpeg) and, on a GPU,
NVIDIA's CUDA libraries; neither belongs in the distributed worker.
"""

import argparse
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Protocol

from lirisync_transcribe.songs import (
    SongSetError,
    asr_exists,
    ensure_writable,
    find_audio,
    list_songs,
    validate_name,
    write_asr,
)
from lirisync_transcribe.words import WordLike, asr_words

LANGUAGE = "ja"


class SegmentLike(Protocol):
    """The part of faster-whisper's ``Segment`` that this module reads."""

    @property
    def words(self) -> Sequence[WordLike] | None: ...


class CtranslateModel(Protocol):
    """The part of the loaded ctranslate2 model that goes into the meta file."""

    @property
    def device(self) -> str: ...

    @property
    def compute_type(self) -> str: ...


class Transcriber(Protocol):
    """The part of faster-whisper's ``WhisperModel`` that this module uses."""

    @property
    def model(self) -> CtranslateModel: ...

    def transcribe(
        self,
        audio: str,
        *,
        language: str,
        word_timestamps: bool,
        vad_filter: bool,
        beam_size: int,
    ) -> tuple[Iterable[SegmentLike], object]: ...


@dataclass(frozen=True)
class Options:
    songs_dir: Path
    model: str
    name: str
    songs: list[str]
    audio: str
    device: str
    compute_type: str
    beam_size: int
    vad: bool
    overwrite: bool
    skip_existing: bool


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{value} is not at least 1")
    return value


def parse_args(argv: Sequence[str] | None = None) -> Options:
    parser = argparse.ArgumentParser(
        prog="lirisync-transcribe",
        description="Transcribe each eval song with faster-whisper into asr/<name>.json.",
    )
    parser.add_argument(
        "--songs-dir",
        type=Path,
        default=Path("../songs"),
        help="Directory of songs. The default is relative to the working directory, which"
        " is eval/transcribe when run with `uv --directory eval/transcribe`.",
    )
    parser.add_argument(
        "--model", required=True, help="Hugging Face repo id or a local model directory."
    )
    parser.add_argument(
        "--name", required=True, help="Name of the transcript: writes asr/<name>.json."
    )
    parser.add_argument(
        "--song",
        action="append",
        default=[],
        dest="songs",
        metavar="SLUG",
        help="Only transcribe this song. Repeat for several.",
    )
    parser.add_argument(
        "--audio", default="vocals", help="Stem of the audio file in audio/ (default: vocals)."
    )
    parser.add_argument("--device", default="auto", help="auto, cpu or cuda (default: auto).")
    parser.add_argument(
        "--compute-type", default="default", help="CTranslate2 compute type (default: default)."
    )
    parser.add_argument(
        "--beam-size", type=positive_int, default=5, help="Beam size, at least 1 (default: 5)."
    )
    parser.add_argument(
        "--vad",
        action="store_true",
        help="Enable the voice activity filter. Off by default: it can cut sung passages.",
    )
    existing = parser.add_mutually_exclusive_group()
    existing.add_argument(
        "--overwrite", action="store_true", help="Replace an existing asr/<name>.json."
    )
    existing.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip songs that already have asr/<name>.json, to resume after a failure.",
    )
    args = parser.parse_args(argv)
    return Options(
        songs_dir=args.songs_dir,
        model=args.model,
        name=args.name,
        songs=args.songs,
        audio=args.audio,
        device=args.device,
        compute_type=args.compute_type,
        beam_size=args.beam_size,
        vad=args.vad,
        overwrite=args.overwrite,
        skip_existing=args.skip_existing,
    )


def load_whisper(options: Options) -> Transcriber:
    # Imported here so that importing this module (and the tests) stays light.
    from faster_whisper import WhisperModel  # noqa: PLC0415

    model: Transcriber = WhisperModel(
        options.model, device=options.device, compute_type=options.compute_type
    )
    return model


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _select_songs(options: Options) -> list[Path]:
    songs = list_songs(options.songs_dir)
    if not options.songs:
        return songs
    by_slug = {song.name: song for song in songs}
    for slug in options.songs:
        if slug not in by_slug:
            raise SongSetError(f'Unknown song "{slug}" under {options.songs_dir}')
    # Keep the sorted order and drop duplicates given on the command line.
    wanted = set(options.songs)
    return [song for song in songs if song.name in wanted]


def _run(options: Options, load_model: Callable[[Options], Transcriber]) -> None:
    # Check everything that can fail cheaply before the model is loaded.
    validate_name(options.name)
    songs = _select_songs(options)
    pending: list[Path] = []
    for song in songs:
        if options.skip_existing and asr_exists(song, options.name):
            _log(f"{song.name}: skipped (asr/{options.name}.json exists)")
        else:
            pending.append(song)
    audio_files = [(song, find_audio(song, options.audio)) for song in pending]
    for song, _ in audio_files:
        ensure_writable(song, options.name, overwrite=options.overwrite)
    if not audio_files:
        _log("Nothing to transcribe")
        return

    _log(f"Loading model {options.model} (device={options.device})")
    model = load_model(options)
    versions = {
        "fasterWhisper": version("faster-whisper"),
        "ctranslate2": version("ctranslate2"),
        "av": version("av"),
    }
    for number, (song, audio) in enumerate(audio_files, start=1):
        prefix = f"[{number}/{len(audio_files)}] {song.name}"
        _log(f"{prefix}: transcribing {audio.name}")
        started = time.monotonic()
        try:
            segments, _ = model.transcribe(
                str(audio),
                language=LANGUAGE,
                word_timestamps=True,
                vad_filter=options.vad,
                beam_size=options.beam_size,
            )
            result = asr_words([word for segment in segments for word in segment.words or ()])
        except ValueError as error:
            raise SongSetError(f'Song "{song.name}": {error}') from error
        except Exception as error:
            # Segments decode lazily, so model failures (e.g. CUDA errors) surface
            # here; name the song so the user knows where to resume.
            raise SongSetError(f'Song "{song.name}": {type(error).__name__}: {error}') from error
        write_asr(
            song,
            options.name,
            result.words,
            {
                "model": options.model,
                **versions,
                "device": options.device,
                "computeType": options.compute_type,
                "deviceUsed": model.model.device,
                "computeTypeUsed": model.model.compute_type,
                "beamSize": options.beam_size,
                "vad": options.vad,
                "language": LANGUAGE,
                "audio": audio.name,
                "clampedStarts": result.clamped_starts,
            },
            overwrite=options.overwrite,
        )
        _log(f"{prefix}: {len(result.words)} words in {time.monotonic() - started:.1f} s")
        if result.clamped_starts > 0:
            _log(f"warning: {song.name}: {result.clamped_starts} word starts clamped")
        if not result.words:
            _log(f"warning: {song.name}: no words")


def main(
    argv: Sequence[str] | None = None,
    load_model: Callable[[Options], Transcriber] = load_whisper,
) -> int:
    options = parse_args(argv)
    try:
        _run(options, load_model)
    except (SongSetError, OSError) as error:
        _log(f"error: {error}")
        return 1
    except Exception as error:  # report any model failure without a traceback
        _log(f"error: {type(error).__name__}: {error}")
        return 1
    return 0
