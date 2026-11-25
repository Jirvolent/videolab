"""Geri al / ileri al: Timeline anlık görüntülerine (JSON) dayalı basit ve sağlam yapı."""
from __future__ import annotations

import json
from .model import Timeline


class History:
    def __init__(self, timeline: Timeline, limit: int = 200):
        self.limit = limit
        self._undo: list[tuple[str, str]] = []
        self._redo: list[tuple[str, str]] = []
        self.timeline = timeline

    @staticmethod
    def _snap(tl: Timeline) -> str:
        return json.dumps(tl.to_dict(), sort_keys=True)

    def checkpoint(self, label: str) -> None:
        """Bir düzenleme YAPILMADAN ÖNCE çağrılır."""
        self._undo.append((label, self._snap(self.timeline)))
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, state: str) -> None:
        self.timeline.__dict__.update(Timeline.from_dict(json.loads(state)).__dict__)

    def undo(self) -> str | None:
        if not self._undo:
            return None
        label, state = self._undo.pop()
        self._redo.append((label, self._snap(self.timeline)))
        self._restore(state)
        return label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        label, state = self._redo.pop()
        self._undo.append((label, self._snap(self.timeline)))
        self._restore(state)
        return label

    @property
    def labels(self) -> list[str]:
        return [l for l, _ in self._undo]
