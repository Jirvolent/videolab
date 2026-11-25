"""Arka plan işleri: arayüz donmaz, hatalar uygulamayı kapatmaz."""
import threading
import traceback

from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    progress = Signal(float, object)     # 0..1, kalan saniye (veya None)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        """fn(progress_cb, cancel_event) -> sonuç"""
        super().__init__()
        self.fn = fn
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            self.done.emit(self.fn(lambda f, r=None: self.progress.emit(float(f), r), self.cancel_event))
        except InterruptedError:
            self.failed.emit("İptal edildi")
        except Exception as e:                       # uygulama çökmesin
            traceback.print_exc()
            self.failed.emit(str(e))
