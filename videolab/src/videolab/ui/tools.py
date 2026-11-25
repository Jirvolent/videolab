"""Araçlar menüsü: transkript tabanlı özellikler, altyazı, 9:16 takip, proxy, küçük resim, toplu işlem, kayıt, eklentiler.
NOT: Bu dosya henüz gerçek bir masaüstünde denenmedi; arkasındaki motor modülleri testlidir."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from ..analysis.autocrop import detect_face_track, smooth_track
from ..analysis.profanity import ProfanityFilter, Word
from ..analysis.transcript_tools import (SubStyle, find_fillers, find_retakes, make_chapters, chapters_text,
                                         parse_srt, ranges_from_deleted_words, to_ass, to_srt, words_to_cues)
from ..analysis.diarize import diarize_file, label_words, speech_regions
from ..analysis.silence import frame_levels_db
from ..analysis.transcript_tools import speaker_name
from ..core.branding import Branding, intro_offset, with_branding
from ..core.edit_ops import apply_cuts, apply_transitions, source_to_timeline
from ..core.model import Clip
from ..media.ffmpeg import probe, stream_pcm
from ..core.pipeline import AutoEditOptions, Job, JobQueue, auto_edit
from ..core.plugins import load_plugins
from ..export.censor import CensorRegion
from ..export.exporter import ExportSettings, export
from ..media.proxy import make_proxy
from ..media.recorder import Recording, build_record_command
from ..media.youtube import pick_thumbnails
from ..analysis.breaths import BreathSegment, detect_breaths_file
from ..core.voice_prep import VoiceOptions, prepare
from .dialogs import VoiceDialog, BatchDialog, BrandingDialog, ChecklistDialog, ExportDialog, TextDialog, TransitionDialog, WordEditDialog
from .workers import Worker


def _transcribe(path, prog, cancel, language=None):
    from ..analysis.transcribe import transcribe_words
    return list(transcribe_words(path, language=language, on_progress=prog, should_cancel=cancel.is_set))


class ToolsMixin:
    def init_tools(self):
        self.words: list[Word] = []
        self.profanity = ProfanityFilter()
        self.words_media: str | None = None
        self.censor_hits = []               # (kaynak_başlangıç, kaynak_bitiş, mod)
        self.follow_keys = []               # kaynak zamanında (t, merkez)
        self.cues = []
        self.voice_opts = VoiceOptions()
        self.breath_list: list[BreathSegment] | None = None      # kullanıcının incelediği nefesler (kaynak zamanı)
        self.breath_media: str | None = None
        self.speaker_labels: list[int] | None = None
        self.branding = Branding.load(self.recent)
        self.recording: Recording | None = None
        self.plugins, errors = load_plugins(Path.home() / ".videolab" / "plugins")
        m = self.menuBar().addMenu("Araçlar")
        def add(label, slot):
            a = QAction(label, self); a.triggered.connect(slot); m.addAction(a)
        add("Konuşmayı yazıya dök (TR/EN)…", self.tool_transcribe)
        add("Dolgu sözcüklerini temizle…", self.tool_fillers)
        add("Tekrar çekimleri bul…", self.tool_retakes)
        add("Metinden düzenle…", self.tool_text_edit)
        add("Küfür algıla ve sansürle…", self.tool_profanity)
        m.addSeparator()
        add("Altyazı oluştur (kelime vurgulu)", self.tool_make_subs)
        add("SRT dışa aktar…", self.tool_export_srt); add("SRT içe aktar…", self.tool_import_srt)
        add("Bölüm / zaman damgası önerisi…", self.tool_chapters)
        add("9:16 yüz takibini hesapla…", self.tool_follow)
        add("Küçük resim önerileri…", self.tool_thumbs)
        add("Konuşmacıları ayır…", self.tool_speakers)
        add("Ses iyileştirme (nefes, ağız sesi, ton)…", self.tool_voice)
        m.addSeparator()
        add("Geçişleri tüm kliplere uygula…", self.tool_transitions_all)
        add("Seçili klibe geçiş ata…", self.tool_transition_selected)
        add("Intro / Outro ayarları…", self.tool_branding)
        m.addSeparator()
        add("Proxy önizleme oluştur…", self.tool_proxy)
        add("Toplu işlem…", self.tool_batch)
        add("Ekran kaydını başlat/durdur", self.tool_record_screen)
        if self.plugins.actions or errors:
            pm = self.menuBar().addMenu("Eklentiler")
            for name, fn in self.plugins.actions.items():
                a = QAction(name, self); a.triggered.connect(lambda _, f=fn: f(self)); pm.addAction(a)
            for e in errors:
                pm.addAction(QAction("⚠ " + e, self))

    # ---- yardımcılar
    def _clip(self):
        c = self._target_clip()
        if not c: QMessageBox.information(self, "VideoLab", "Önce timeline'a bir video ekleyin.")
        return c

    def _need_words(self) -> bool:
        c = self._target_clip()
        if not c or not self.words or self.words_media != c.media_path:
            QMessageBox.information(self, "VideoLab", "Önce Araçlar ▸ Konuşmayı yazıya dök çalıştırın."); return False
        return True

    # ---- transkript
    def tool_transcribe(self):
        c = self._clip()
        if not c: return
        lang, ok = QInputDialog.getItem(self, "Dil", "Konuşma dili:", ["Otomatik", "Türkçe", "English"], 0, False)
        if not ok: return
        code = {"Otomatik": None, "Türkçe": "tr", "English": "en"}[lang]
        def done(words): self.words, self.words_media = words, c.media_path; self.statusBar().showMessage(f"{len(words)} kelime yazıya döküldü")
        self._run("Konuşma yazıya dökülüyor (ilk seferde model indirilir)…", lambda p, ev: _transcribe(c.media_path, p, ev, code), done)

    def _apply_spans(self, title, spans):
        if not spans: QMessageBox.information(self, title, "Bir şey bulunamadı."); return
        dlg = ChecklistDialog(self, title, [f"{s.start:.2f}–{s.end:.2f}  {s.text}" for s in spans], "Kesilecekleri işaretleyin.")
        if dlg.exec():
            c = self._target_clip(); self.history.checkpoint(title)
            cut = apply_cuts(self.project.timeline, c, [(spans[i].start, spans[i].end) for i in dlg.checked()])
            self.timeline.update(); self.statusBar().showMessage(f"{cut:.1f} sn kesildi")

    def tool_fillers(self):
        if self._need_words(): self._apply_spans("Dolgu sözcükleri", find_fillers(self.words))

    def tool_retakes(self):
        if self._need_words(): self._apply_spans("Tekrar çekimler", find_retakes(self.words))

    def tool_text_edit(self):
        if not self._need_words(): return
        dlg = WordEditDialog(self, self.words)
        if dlg.exec() and dlg.selected():
            sel = dlg.selected(); c = self._target_clip(); self.history.checkpoint("Metinden düzenle")
            apply_cuts(self.project.timeline, c, ranges_from_deleted_words(self.words, sel))
            self.words = [w for i, w in enumerate(self.words) if i not in sel]; self.timeline.update()

    def tool_profanity(self):
        if not self._need_words(): return
        hits = self.profanity.scan(self.words)
        if not hits: QMessageBox.information(self, "Küfür", "Küfür bulunamadı."); return
        mode, ok = QInputDialog.getItem(self, "Sansür türü", "Nasıl sansürlensin?", ["Bip sesi", "Sessize al"], 0, False)
        if not ok: return
        dlg = ChecklistDialog(self, "Küfürler", [f"{h.start:.2f}–{h.end:.2f}  {h.word}" for h in hits], "Yanlış algılananların işaretini kaldırın.")
        if dlg.exec():
            self.censor_hits = [(hits[i].start, hits[i].end, "beep" if mode == "Bip sesi" else "mute") for i in dlg.checked()]
            self._overlay_censor(); self.statusBar().showMessage(f"{len(self.censor_hits)} sansür işaretlendi (dışa aktarırken uygulanır)")

    def _overlay_censor(self):
        from PySide6.QtGui import QColor
        c = self._target_clip(); ov = []
        for a, b, _ in self.censor_hits:
            ta = source_to_timeline(self.project.timeline, c.media_path, a)
            if ta is not None: ov.append((ta, ta + (b - a) / c.speed, QColor(255, 165, 0, 120)))
        self.timeline.overlays = ov; self.timeline.update()

    # ---- altyazı
    def tool_make_subs(self):
        if self._need_words():
            sp = self.speaker_labels if self.speaker_labels and len(self.speaker_labels) == len(self.words) else None
            self.cues = words_to_cues(self.words, speakers=sp); self.statusBar().showMessage(f"{len(self.cues)} altyazı satırı")

    def tool_export_srt(self):
        if not self.cues: self.tool_make_subs()
        if not self.cues: return
        p, _ = QFileDialog.getSaveFileName(self, "SRT", "", "SRT (*.srt)")
        if p: Path(p).write_text(to_srt(self.cues, speaker_prefix=any(c.speaker is not None for c in self.cues)), encoding="utf-8")

    def tool_import_srt(self):
        p, _ = QFileDialog.getOpenFileName(self, "SRT", "", "SRT (*.srt)")
        if p: self.cues = parse_srt(Path(p).read_text(encoding="utf-8-sig")); self.statusBar().showMessage(f"{len(self.cues)} satır içe aktarıldı")

    def tool_chapters(self):
        if self._need_words(): TextDialog(self, "YouTube bölümleri", chapters_text(make_chapters(self.words)), True).exec()

    # ---- konuşmacılar, geçişler, intro/outro
    def tool_speakers(self):
        c = self._clip()
        if not c: return
        n, ok = QInputDialog.getInt(self, "Konuşmacı sayısı", "Kaç konuşmacı var? (0 = otomatik)", 0, 0, 8)
        if not ok: return
        def work(p, ev):
            regions = speech_regions(frame_levels_db(stream_pcm(c.media_path, 16000, 10.0), 16000))
            return diarize_file(c.media_path, regions, n_speakers=n or None, on_progress=p)
        def done(segs):
            self.speaker_segments = segs
            if self.words and self.words_media == c.media_path: self.speaker_labels = label_words(self.words, segs)
            from PySide6.QtGui import QColor
            from ..analysis.transcript_tools import SPEAKER_COLORS
            off = c.start - c.source_in
            self.timeline.overlays = [(s.start + off, s.end + off, QColor(SPEAKER_COLORS[s.speaker % 6] + "55")) for s in segs]
            self.timeline.update(); self.statusBar().showMessage(f"{len({s.speaker for s in segs})} konuşmacı bulundu (yerleşik yöntem benzer seslerde hata yapabilir)")
        self._run("Konuşmacılar ayrılıyor…", work, done)

    def tool_voice(self):
        dlg = VoiceDialog(self, self.voice_opts)
        dlg.find_btn.clicked.connect(lambda: self.tool_find_breaths(dlg))
        if dlg.exec():
            self.voice_opts = dlg.value(); self.statusBar().showMessage("Ses iyileştirme ayarları kaydedildi; dışa aktarırken uygulanır")

    def tool_find_breaths(self, parent=None):
        c = self._clip()
        if not c: return
        def done(segs):
            if not segs: QMessageBox.information(self, "Nefesler", "Nefes bulunamadı."); return
            dlg = ChecklistDialog(self, "Bulunan nefesler", [f"{s.start:.2f}–{s.end:.2f} sn   ({s.level_db:.0f} dB)" for s in segs],
                                  "Nefes olmayanların işaretini kaldırın. Bu yöntem bir tahmindir; hatalı bulgular olabilir.")
            if dlg.exec():
                keep = set(dlg.checked())
                for i, sg in enumerate(segs): sg.enabled = i in keep
                self.breath_list, self.breath_media = segs, c.media_path
                from PySide6.QtGui import QColor
                off = c.start - c.source_in
                self.timeline.overlays = [(sg.start + off, sg.end + off, QColor(80, 200, 255, 110)) for sg in segs if sg.enabled]; self.timeline.update()
        self._run("Nefesler aranıyor…", lambda p, ev: detect_breaths_file(c.media_path, on_progress=p), done)

    def tool_transitions_all(self):
        dlg = TransitionDialog(self, "Geçişleri uygula")
        if dlg.exec():
            self.history.checkpoint("Geçişler")
            n = apply_transitions(self.project.timeline, dlg.trans.currentData(), dlg.dur.value())
            self.timeline.update(); self.statusBar().showMessage(f"{n} klip sınırına geçiş atandı")

    def tool_transition_selected(self):
        sel = self.timeline.selected
        if not sel: QMessageBox.information(self, "VideoLab", "Önce bir klip seçin (geçiş, o klibin BAŞINA uygulanır)."); return
        dlg = TransitionDialog(self, "Seçili klibe geçiş")
        if dlg.exec():
            self.history.checkpoint("Geçiş")
            _, clip = self.project.timeline.find_clip(sel); clip.transition, clip.transition_dur = dlg.trans.currentData(), dlg.dur.value()
            self.timeline.update()

    def tool_branding(self):
        dlg = BrandingDialog(self, self.branding)
        if dlg.exec(): self.branding = dlg.value(); self.branding.save(self.recent); self.statusBar().showMessage("Intro/outro ayarları kaydedildi")

    # ---- kütüphaneden ekleme (oynatma çubuğu konumuna)
    def insert_library_item(self, item):
        tl = self.project.timeline; t = self.timeline.playhead; self.history.checkpoint("Kütüphaneden ekle")
        if item.kind == "meme":
            dur = 2.5 if item.is_image else min(item.duration or 3.0, 6.0)
            track = tl.tracks[1]                                          # V2: bindirme
            tl.add_clip(track.id, Clip(item.path, 0, dur, t, scale=0.35, pos_x=0.5, pos_y=0.5, label=item.name))
        else:
            tl.add_clip(tl.tracks[3].id, Clip(item.path, 0, item.duration or 1.0, t, label=item.name))   # A2: efekt
        self.timeline.update()

    # ---- 9:16 takip / proxy / küçük resim
    def tool_follow(self):
        c = self._clip()
        if not c: return
        def work(p, ev): return smooth_track(detect_face_track(c.media_path, 2.0, p, ev.is_set))
        def done(keys): self.follow_keys = keys; self.statusBar().showMessage(f"{len(keys)} takip anahtarı hazır; dışa aktarırken 9:16 seçin")
        self._run("Yüz takibi hesaplanıyor…", work, done)

    def tool_proxy(self):
        c = self._clip()
        if not c: return
        dst = str(Path(c.media_path).with_suffix("")) + "_proxy.mp4"
        self._run("Proxy oluşturuluyor…", lambda p, ev: make_proxy(c.media_path, dst, 360, p, ev),
                  lambda d: (self.player.setSource(QUrl.fromLocalFile(d)), self.statusBar().showMessage("Önizleme proxy'e geçti; dışa aktarma orijinali kullanır")))

    def tool_thumbs(self):
        c = self._clip()
        if not c: return
        prefix = str(Path(c.media_path).with_suffix("")) + "_thumb"
        self._run("Kareler taranıyor…", lambda p, ev: pick_thumbnails(c.media_path, prefix, 3),
                  lambda ps: QMessageBox.information(self, "Küçük resimler", "\n".join(ps)))

    # ---- toplu işlem, kayıt
    def tool_batch(self):
        dlg = BatchDialog(self)
        if not (dlg.exec() and dlg.files and dlg.outdir): return
        q = JobQueue()
        for f in dlg.files:
            out = os.path.join(dlg.outdir, Path(f).stem + "_duzenlendi.mp4")
            opt = AutoEditOptions(silence=self._params() if dlg.sil.isChecked() else None, remove_fillers=dlg.fil.isChecked(),
                                  censor_profanity=dlg.prof.isChecked(), voice=dlg.voice(), branding=self.branding, transcriber=lambda p: _transcribe(p, lambda *_: None, threading.Event()))
            q.add(Job(Path(f).name, lambda prog, ev, f=f, out=out, opt=opt: auto_edit(f, ExportSettings(out), opt, prog, ev)))
        def work(prog, ev):
            q.run_all(lambda i, fr: prog((i + fr) / len(q.jobs)), ev); return q
        def done(q):
            bad = [f"{j.name}: {j.error}" for j in q.jobs if j.status == "hata"]
            QMessageBox.information(self, "Toplu işlem", f"{sum(j.status == 'bitti' for j in q.jobs)} / {len(q.jobs)} tamamlandı." + ("\n\n" + "\n".join(bad) if bad else ""))
        self._run("Toplu işlem…", work, done)

    def tool_record_screen(self):
        if self.recording:
            self.recording.stop(); self.recording = None; self.statusBar().showMessage("Kayıt durduruldu"); return
        p, _ = QFileDialog.getSaveFileName(self, "Kayıt dosyası", "", "MP4 (*.mp4)")
        if p:
            self.recording = Recording(build_record_command("screen", p)); self.statusBar().showMessage("Kayıt sürüyor… tekrar tıklayarak durdurun")

    # ---- dışa aktarma (tüm seçeneklerle)
    def export_dialog(self):
        tl = self.project.timeline
        has_music = any(t.kind == "audio" and t.clips for t in tl.tracks)
        dlg = ExportDialog(self, has_music, bool(self.follow_keys), bool(self.cues))
        if not dlg.exec(): return
        path, _ = QFileDialog.getSaveFileName(self, "Dışa aktar", "", f"{dlg.container.currentText().upper()} (*.{dlg.container.currentText()})")
        if not path: return
        s = dlg.settings(path); c = self._target_clip()
        if c:
            s.censor = [CensorRegion(a_t, a_t + (b - a) / c.speed, mode) for a, b, mode in self.censor_hits
                        if (a_t := source_to_timeline(tl, c.media_path, a)) is not None]
            if dlg.follow.isChecked() and self.follow_keys and s.aspect == "9:16":
                s.follow = [(t2, cx) for t, cx in self.follow_keys if (t2 := source_to_timeline(tl, c.media_path, t)) is not None]
        tmp_ass = None
        if dlg.subs.isChecked() and self.cues:
            w, h = s.size(); tmp_ass = path + ".ass"
            Path(tmp_ass).write_text(to_ass(self.cues, SubStyle(size=max(24, h // 20)), w, h), encoding="utf-8"); s.subtitle_ass = tmp_ass
        branded = with_branding(tl, self.branding)
        if intro_offset(self.branding):
            off = intro_offset(self.branding)
            s.censor = [CensorRegion(r.start + off, r.end + off, r.mode) for r in s.censor]; s.follow = [(t + off, x) for t, x in s.follow]
        voice, mc = self.voice_opts, c
        breaths = self.breath_list if (c and self.breath_media == c.media_path) else None
        def work(p, ev):
            temps = []
            try:
                if voice.any and mc:                    # analiz (nefes/otomatik EQ) burada, arka planda yapılır
                    temps = prepare(s, mc.media_path, voice, lambda t: source_to_timeline(tl, mc.media_path, t),
                                    tl.duration, intro_offset(self.branding), breaths)
                export(branded, s, p, ev)
            finally:
                for t in temps + ([tmp_ass] if tmp_ass else []):
                    if t and os.path.exists(t): os.remove(t)
        self._run("Dışa aktarılıyor…", work, lambda _: self.statusBar().showMessage("Dışa aktarma tamamlandı"))
