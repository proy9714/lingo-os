"""Speech to text on this laptop (faster-whisper), for videos with no captions in your language and your own media.

Off until you choose a model in Settings → Transcription. The model downloads the first time it's needed (into
data/models), runs on the CPU, and nothing is sent anywhere: YouTube audio is fetched like the video itself, kept only
while it's being transcribed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig
from app.ingest.subtitles import Cue

# CTranslate2 conversions of OpenAI's Whisper models, quantised to int8 on load
MODELS = {
    "base": {"repo": "Systran/faster-whisper-base", "size_mb": 145, "label": "Base: quick (about a minute for 10 minutes of video)"},
    "small": {"repo": "Systran/faster-whisper-small", "size_mb": 484, "label": "Small: more accurate, about 3× slower"},
}
SETTING = "whisper.model"


class WhisperError(RuntimeError):
    pass


@dataclass
class Transcription:
    cues: list[Cue]
    language: str
    language_probability: float


def model_dir(cfg: AppConfig, size: str) -> Path:
    return cfg.data_dir / "models" / f"whisper-{size}"


def model_ready(cfg: AppConfig, size: str) -> bool:
    return (model_dir(cfg, size) / "model.bin").exists()


def ensure_model(cfg: AppConfig, size: str) -> Path:
    """The model's folder, downloading it first if needed."""
    if size not in MODELS:
        raise WhisperError(f"unknown Whisper model '{size}'")
    target = model_dir(cfg, size)
    if model_ready(cfg, size):
        return target
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(MODELS[size]["repo"], local_dir=target, allow_patterns=["*.bin", "*.json", "*.txt"])
    except Exception as exc:  # noqa: BLE001 - network or disk: say what happened
        raise WhisperError(f"the speech model couldn't be downloaded: {exc}") from exc
    if not model_ready(cfg, size):
        raise WhisperError("the speech model download is incomplete")
    return target


def youtube_audio(video_id: str, folder: Path) -> Path:
    """The audio track only (no video, no conversion: whisper reads m4a and webm itself)."""
    from yt_dlp import YoutubeDL

    folder.mkdir(parents=True, exist_ok=True)
    options = {
        "format": "bestaudio[ext=m4a]/bestaudio", "outtmpl": str(folder / f"{video_id}.%(ext)s"), "quiet": True,
        "no_warnings": True, "noplaylist": True, "js_runtimes": {"node": {}}, "socket_timeout": 30,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            path = Path(ydl.prepare_filename(info))
    except Exception as exc:  # noqa: BLE001
        raise WhisperError(f"the audio couldn't be fetched: {str(exc).splitlines()[0][:200]}") from exc
    if not path.exists():
        raise WhisperError("the audio couldn't be fetched")
    return path


SAMPLE_RATE = 16000


def decode(audio: Path):  # noqa: ANN201 - a float32 numpy array
    """The recording as 16 kHz mono samples. (faster-whisper's own decoder passes an option newer PyAV removed.)"""
    import av
    import numpy as np

    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(str(audio), mode="r") as container:
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray().reshape(-1))
        for resampled in resampler.resample(None):  # flush what the resampler still holds
            chunks.append(resampled.to_ndarray().reshape(-1))
    if not chunks:
        raise WhisperError("the recording has no sound track")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe(model_path: Path, audio: Path, lang: str, on_progress: Callable[[float], None] | None = None,
               duration: float | None = None) -> Transcription:
    from faster_whisper import WhisperModel

    model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
    segments, info = model.transcribe(decode(audio), language=lang, vad_filter=True, beam_size=5, condition_on_previous_text=False)
    total = duration or info.duration or 0
    cues: list[Cue] = []
    for segment in segments:
        line = segment.text.strip()
        if line:
            cues.append(Cue(int(segment.start * 1000), int(segment.end * 1000), line))
        if on_progress and total:
            on_progress(min(1.0, segment.end / total))
    return Transcription(cues, info.language, info.language_probability)
