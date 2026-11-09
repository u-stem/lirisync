from dataclasses import dataclass
from pathlib import Path

from lirisync_transcribe.songs import write_asr
from lirisync_transcribe.words import asr_words

# The same file is parsed by `parseAsrFile` in eval/test/asr-file.test.ts, so the
# writer here and the reader there cannot drift apart unnoticed.
FIXTURE = Path(__file__).parent / "fixtures" / "asr-sample.json"


@dataclass(frozen=True)
class FakeWord:
    start: float
    end: float
    word: str


def test_the_writer_output_equals_the_shared_fixture_text(tmp_path: Path) -> None:
    words = [
        FakeWord(12.3, 12.9, "風が"),
        FakeWord(12.9, 13.6, " line"),
        FakeWord(13.6, 13.6, "吹く"),
    ]

    write_asr(tmp_path, "t", asr_words(words).words, {}, overwrite=False)

    assert (tmp_path / "asr" / "t.json").read_text("utf-8") == FIXTURE.read_text("utf-8")
