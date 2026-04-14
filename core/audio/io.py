from __future__ import annotations

import io
import math
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class AudioPreviewStats:
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    peak_dbfs: float | None
    rms_dbfs: float | None
    is_likely_silent: bool


def save_uploaded_audio(upload: bytes | BinaryIO, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(upload, (bytes, bytearray)):
        payload = bytes(upload)
    elif hasattr(upload, "read"):
        payload = upload.read()
    else:
        raise TypeError("Unsupported uploaded audio type.")

    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("Uploaded audio payload must be bytes.")

    output_path.write_bytes(bytes(payload))
    return output_path


def copy_audio_file(source_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, output_path)
    return output_path


def get_audio_duration(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wav_file:
        frame_count = wav_file.getnframes()
        frame_rate = wav_file.getframerate()
        if frame_rate == 0:
            raise ValueError(f"Invalid WAV sample rate in {audio_path}")
        return frame_count / float(frame_rate)


def get_audio_sample_rate(audio_path: Path) -> int:
    with wave.open(str(audio_path), "rb") as wav_file:
        return int(wav_file.getframerate())


def inspect_wav_bytes(audio_bytes: bytes) -> AudioPreviewStats:
    if not audio_bytes:
        raise ValueError("Audio payload is empty.")

    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        frame_count = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        raw_frames = wav_file.readframes(frame_count)

    if sample_rate <= 0:
        raise ValueError("Invalid WAV sample rate.")
    if sample_width not in (1, 2, 3, 4):
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    duration_seconds = frame_count / float(sample_rate)
    peak_abs = 0
    sum_squares = 0.0
    sample_count = 0

    for index in range(0, len(raw_frames), sample_width):
        chunk = raw_frames[index : index + sample_width]
        if len(chunk) < sample_width:
            continue

        if sample_width == 1:
            sample = chunk[0] - 128
            max_value = 127
        else:
            sample = int.from_bytes(chunk, byteorder="little", signed=True)
            max_value = (1 << (8 * sample_width - 1)) - 1

        abs_sample = abs(sample)
        if abs_sample > peak_abs:
            peak_abs = abs_sample
        sum_squares += float(sample * sample)
        sample_count += 1

    if sample_count == 0:
        peak_dbfs = None
        rms_dbfs = None
        is_likely_silent = True
    else:
        peak_norm = peak_abs / max_value if max_value else 0.0
        rms_norm = math.sqrt(sum_squares / sample_count) / max_value if max_value else 0.0
        peak_dbfs = 20.0 * math.log10(max(peak_norm, 1e-12))
        rms_dbfs = 20.0 * math.log10(max(rms_norm, 1e-12))
        is_likely_silent = peak_norm < 0.01 and rms_norm < 0.003

    return AudioPreviewStats(
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frame_count=frame_count,
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        is_likely_silent=is_likely_silent,
    )


def maybe_normalize_audio(audio_path: Path) -> Path:
    # TODO(next): add optional normalization, resampling, and VAD hooks here.
    return audio_path
