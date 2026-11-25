# Mimari
```
src/videolab/
  core/      model.py (Timeline/Track/Clip) · history.py (undo/redo) · project.py (JSON + SQLite)
  media/     ffmpeg.py (probe, akışlı PCM okuma)
  analysis/  silence.py · profanity.py · transcribe.py (faster-whisper)
  export/    exporter.py (filter_complex + ilerleme/iptal) · censor.py (bip/sessiz)
  ui/        main_window.py · timeline_widget.py · workers.py (QThread) · theme.py
  i18n/      tr.json (yeni dil = yeni JSON)
```
İlkeler: UI ile motor ayrı (core/analysis/export Qt'ye bağımlı değil, test edilebilir); ağır işler QThread'de;
ses/video akış halinde işlenir (3 saatlik videoda RAM sabit); undo = JSON anlık görüntü; proje yazımı atomik.
Sessizlik kesme = `Timeline.remove_range(ripple=True)`; ses/video aynı aralıktan kesildiği için senkron bozulmaz.
Küfür: transkript (kelime zamanları) → `ProfanityFilter.scan` → `CensorRegion` → FFmpeg ses filtresi (bip kelimenin tamamını kapsar).
