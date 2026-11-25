# Yol Haritası
Durum: ✅ motor + otomatik test · 🟡 kod yazıldı, canlı denenmedi · ⬜ yapılmadı

| Özellik | Durum | Not |
|---|---|---|
| Timeline, undo/redo, proje kaydı, SQLite son projeler | ✅ | |
| Dışa aktarma (MP4/MOV/MKV, H.264/H.265, 720p–4K, fps, 16:9/9:16/1:1, hız, fade) | ✅ | donanım kodlayıcılar 🟡 |
| Sessizlik temizleme | ✅ | |
| Küfür algılama + bip/sessiz (motor) | ✅ | gerçek transkript 🟡 (faster-whisper gerekir) |
| Dolgu sözcüğü, tekrar çekim, metinden düzenleme | ✅ | Whisper bazen "ııı"yı yazıya dökmez |
| Ducking, müzik karışımı, LUFS | ✅ | |
| SRT, kelime vurgulu altyazı gömme | ✅ | |
| Bölümler, küçük resim, açıklama | ✅ | |
| Proxy, dalga formu verisi | ✅ | dalga formunu timeline'da çizmek ⬜ |
| Toplu işlem / otomatik düzenleme hattı | ✅ | |
| Eklenti sistemi | ✅ | |
| 9:16 yüz takibi | 🟡 | yumuşatma ve kırpma testli; yüz algılama gerçek videoyla denenmedi |
| Ekran/webcam kaydı | 🟡 | komutlar testli, canlı kayıt denenmedi |
| Arayüz (ana pencere, Araçlar menüsü, diyaloglar) | 🟡 | hiç açılmadı |
| Konuşmacı ayırma | ✅ sentetik seslerle | yerleşik MFCC yöntemi gerçek konuşmada denenmedi, benzer seslerde zayıf olabilir; `pip install resemblyzer` ile daha doğrusu (denenmedi) |
| Klip geçişleri (27 tür) | ✅ | |
| Bindirme / meme (V2+) | ✅ | konum/boyut arayüzden ayarlanamıyor, şimdilik varsayılan: ortada %35 |
| Nefes / ağız sesi azaltma | ✅ sentetik seslerle | gerçek nefeslerde hatalı bulgu olabilir; bu yüzden inceleme listesi var |
| Konuşma tonu eşitleme + otomatik EQ | ✅ | zevke bağlı: hazır ayarları kendi sesinizle dinleyin |
| Meme & ses kütüphanesi | ✅ motor · 🟡 panel | |
| Intro/outro yuvası (otomatik ekleme) | ✅ motor · 🟡 diyalog | |
| Yazı/logo bindirme arayüzü, kırpma aracı | ⬜ | logo için bindirme motoru hazır |
| Dalga formu çizimi, Silero VAD, PyInstaller EXE | ⬜ | |
