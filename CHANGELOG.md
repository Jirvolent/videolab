# Değişiklik Günlüğü
## 0.4.0
- Nefes azaltma: gürültü benzeri, konuşmadan belirgin kısık sesleri bulur (kelime içi 's/ş' sesine dokunmaz); kullanıcı listeyi inceler; kazanç zarfı ile yumuşak kısma
- Ağız sesi / tıkırtı azaltma (adeclick)
- Konuşma tonu eşitleme: 4 hazır ayar (doğal, podcast, YouTube, zayıf mikrofon) = yüksek geçiren + de-esser + EQ + kompresör + seviye dengeleme + limiter; isteğe bağlı otomatik EQ (sesin spektrumunu ölçüp dengeler) ve gürültü azaltma
- Toplu işleme ses seçenekleri eklendi
## 0.3.0
- Klip geçişleri (27 xfade geçişi + ses çapraz solması): tek tek veya toplu uygulama; sessizlik kesimleri arasına konmaz
- Bindirme kanalları (V2+): meme görseli / GIF / video; konum, boyut, yumuşak giriş-çıkış
- Meme ve ses efekti kütüphanesi (klasör + etiket + arama), oynatma çubuğuna tek tıkla ekleme
- Intro/outro YUVASI: kendi videolarınızı seçin, her çıktıya otomatik eklenir (geçiş seçilebilir); intro/outro oluşturucu kapsamdan çıkarıldı
- Konuşmacı ayırma (hesapsız): yerleşik MFCC yöntemi + isteğe bağlı Resemblyzer; akışlı çalışır; konuşmacıya göre renkli altyazı ve SRT öneki
## 0.2.0 – ek özellikler
- Dolgu sözcüğü temizleme (ııı/eee/um/uh; "yani/şey/you know" isteğe bağlı), tekrar çekim bulma, metinden düzenleme
- Ducking (sidechain), müzik kanalları (A1/A2) karışımı, LUFS normalizasyonu, deshake, otomatik renk
- SRT içe/dışa aktarma, kelime vurgulu (CapCut tarzı) ASS altyazı ve videoya gömme
- 9:16 yüz takibi (OpenCV) + yumuşatma + dışa aktarmada dinamik kırpma
- Bölüm/zaman damgası önerisi, küçük resim seçici, açıklama üretici
- Proxy önizleme, dalga formu tepe değerleri (akışlı), otomatik düzenleme hattı, toplu işlem kuyruğu
- Eklenti sistemi (~/.videolab/plugins), ekran/webcam kaydı komutları, Araçlar menüsü
## 0.1.0 – çekirdek
- Timeline, undo/redo, proje kaydı, FFmpeg dışa aktarma, sessizlik algılama, küfür motoru, arayüz iskeleti
