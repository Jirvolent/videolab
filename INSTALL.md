# Kurulum
1. Python 3.11+ ve FFmpeg (ffmpeg + ffprobe PATH'te olmalı). Windows: `winget install Gyan.FFmpeg`
2. `python -m venv .venv && .venv\Scripts\activate` (Linux/macOS: `source .venv/bin/activate`)
3. `pip install -r requirements.txt`
4. Çalıştır: `set PYTHONPATH=src` (Linux: `export PYTHONPATH=src`) ardından `python -m videolab`
5. Testler: `python -m unittest discover -s tests -v`
6. EXE (Faz 10): `pyinstaller --noconfirm --windowed --name VideoLab --paths src src/videolab/__main__.py`
