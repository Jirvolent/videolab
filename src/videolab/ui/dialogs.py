"""Ortak diyaloglar: onay listesi, metin, dışa aktarma seçenekleri, toplu işlem."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDoubleSpinBox, QLineEdit, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout)

from ..core.branding import Branding
from ..core.voice_prep import VoiceOptions
from ..export.exporter import ASPECTS, RESOLUTIONS, TRANSITIONS, ExportSettings
from ..export.voicefx import PRESET_LABELS


class ChecklistDialog(QDialog):
    """Algılananları tek tek onaylatır (küfür, dolgu sözcüğü, tekrar çekim, sessizlik…)."""
    def __init__(self, parent, title: str, items: list[str], hint: str = ""):
        super().__init__(parent); self.setWindowTitle(title); self.resize(520, 480)
        lay = QVBoxLayout(self)
        if hint: lay.addWidget(QLabel(hint))
        self.list = QListWidget(); lay.addWidget(self.list)
        for t in items:
            it = QListWidgetItem(t); it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        row = QHBoxLayout()
        for label, state in (("Hepsini seç", Qt.Checked), ("Hiçbirini seçme", Qt.Unchecked)):
            b = QPushButton(label); b.clicked.connect(lambda _, s=state: self._all(s)); row.addWidget(b)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); lay.addWidget(bb)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)

    def _all(self, s):
        for i in range(self.list.count()): self.list.item(i).setCheckState(s)

    def checked(self) -> list[int]:
        return [i for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]


class TextDialog(QDialog):
    def __init__(self, parent, title: str, text: str, editable: bool = False):
        super().__init__(parent); self.setWindowTitle(title); self.resize(560, 420)
        lay = QVBoxLayout(self); self.edit = QPlainTextEdit(text); self.edit.setReadOnly(not editable); lay.addWidget(self.edit)
        b = QPushButton("Panoya kopyala"); b.clicked.connect(lambda: self.edit.selectAll() or self.edit.copy()); lay.addWidget(b)
        bb = QDialogButtonBox(QDialogButtonBox.Close); bb.rejected.connect(self.reject); lay.addWidget(bb)


class WordEditDialog(QDialog):
    """Metinden düzenleme: silmek istediğiniz kelimeleri seçin; videodan da kesilir."""
    def __init__(self, parent, words):
        super().__init__(parent); self.setWindowTitle("Metinden Düzenle"); self.resize(600, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Silinecek kelimeleri seçin (Ctrl/Shift ile çoklu seçim)."))
        self.list = QListWidget(); self.list.setSelectionMode(QListWidget.ExtendedSelection)
        for w in words: self.list.addItem(f"[{w.start:7.2f}]  {w.text}")
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); lay.addWidget(bb)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)

    def selected(self) -> set[int]:
        return {self.list.row(i) for i in self.list.selectedItems()}


class ExportDialog(QDialog):
    def __init__(self, parent, has_music: bool, has_follow: bool, has_subs: bool):
        super().__init__(parent); self.setWindowTitle("Dışa Aktar"); form = QFormLayout(self)
        self.container = QComboBox(); self.container.addItems(["mp4", "mov", "mkv"])
        self.codec = QComboBox(); self.codec.addItems(["h264", "h265"])
        self.res = QComboBox(); self.res.addItems(list(RESOLUTIONS)); self.res.setCurrentText("1080p")
        self.aspect = QComboBox(); self.aspect.addItems(list(ASPECTS))
        self.fps = QComboBox(); self.fps.addItems(["24", "30", "60"]); self.fps.setCurrentText("30")
        self.hw = QComboBox(); self.hw.addItems(["none", "nvenc", "qsv", "amf"])
        self.crf = QSpinBox(); self.crf.setRange(14, 32); self.crf.setValue(20)
        self.duck = QCheckBox("Konuşma varken müziği kıs (ducking)"); self.duck.setChecked(has_music); self.duck.setEnabled(has_music)
        self.loud = QCheckBox("Ses seviyesini YouTube'a göre normalleştir (-14 LUFS)")
        self.stab = QCheckBox("Görüntü sabitleme (deshake)"); self.color = QCheckBox("Otomatik renk/kontrast")
        self.follow = QCheckBox("9:16 yüz takibi uygula"); self.follow.setChecked(has_follow); self.follow.setEnabled(has_follow)
        self.subs = QCheckBox("Altyazıyı videoya göm"); self.subs.setChecked(has_subs); self.subs.setEnabled(has_subs)
        for label, w in (("Biçim", self.container), ("Kodek", self.codec), ("Çözünürlük", self.res), ("En/boy", self.aspect),
                         ("FPS", self.fps), ("Donanım hızlandırma", self.hw), ("Kalite (CRF, düşük=iyi)", self.crf)):
            form.addRow(label, w)
        for w in (self.duck, self.loud, self.stab, self.color, self.follow, self.subs): form.addRow(w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); form.addRow(bb)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)

    def settings(self, output: str) -> ExportSettings:
        return ExportSettings(output, container=self.container.currentText(), codec=self.codec.currentText(),
                              resolution=self.res.currentText(), aspect=self.aspect.currentText(),
                              fps=int(self.fps.currentText()), hw=self.hw.currentText(), crf=self.crf.value(),
                              ducking=self.duck.isChecked(), loudnorm=self.loud.isChecked(),
                              stabilize=self.stab.isChecked(), auto_color=self.color.isChecked())


class BatchDialog(QDialog):
    """Birden fazla videoyu aynı otomatik düzenleme ayarlarıyla işler."""
    def __init__(self, parent):
        super().__init__(parent); self.setWindowTitle("Toplu İşlem"); self.resize(560, 460)
        lay = QVBoxLayout(self); self.files: list[str] = []; self.outdir = ""
        self.list = QListWidget(); lay.addWidget(self.list)
        b1 = QPushButton("Video ekle…"); b1.clicked.connect(self._add); lay.addWidget(b1)
        b2 = QPushButton("Çıktı klasörü seç…"); b2.clicked.connect(self._out); lay.addWidget(b2)
        self.sil = QCheckBox("Sessizlikleri temizle"); self.sil.setChecked(True)
        self.fil = QCheckBox("Dolgu sözcüklerini temizle (ııı, um…)"); self.prof = QCheckBox("Küfürleri bip ile sansürle")
        self.breath = QCheckBox("Nefesleri azalt"); self.clicks = QCheckBox("Ağız seslerini (tıkırtı) azalt")
        self.tone = QComboBox(); self.tone.addItem("Ton eşitleme: kapalı", None)
        for k, v in PRESET_LABELS.items(): self.tone.addItem("Ton eşitleme: " + v, k)
        for w in (self.sil, self.fil, self.prof, self.breath, self.clicks, self.tone): lay.addWidget(w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); lay.addWidget(bb)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)

    def voice(self) -> VoiceOptions:
        return VoiceOptions(breath=self.breath.isChecked(), mouth_clicks=self.clicks.isChecked(), preset=self.tone.currentData())

    def _add(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Videolar", "", "Video (*.mp4 *.mov *.mkv *.avi *.webm)")
        for f in fs: self.files.append(f); self.list.addItem(f)

    def _out(self):
        self.outdir = QFileDialog.getExistingDirectory(self, "Çıktı klasörü") or self.outdir


class BrandingDialog(QDialog):
    """Intro/outro yuvası: kendi videolarınızı seçin; her videonun başına/sonuna otomatik eklenir."""
    def __init__(self, parent, b: Branding):
        super().__init__(parent); self.setWindowTitle("Intro / Outro"); self.resize(560, 260); form = QFormLayout(self)
        self.intro = QLineEdit(b.intro_path); self.outro = QLineEdit(b.outro_path)
        for label, edit in (("Intro videosu", self.intro), ("Outro videosu", self.outro)):
            row = QHBoxLayout(); row.addWidget(edit); btn = QPushButton("Seç…")
            btn.clicked.connect(lambda _, e=edit: e.setText(QFileDialog.getOpenFileName(self, "Video", "", "Video (*.mp4 *.mov *.mkv *.webm)")[0] or e.text()))
            row.addWidget(btn); form.addRow(label, row)
        self.use_intro = QCheckBox("Her videonun başına intro ekle"); self.use_intro.setChecked(b.intro_enabled)
        self.use_outro = QCheckBox("Her videonun sonuna outro ekle"); self.use_outro.setChecked(b.outro_enabled)
        self.trans = QComboBox()
        for k, v in TRANSITIONS.items(): self.trans.addItem(v, k)
        self.trans.setCurrentIndex(max(0, self.trans.findData(b.transition)))
        self.dur = QDoubleSpinBox(); self.dur.setRange(0.1, 3.0); self.dur.setSingleStep(0.1); self.dur.setValue(b.transition_dur)
        for w in (self.use_intro, self.use_outro): form.addRow(w)
        form.addRow("Geçiş", self.trans); form.addRow("Geçiş süresi (sn)", self.dur)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); form.addRow(bb)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)

    def value(self) -> Branding:
        return Branding(self.intro.text().strip(), self.outro.text().strip(), self.use_intro.isChecked(),
                        self.use_outro.isChecked(), self.trans.currentData(), self.dur.value())


class TransitionDialog(QDialog):
    def __init__(self, parent, title="Geçiş Uygula"):
        super().__init__(parent); self.setWindowTitle(title); form = QFormLayout(self)
        self.trans = QComboBox()
        for k, v in TRANSITIONS.items(): self.trans.addItem(v, k)
        self.trans.setCurrentIndex(self.trans.findData("fade"))
        self.dur = QDoubleSpinBox(); self.dur.setRange(0.1, 3.0); self.dur.setSingleStep(0.1); self.dur.setValue(0.5)
        form.addRow("Geçiş", self.trans); form.addRow("Süre (sn)", self.dur)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); form.addRow(bb)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)


BREATH_LEVELS = {"Doğal (nefes duyulur, kısık) −14 dB": -14.0, "Güçlü −24 dB": -24.0, "Neredeyse sessiz −45 dB": -45.0}


class VoiceDialog(QDialog):
    """Ses iyileştirme: nefes, ağız sesi, ton eşitleme."""
    def __init__(self, parent, o: VoiceOptions):
        super().__init__(parent); self.setWindowTitle("Ses İyileştirme"); self.resize(480, 360); form = QFormLayout(self)
        self.breath = QCheckBox("Nefesleri azalt"); self.breath.setChecked(o.breath)
        self.level = QComboBox()
        for k, v in BREATH_LEVELS.items(): self.level.addItem(k, v)
        self.level.setCurrentIndex(max(0, self.level.findData(o.breath_gain_db)))
        self.find_btn = QPushButton("Nefesleri bul ve incele…")
        self.clicks = QCheckBox("Ağız seslerini / tıkırtıları azalt"); self.clicks.setChecked(o.mouth_clicks)
        self.preset = QComboBox(); self.preset.addItem("Kapalı", None)
        for k, v in PRESET_LABELS.items(): self.preset.addItem(v, k)
        self.preset.setCurrentIndex(max(0, self.preset.findData(o.preset)))
        self.auto_eq = QCheckBox("Otomatik EQ (sesinizin tonunu ölç, dengele)"); self.auto_eq.setChecked(o.auto_eq)
        self.denoise = QCheckBox("Arka plan gürültüsünü azalt"); self.denoise.setChecked(o.denoise)
        form.addRow(self.breath); form.addRow("Nefes kısma", self.level); form.addRow(self.find_btn); form.addRow(self.clicks)
        form.addRow("Ton eşitleme", self.preset); form.addRow(self.auto_eq); form.addRow(self.denoise)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); form.addRow(bb)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)

    def value(self) -> VoiceOptions:
        return VoiceOptions(breath=self.breath.isChecked(), breath_gain_db=self.level.currentData(), mouth_clicks=self.clicks.isChecked(),
                            preset=self.preset.currentData(), auto_eq=self.auto_eq.isChecked(), denoise=self.denoise.isChecked())
