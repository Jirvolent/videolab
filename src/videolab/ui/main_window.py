"""Ana pencere: medya paneli | önizleme | özellikler, altta timeline ve durum çubuğu."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QToolBar, QVBoxLayout, QWidget)

from .. import __version__
from ..analysis.silence import SilenceParams, find_silences, frame_levels_db
from ..core.history import History
from ..core.model import Clip, Timeline
from ..core.project import Project, RecentProjects
from ..export.exporter import ExportSettings, export
from ..i18n import tr
from ..media.ffmpeg import probe, stream_pcm
from .timeline_widget import TimelineWidget
from .workers import Worker
from .tools import ToolsMixin
from .library_panel import LibraryPanel
from ..core.library import Library

from PySide6.QtGui import QColor


class MainWindow(ToolsMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{tr('app.title')} {__version__}")
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        data_dir = Path.home() / ".videolab"
        self.recent = RecentProjects(str(data_dir / "videolab.db"))
        self.project = Project()
        self.history = History(self.project.timeline)
        self.levels = None                # analiz edilmiş ses seviyeleri
        self.silences = []
        self.worker: Worker | None = None
        self._build_ui()
        self.init_tools()
        self._autosave = QTimer(self, interval=60_000)
        self._autosave.timeout.connect(lambda: self.project.autosave())
        self._autosave.start()

    # ---------- arayüz ----------
    def _build_ui(self):
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(QAudioOutput(self))
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)
        self.timeline = TimelineWidget(self.project.timeline, self.history)
        self.timeline.seek.connect(lambda t: self.player.setPosition(int(t * 1000)))
        self.timeline.edited.connect(self._edited)

        center = QWidget(); lay = QVBoxLayout(center); lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.video, 3); lay.addWidget(self.timeline, 2)
        self.setCentralWidget(center)

        self.media_list = QListWidget()
        self.media_list.itemDoubleClicked.connect(lambda it: self.add_to_timeline(it.data(Qt.UserRole)))
        self._dock(tr("panel.media"), self.media_list, Qt.LeftDockWidgetArea)
        self.library = Library(str(Path.home() / ".videolab" / "videolab.db"), str(Path.home() / "VideoLab Kütüphane"))
        self.lib_panel = LibraryPanel(self.library)
        self.lib_panel.insert_requested.connect(lambda it: self.insert_library_item(it))
        self._dock("Meme & Ses Kütüphanesi", self.lib_panel, Qt.LeftDockWidgetArea)

        panel = QWidget(); form = QFormLayout(panel)
        d = SilenceParams()
        self.sp = {}
        for key, label, val, lo, hi, step in [
            ("min_silence", "silence.min", d.min_silence, 0.1, 10, 0.1),
            ("threshold_db", "silence.thr", d.threshold_db, -80, -5, 1),
            ("cut_ratio", "silence.ratio", d.cut_ratio * 100, 10, 100, 5),
            ("pad_before", "silence.before", d.pad_before, 0, 2, 0.05),
            ("pad_after", "silence.after", d.pad_after, 0, 2, 0.05)]:
            w = QDoubleSpinBox(); w.setRange(lo, hi); w.setSingleStep(step); w.setValue(val)
            w.valueChanged.connect(self._refresh_silences)
            self.sp[key] = w; form.addRow(tr(label), w)
        b1 = QPushButton(tr("silence.detect")); b1.clicked.connect(self.analyze_silence)
        b2 = QPushButton(tr("silence.apply")); b2.setObjectName("primary"); b2.clicked.connect(self.apply_silence)
        self.sil_list = QListWidget()
        self.sil_list.itemChanged.connect(self._silence_toggled)
        form.addRow(b1); form.addRow(self.sil_list); form.addRow(b2)
        self._dock(tr("panel.silence"), panel, Qt.RightDockWidgetArea)

        self.bar = QProgressBar(); self.bar.setMaximumWidth(300); self.bar.hide()
        self.cancel_btn = QPushButton(tr("status.cancel")); self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(lambda: self.worker and self.worker.cancel())
        self.statusBar().addPermanentWidget(self.bar); self.statusBar().addPermanentWidget(self.cancel_btn)
        self.statusBar().showMessage(tr("status.ready"))
        self._menus()

    def _dock(self, title, widget, area):
        dock = QDockWidget(title, self); dock.setWidget(widget); dock.setMinimumWidth(240)
        self.addDockWidget(area, dock)

    def _act(self, menu, key, slot, shortcut=None):
        a = QAction(tr(key), self); a.triggered.connect(slot)
        if shortcut: a.setShortcut(QKeySequence(shortcut))
        menu.addAction(a); return a

    def _menus(self):
        f = self.menuBar().addMenu(tr("menu.file"))
        self._act(f, "act.new", self.new_project, "Ctrl+N"); self._act(f, "act.open", self.open_project, "Ctrl+O")
        self._act(f, "act.import", self.import_media, "Ctrl+I"); self._act(f, "act.save", self.save_project, "Ctrl+S")
        self._act(f, "act.save_as", lambda: self.save_project(True), "Ctrl+Shift+S")
        self._act(f, "act.export", self.export_dialog, "Ctrl+E"); self._act(f, "act.quit", self.close, "Ctrl+Q")
        e = self.menuBar().addMenu(tr("menu.edit"))
        self._act(e, "act.undo", self.undo, "Ctrl+Z"); self._act(e, "act.redo", self.redo, "Ctrl+Y")
        self._act(e, "act.split", self.timeline.split_at_playhead); self._act(e, "act.delete", self.timeline.delete_selected)
        self._act(e, "act.zoom_in", lambda: self.timeline.zoom(1.3), "Ctrl+="); self._act(e, "act.zoom_out", lambda: self.timeline.zoom(1 / 1.3), "Ctrl+-")

    # ---------- medya ----------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls(): ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls(): self._import(u.toLocalFile())

    def import_media(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("act.import"), "", tr("dlg.media_filter"))
        for f in files: self._import(f)

    def _import(self, path):
        try:
            info = probe(path)
        except Exception as e:
            return self._error(e)
        if path not in self.project.media: self.project.media.append(path)
        it = QListWidgetItem(f"{os.path.basename(path)}  ({info.duration:.1f} sn)")
        it.setData(Qt.UserRole, path); self.media_list.addItem(it)
        if len(self.project.timeline.tracks[0].clips) == 0: self.add_to_timeline(path)

    def add_to_timeline(self, path):
        info = probe(path); tl = self.project.timeline
        self.history.checkpoint("Klip ekle")
        tl.add_clip(tl.tracks[0].id, Clip(path, 0, info.duration, tl.tracks[0].clips[-1].end if tl.tracks[0].clips else 0))
        self.player.setSource(QUrl.fromLocalFile(path)); self._edited()

    # ---------- düzenleme ----------
    def _edited(self):
        self.timeline.setMinimumWidth(0); self.timeline.update()

    def undo(self):
        self.history.undo(); self.timeline.update()

    def redo(self):
        self.history.redo(); self.timeline.update()

    # ---------- proje ----------
    def new_project(self):
        self.project = Project(); self.history = History(self.project.timeline)
        self.timeline.set_timeline(self.project.timeline, self.history); self.media_list.clear()

    def save_project(self, as_new=False):
        path = self.project.path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, tr("act.save"), "", tr("dlg.project_filter"))
            if not path: return
            if not path.endswith(".vlab"): path += ".vlab"
        try:
            self.project.save(path); self.recent.add(path, self.project.name)
        except Exception as e: self._error(e)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("act.open"), "", tr("dlg.project_filter"))
        if not path: return
        try:
            self.project = Project.load(path); self.history = History(self.project.timeline)
            self.timeline.set_timeline(self.project.timeline, self.history)
            self.media_list.clear()
            for m in self.project.media:
                it = QListWidgetItem(os.path.basename(m)); it.setData(Qt.UserRole, m); self.media_list.addItem(it)
            self.recent.add(path, self.project.name)
        except Exception as e: self._error(e)

    # ---------- sessizlik ----------
    def _params(self) -> SilenceParams:
        v = {k: w.value() for k, w in self.sp.items()}; v["cut_ratio"] /= 100
        return SilenceParams(**v)

    def _target_clip(self):
        tl = self.project.timeline
        c = next((c for t in tl.tracks for c in t.clips if c.id == self.timeline.selected), None)
        return c or (tl.tracks[0].clips[0] if tl.tracks[0].clips else None)

    def analyze_silence(self):
        clip = self._target_clip()
        if not clip: return
        self._run(tr("status.analyzing"), lambda prog, cancel: frame_levels_db(
            (prog(0.0) or ch for ch in stream_pcm(clip.media_path, 16000, 10.0)), 16000), self._levels_ready)

    def _levels_ready(self, levels):
        self.levels = levels; self._refresh_silences()

    def _refresh_silences(self, *_):
        if self.levels is None: return
        self.silences = find_silences(self.levels, self._params())
        self.sil_list.blockSignals(True); self.sil_list.clear()
        for s in self.silences:
            it = QListWidgetItem(f"{s.cut_start:.2f} – {s.cut_end:.2f} sn  ({s.cut_duration:.2f} sn)")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(Qt.Checked); self.sil_list.addItem(it)
        self.sil_list.blockSignals(False)
        self._overlay()
        self.statusBar().showMessage(f"{len(self.silences)} sessizlik" if self.silences else tr("silence.none"))

    def _silence_toggled(self, item):
        self.silences[self.sil_list.row(item)].enabled = item.checkState() == Qt.Checked; self._overlay()

    def _overlay(self):
        clip = self._target_clip()
        off = clip.start - clip.source_in if clip else 0
        self.timeline.overlays = [(s.cut_start + off, s.cut_end + off, QColor(255, 77, 79, 90 if s.enabled else 25))
                                  for s in self.silences]
        self.timeline.update()

    def apply_silence(self):
        clip = self._target_clip()
        if not clip or not self.silences: return
        tl = self.project.timeline; ids = [t.id for t in tl.tracks if t.kind == "video"]
        self.history.checkpoint("Sessizlikleri kes")
        base_start, base_in, speed = clip.start, clip.source_in, clip.speed
        for s in sorted((s for s in self.silences if s.enabled), key=lambda s: s.cut_start, reverse=True):
            a = base_start + (s.cut_start - base_in) / speed; b = base_start + (s.cut_end - base_in) / speed
            tl.remove_range(ids, a, b, ripple=True)       # sondan başa: önceki konumlar bozulmaz
        self.silences, self.levels = [], None; self.sil_list.clear(); self.timeline.overlays = []; self.timeline.update()

    # ---------- dışa aktarma ----------
    # ---------- ortak ----------
    def _run(self, msg, fn, on_done):
        if self.worker and self.worker.isRunning(): return
        self.statusBar().showMessage(msg); self.bar.setValue(0); self.bar.show(); self.cancel_btn.show()
        self.worker = Worker(fn)
        self.worker.progress.connect(lambda f, r: (self.bar.setValue(int(f * 100)),
                                                   self.bar.setFormat(f"%p%  ~{int(r)} sn" if r else "%p%")))
        self.worker.done.connect(lambda res: (self._finish(), on_done(res)))
        self.worker.failed.connect(lambda m: (self._finish(), self.statusBar().showMessage(tr("status.error", msg=m))))
        self.worker.start()

    def _finish(self):
        self.bar.hide(); self.cancel_btn.hide()

    def _error(self, e):
        QMessageBox.warning(self, tr("app.title"), tr("status.error", msg=str(e)))
