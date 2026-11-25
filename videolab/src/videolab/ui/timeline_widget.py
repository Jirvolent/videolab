"""Çok kanallı timeline çizimi ve etkileşimi (seçme, taşıma, arama, yakınlaştırma)."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget

from ..core.history import History
from ..core.model import Timeline

TRACK_H, RULER_H, HEADER_W = 46, 24, 54
COLORS = {"video": QColor("#3a6df0"), "audio": QColor("#27a876")}


class TimelineWidget(QWidget):
    seek = Signal(float)
    edited = Signal()
    selection_changed = Signal(object)

    def __init__(self, timeline: Timeline, history: History):
        super().__init__()
        self.tl, self.history = timeline, history
        self.px_per_sec = 40.0
        self.playhead = 0.0
        self.selected: str | None = None
        self.overlays: list[tuple[float, float, QColor]] = []   # sessizlik / küfür işaretleri (timeline sn)
        self._drag = None
        self.setMinimumHeight(RULER_H + TRACK_H * len(timeline.tracks) + 8)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_timeline(self, tl: Timeline, history: History):
        self.tl, self.history, self.selected = tl, history, None
        self.update()

    # ---- koordinat ----
    def t_to_x(self, t): return HEADER_W + t * self.px_per_sec
    def x_to_t(self, x): return max(0.0, (x - HEADER_W) / self.px_per_sec)

    def zoom(self, factor):
        self.px_per_sec = min(2000, max(2, self.px_per_sec * factor))
        self.update()

    def _clip_at(self, pos):
        row = int((pos.y() - RULER_H) // TRACK_H)
        if 0 <= row < len(self.tl.tracks):
            tr = self.tl.tracks[row]
            t = self.x_to_t(pos.x())
            for c in tr.clips:
                if c.start <= t <= c.end:
                    return tr, c
        return None, None

    # ---- çizim ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#16181d"))
        p.setFont(QFont("Segoe UI", 8))
        step = 1 if self.px_per_sec >= 40 else 5 if self.px_per_sec >= 8 else 30
        p.setPen(QColor("#6b7280"))
        t = 0
        while self.t_to_x(t) < self.width():
            x = self.t_to_x(t)
            p.drawLine(int(x), RULER_H - 6, int(x), RULER_H)
            p.drawText(int(x) + 3, RULER_H - 8, f"{int(t // 60):02d}:{int(t % 60):02d}")
            t += step
        for i, tr in enumerate(self.tl.tracks):
            y = RULER_H + i * TRACK_H
            p.fillRect(0, y, HEADER_W, TRACK_H - 2, QColor("#22252c"))
            p.setPen(QColor("#9aa1ad")); p.drawText(8, y + 28, tr.name)
            p.fillRect(HEADER_W, y, self.width(), TRACK_H - 2, QColor("#1e2127"))
            for c in tr.clips:
                r = QRectF(self.t_to_x(c.start), y + 3, c.duration * self.px_per_sec, TRACK_H - 8)
                col = COLORS[tr.kind]
                p.setBrush(col.lighter(130) if c.id == self.selected else col)
                p.setPen(QPen(QColor("#ffffff") if c.id == self.selected else col.darker(140), 1.5))
                p.drawRoundedRect(r, 4, 4)
                p.setPen(Qt.white)
                p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.TextSingleLine,
                           c.media_path.replace("\\", "/").split("/")[-1] + (f"  ×{c.speed:g}" if c.speed != 1 else ""))
        for a, b, col in self.overlays:
            p.fillRect(QRectF(self.t_to_x(a), RULER_H, max(2.0, (b - a) * self.px_per_sec),
                              TRACK_H * len(self.tl.tracks)), col)
        p.setPen(QPen(QColor("#ff4d4f"), 2))
        x = int(self.t_to_x(self.playhead))
        p.drawLine(x, 0, x, self.height())

    # ---- fare / klavye ----
    def mousePressEvent(self, e):
        self.setFocus()
        if e.position().y() < RULER_H:
            self.playhead = self.x_to_t(e.position().x()); self.seek.emit(self.playhead); self.update(); return
        tr, c = self._clip_at(e.position())
        self.selected = c.id if c else None
        self.selection_changed.emit(c)
        if c:
            self.history.checkpoint("Klip taşı")
            self._drag = (c.id, self.x_to_t(e.position().x()) - c.start)
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.LeftButton:
            cid, off = self._drag
            self.tl.move_clip(cid, self.x_to_t(e.position().x()) - off)
            self.update()

    def mouseReleaseEvent(self, _):
        if self._drag:
            self._drag = None
            self.edited.emit()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_S: self.split_at_playhead()
        elif k in (Qt.Key_Delete, Qt.Key_Backspace): self.delete_selected()
        elif k in (Qt.Key_Left, Qt.Key_Right):          # kare kare ilerle
            self.playhead = max(0.0, self.playhead + (1 if k == Qt.Key_Right else -1) / self.tl.fps)
            self.seek.emit(self.playhead); self.update()
        else: super().keyPressEvent(e)

    def split_at_playhead(self):
        targets = [c for t in self.tl.tracks for c in t.clips
                   if (self.selected is None or c.id == self.selected) and c.start < self.playhead < c.end]
        if not targets: return
        self.history.checkpoint("Böl")
        for c in targets: self.tl.split_clip(c.id, self.playhead)
        self.edited.emit(); self.update()

    def delete_selected(self):
        if self.selected:
            self.history.checkpoint("Sil")
            self.tl.delete_clip(self.selected); self.selected = None
            self.edited.emit(); self.update()
