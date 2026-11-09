import wave
from pathlib import Path

from faster_whisper import decode_audio

SAMPLE_RATE = 16000


def test_decode_audio_reads_a_wav_with_the_pinned_av(tmp_path: Path) -> None:
    # Guards the `av` upper bound in pyproject.toml: faster-whisper calls
    # av.open(metadata_errors=...), which PyAV 19 removed, so decoding any file
    # raises TypeError there. No model is needed, so this stays cheap.
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"\x00\x00" * (SAMPLE_RATE // 10))

    assert len(decode_audio(str(path), sampling_rate=SAMPLE_RATE)) == SAMPLE_RATE // 10
