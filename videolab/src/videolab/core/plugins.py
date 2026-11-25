"""Eklenti sistemi: ~/.videolab/plugins/*.py dosyaları `register(api)` fonksiyonu sunar.
Bozuk bir eklenti uygulamayı çökertmez; hata listelenir."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class PluginAPI:
    analyzers: dict[str, Callable] = field(default_factory=dict)    # ad -> fn(words) -> list[Span]
    actions: dict[str, Callable] = field(default_factory=dict)      # menü adı -> fn(window)
    video_filters: dict[str, Callable] = field(default_factory=dict)  # ad -> fn(ExportSettings) -> ffmpeg vf parçası

    def add_analyzer(self, name: str, fn: Callable) -> None: self.analyzers[name] = fn
    def add_action(self, name: str, fn: Callable) -> None: self.actions[name] = fn
    def add_video_filter(self, name: str, fn: Callable) -> None: self.video_filters[name] = fn


def load_plugins(directory: str | Path) -> tuple[PluginAPI, list[str]]:
    api, errors = PluginAPI(), []
    d = Path(directory)
    if not d.is_dir():
        return api, errors
    for f in sorted(d.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"videolab_plugin_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            mod.register(api)
        except Exception as e:
            errors.append(f"{f.name}: {e}")
    return api, errors
