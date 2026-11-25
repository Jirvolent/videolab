# VideoLab

Açık kaynak, çevrimdışı çalışan, yapay zekâ destekli masaüstü video düzenleyici.
Python · PySide6 · FFmpeg · faster-whisper · OpenCV. Arayüz Türkçe; çoklu dile uygun yapı.

> **Durum: alfa (v0.4).** Motor (kesme, dışa aktarma, sessizlik, küfür, ses işleme…) otomatik testlerle doğrulandı.
> Masaüstü arayüzü yazıldı ama henüz yeterince denenmedi; hata görürseniz Issue açın.

## Özellikler
- Çok kanallı timeline, bölme/silme/taşıma, geri al/ileri al, JSON proje, otomatik kayıt
- Dışa aktarma: MP4/MOV/MKV, H.264/H.265, 720p–4K, 24/30/60 fps, 16:9 / 9:16 / 1:1
- Sessizlik temizleme, dolgu sözcüğü (ııı, um) temizleme, tekrar çekim bulma, metinden düzenleme
- Türkçe/İngilizce küfür algılama ve bip/sessize alma
- Altyazı: otomatik, SRT içe/dışa aktarma, kelime vurgulu, konuşmacı renkli
- Klip geçişleri (27 tür), meme ve ses efekti kütüphanesi, intro/outro yuvası
- Ses: müzik, ducking, LUFS, nefes ve ağız sesi azaltma, konuşma tonu eşitleme, otomatik EQ
- Konuşmacı ayırma (anahtarsız), 9:16 yüz takibi, proxy önizleme, toplu işlem, eklenti sistemi

Ayrıntılı durum için: [docs/ROADMAP.md](docs/ROADMAP.md) · Mimari: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Kurulum ve çalıştırma
[INSTALL.md](INSTALL.md) dosyasına bakın. Kısaca: Python 3.11+, FFmpeg, `pip install -r requirements.txt`,
ardından `PYTHONPATH=src python -m videolab` (Windows PowerShell: `$env:PYTHONPATH="src"; python -m videolab`).

## Test
`python -m unittest discover -s tests -v` (FFmpeg gerekir; PySide6 gerekmez)

## Lisans
MIT. Üçüncü taraf bileşenler (FFmpeg, Qt, modeller) için: [docs/LICENSES.md](docs/LICENSES.md)
