"""The character CTC model: the real ONNX file and vocabulary behave as the code assumes.

Skipped unless `LIRISYNC_ALIGNER_DIR` names a directory fetched with
`tools/fetch_aligner_model.py`. The model is about 360 MB (int8) and runs on the CPU.
"""

import os
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pytest

from lirisync_worker.ctc_model import BLANK, SAMPLE_RATE, CharCtcModel, frame_count, parse_vocab
from lirisync_worker.ctc_tokens import CharVocab, kana_text, surface_text
from lirisync_worker.match_text import Token

ENV_VAR = "LIRISYNC_ALIGNER_DIR"
FILES = ("model.int8.onnx", "vocab.json")

# Silence in the sense of "no singing": faint noise. The input is normalized to
# unit variance, so the model sees loud noise, not quiet; 95% is a floor well
# above chance for a model that has learned that noise carries no text.
NOISE_AMPLITUDE = 1e-4
NOISE_SECONDS = 2
MIN_BLANK_SHARE = 0.95

GOJUON = (
    "あいうえお" "かきくけこ" "さしすせそ" "たちつてと" "なにぬねの"
    "はひふへほ" "まみむめも" "やゆよ" "らりるれろ" "わをん"
    "がぎぐげご" "ざじずぜぞ" "だぢづでど" "ばびぶべぼ" "ぱぴぷぺぽ"
    "ぁぃぅぇぉ" "ゃゅょっー" "ゎゐゑゔゕゖ"
)  # fmt: skip
# Every kana letter, the long vowel mark, the small katakana extension (U+31F0..)
# and a small katakana with a combining semi-voiced mark (ㇷ゚).
ALL_KANA = (
    "".join(chr(c) for c in range(0x3041, 0x3097))
    + "".join(chr(c) for c in range(0x30A1, 0x30FB))
    + "ー"
    + "".join(chr(c) for c in range(0x31F0, 0x3200))
    + "ㇷ\u309a"
)
# Hiragana the vocabulary lacks, and what `kana_text` writes in their place.
NO_TOKEN_KANA = {"ゎ": "わ", "ゐ": "い", "ゑ": "え", "ゕ": "か", "ゖ": "け", "ゔ": "ヴ"}


class CharReader:
    """A reader that reads every character as itself."""

    def __call__(self, text: str) -> Iterable[Token]:
        return [Token(surface=ch, reading=ch) for ch in text]


@pytest.fixture(scope="module")
def aligner_dir() -> Path:
    value = os.environ.get(ENV_VAR)
    if not value:
        pytest.skip(f"{ENV_VAR} is not set; see tools/fetch_aligner_model.py")
    directory = Path(value).expanduser()
    missing = [name for name in FILES if not (directory / name).is_file()]
    if missing:
        pytest.skip(f"{ENV_VAR}={directory} lacks {missing}; see tools/fetch_aligner_model.py")
    return directory


@pytest.fixture(scope="module")
def model(aligner_dir: Path) -> CharCtcModel:
    return CharCtcModel(aligner_dir)


@pytest.fixture(scope="module")
def noise_log_probs(model: CharCtcModel) -> np.ndarray:
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(NOISE_SECONDS * SAMPLE_RATE) * NOISE_AMPLITUDE).astype(np.float32)
    return model.log_probs(noise)


def test_the_real_model_passes_the_contract_check(model: CharCtcModel) -> None:
    assert len(model.vocab) > 2000


def test_the_vocabulary_file_is_accepted_as_is(aligner_dir: Path) -> None:
    import json  # noqa: PLC0415 - only this test reads the raw file

    raw = json.loads((aligner_dir / "vocab.json").read_text(encoding="utf-8"))

    assert BLANK in parse_vocab(raw, "vocab.json").values()


def test_noise_is_mostly_blank(noise_log_probs: np.ndarray) -> None:
    blank_share = float((noise_log_probs.argmax(axis=1) == BLANK).mean())

    assert blank_share >= MIN_BLANK_SHARE, f"only {blank_share:.1%} of frames are blank"


def test_the_frame_count_is_what_frame_count_predicts(noise_log_probs: np.ndarray) -> None:
    assert noise_log_probs.shape[0] == frame_count(NOISE_SECONDS * SAMPLE_RATE)


def test_the_log_probs_are_finite(noise_log_probs: np.ndarray) -> None:
    assert np.isfinite(noise_log_probs).all()


def test_the_gojuon_encodes_without_skipping(model: CharCtcModel) -> None:
    text = kana_text(GOJUON, CharReader(), frozenset())

    assert model.vocab.encode(text).skipped == ""


def test_every_kana_without_a_token_is_replaced_by_one_with_a_token(model: CharCtcModel) -> None:
    text = kana_text("".join(NO_TOKEN_KANA), CharReader(), frozenset())

    assert text == "".join(NO_TOKEN_KANA.values())


@pytest.mark.parametrize("kana", sorted(NO_TOKEN_KANA))
def test_a_replaced_kana_really_has_no_token(model: CharCtcModel, kana: str) -> None:
    assert model.vocab.encode(kana).skipped == kana


def test_the_replacements_all_have_tokens(model: CharCtcModel) -> None:
    assert model.vocab.encode("".join(NO_TOKEN_KANA.values())).skipped == ""


def test_the_kanji_iteration_mark_has_a_token(model: CharCtcModel) -> None:
    assert model.vocab.encode("々").skipped == ""


def test_the_vocabulary_is_a_char_vocab(model: CharCtcModel) -> None:
    assert isinstance(model.vocab, CharVocab)


def test_surface_text_leaves_no_kana_without_a_token(model: CharCtcModel) -> None:
    assert model.vocab.encode(surface_text(ALL_KANA, frozenset())).skipped == ""


def test_kana_text_leaves_no_kana_without_a_token(model: CharCtcModel) -> None:
    text = kana_text(ALL_KANA, CharReader(), frozenset())

    assert model.vocab.encode(text).skipped == ""
