"""faster-whisper ile kelime zamanlı transkripsiyon. Modeller ilk kullanımda indirilir, sonra çevrimdışı çalışır."""
from __future__ import annotations

from typing import Callable, Iterator

from .profanity import Word


def transcribe_words(path: str, language: str | None = None, model_size: str = "small",
                     device: str = "auto", on_progress: Callable[[float], None] | None = None,
                     should_cancel: Callable[[], bool] | None = None) -> Iterator[Word]:
    """language: 'tr' | 'en' | None (otomatik). Kelimeleri akış halinde üretir."""
    from faster_whisper import WhisperModel   # geç içe aktarma: uygulama modelsiz de açılır

    compute = "int8" if device in ("cpu", "auto") else "float16"
    model = WhisperModel(model_size, device=device, compute_type=compute)
    segments, info = model.transcribe(path, language=language, word_timestamps=True,
                                      vad_filter=True)
    for seg in segments:
        if should_cancel and should_cancel():
            return
        for w in seg.words or []:
            yield Word(w.word.strip(), float(w.start), float(w.end))
        if on_progress and info.duration:
            on_progress(min(1.0, seg.end / info.duration))
