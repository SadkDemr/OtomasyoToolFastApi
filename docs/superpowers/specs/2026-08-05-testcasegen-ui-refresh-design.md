# TestCaseGen — Görsel Yenileme Tasarımı

**Tarih:** 2026-08-05
**Durum:** Onaylandı (spec aşaması)

## Bağlam ve Amaç

`backend/WebArayuz/testcasegen.html` (TestCaseGen sayfası) fonksiyonel olarak tamamlanmış durumda (bkz. `docs/superpowers/specs/2026-08-04-testcasegen-design.md`), ancak görsel olarak zayıf: tüm 4 adım JS template literal'leri içinde ad-hoc `style="..."` satır içi stillerle inşa edilmiş, emoji ikonlar kullanılıyor, tablo/kanban/dropzone gibi bileşenler minimum ("çıplak HTML") görünümde. Bu doküman, **sadece görsel/CSS yenileme + küçük UX iyileştirmeleri** kapsamında bir tasarım tanımlar.

**Kapsam dışı (kesinlikle):** API çağrıları, endpoint'ler, veri modeli, backend davranışı, wizard adım akışının mantığı (4 adım sırası, hangi API hangi adımda çağrılıyor) — bunların hiçbiri değişmiyor. Bu saf bir markup/CSS/ikon yenilemesi + üç adet saf-görsel UX eklemesi (buton spinner state'i, ilerleme çubuğu, drag-over vurgusu).

## Etkilenen Dosya

Sadece `backend/WebArayuz/testcasegen.html`. Dosya kendi `<style>` bloğunu ve kendi `.tcg-*`/`.wf-*` sınıflarını taşıyor; paylaşılan `css/style.css` veya başka hiçbir sayfa değişmiyor. Mevcut paylaşılan bileşenler (`.badge`, `.card-header`/`.card-body`, `.spinner`, `.progress-bar`/`.progress-fill`, `.phone-frame`/`.phone-notch`/`.phone-screen`, `.users-table`) **kullanılacak** ama tanımları değiştirilmeyecek — sadece bu sayfada referans edilecekler.

## Tasarım Yönü

Modern SaaS (Linear/Vercel esintili): bol boşluk, düşük kontrastlı ince kenarlıklar, sadece gerektiğinde yumuşak gölge, tutarlı bir inline-SVG ikon seti (emoji yerine), güçlü tipografik hiyerarşi. Mevcut indigo accent (`--ai-accent`) ve dark-mode token'ları korunuyor.

## Temel Bileşenler (Foundation)

### İkon Seti

Emoji yerine ~20 adet elle yazılmış inline `<svg>` (stroke tabanlı, `currentColor`, 18px, harici kütüphane/build adımı yok). Her ikon bir JS sabiti/fonksiyonu olarak tanımlanır (örn. `ICONS.upload`, `ICONS.link`, `ICONS.camera`, `ICONS.trash`, `ICONS.sparkle`, `ICONS.scale`, `ICONS.flask`, `ICONS.download`, `ICONS.retry`, `ICONS.dragHandle`, `ICONS.chevronRight`, `ICONS.check`, `ICONS.warning`, `ICONS.plus`, `ICONS.folder`, `ICONS.close`) ve template literal'lerde `${ICONS.upload}` şeklinde kullanılır.

Değişecek emoji → ikon eşlemesi: 🔗→link, 📸→camera, 🗑→trash, 🤖→sparkle, ⚖️→scale, 🧪→flask, 📥→download, 🔁→retry, 📂→folder, + →plus.

### Buton Durumları

`.tcg-btn` genişletilir: ikon+etiket kompozisyonu, `disabled` durumunda mevcut `.spinner` (style.css) + "İşleniyor…" metni gösterir (şu anki sadece `opacity:0.5` yerine). Bu, final review'daki "kullanıcı /prioritize sırasında sayfanın donduğunu düşünebilir" bulgusuna saf-görsel bir cevap.

### Kartlar

`.tcg-card` → `.card-header` (ikon + başlık) + `.card-body` ayrımı benimser (style.css'teki `.card-header`/`.card-body` sınıfları referans edilir).

## Adım Bazlı Tasarım

### Header + Oturum Seçici

- Sayfa başlığı yanında sidebar logo tarzı bir ikon-rozet.
- `sessionListPanel`: düz liste yerine küçük kartlardan oluşan panel — klasör ikonu, oturum id'si, ekran/testcase sayıları `.badge` olarak, göreli zaman, silme ikonu hover'da belirir.

### Adım 1 — Ekran Toplama

- Dropzone: ikon + ana metin + yardımcı metin; sürükleme sırasında kenarlık rengi değişiminin yanına hafif tint arka plan eklenir.
- `renderScreenList()`: bordürlü satır listesinden yatay kaydırılabilir **thumbnail kart şeridine** geçer — büyük önizleme, index rozeti (görsel üzerinde overlay), altında not alanı + silme ikonu, sürükleme tutamacı ikonu.
- Canlı ADB paneli: `tcgScreenImage` artık style.css'teki `.phone-frame`/`.phone-notch`/`.phone-screen` sınıflarıyla sarmalanır (şu an bu sayfada kullanılmıyor, `emulator.html` kullanıyor) — çıplak `<img>` yerine gerçek "telefon çerçevesi" görünümü. Bağlan/Yakala butonları ikon+etiket + bağlanıyor/disabled durumları alır.

### Adım 2 — Başlık Çıkarma

- "Başlıkları Çıkar" butonu ikon+spinner; `extractProgress` metni yanına `.progress-bar`/`.progress-fill` eklenir (yüzdelik ilerleme).
- Her ekranın sonucu: aday başlıklar düzenlenebilir "chip" tarzı satırlar olarak render edilir, silme ikonu küçük/hizalı; "+ Başlık Ekle" dropzone'la aynı görsel dilde (dashed ghost-button).
- `parse_error` durumu: amber sol-kenarlıklı, uyarı ikonlu ayrı bir "dikkat" kartı olarak stillendirilir (şu an düz metin).

### Adım 3 — Önceliklendirme (Kanban)

- Kolonlar: renkli üst-accent bar (kırmızı/amber/gri) + başlık yanında sayı rozeti ("High · 4") olan yükseltilmiş kartlar.
- Kanban kartları: metin + gerekçe, önceliğe göre renkli sol kenarlık.
- Boş kolon: "Henüz başlık yok" placeholder metni.
- Sürükleme sırasında hedef kolon `ondragover`'da halka/vurgu efekti alır (şu an sürükleme sırasında hiç görsel geri bildirim yok).

### Adım 4 — Test Case Üretimi

- Başlık checklist: `.badge` ile renkli öncelik rozeti (şu an düz "(high)" metni); zaten test case'i üretilmiş başlıklar küçük bir "✓ üretildi" göstergesi alır.
- Tablo: `.users-table` deseniyle uyumlu header (büyük harf, muted, letter-spacing), satır hover, ihlal (`violations`) satırları arka plan tint'inin yanına sol-kenarlık + uyarı ikonu alır (native `title` tooltip korunur).
- "Excel'e Aktar" butonu `.btn-success` (yeşil) ile görsel olarak ayrılır — wizard'ın bitiş aksiyonu olduğu için "Geri" navigasyon butonundan ayrıştırılır.

## Test / Doğrulama

Bu depoda frontend test runner'ı yok (mevcut kısıt, `docs/superpowers/plans/2026-08-04-testcasegen.md`'deki Global Constraints ile aynı). Doğrulama:

1. JS syntax kontrolü (`node --check` veya eşdeğeri).
2. Mümkün olduğunca gerçek backend'e karşı doğrudan HTTP çağrılarıyla (curl/httpx) markup'ın beklediği veri şekillerinin hâlâ doğru olduğu teyit edilir (bu tasarım hiçbir response şeklini değiştirmiyor, dolayısıyla bu adım düşük risk).
3. Görsel/etkileşimli doğrulama (sürükle-bırak, drag-over vurgusu, spinner state'leri, tema geçişi light/dark) gerçek tarayıcıda insan tarafından yapılmalı — otomatik test yok.

## Riskler / Notlar

- Sayfa tek dosyada ~830 satır; yeniden yazım büyük bir diff üretecek. Uygulama planı, adım adım (foundation → header → step1 → step2 → step3 → step4) küçük parçalara bölünmeli, her adımda mevcut `id`/`class` sözleşmeleri (JS'in `getElementById`/`querySelector` ile aradığı) korunmalı — aksi halde mevcut event handler'lar (`onclick`, `onchange`, drag/drop) kopar.
- İkon seti yeni bir dosya olarak mı (`js/icons.js`) yoksa sayfa içinde mi tanımlanacağı uygulama planında netleştirilecek; sayfa "tek dosya SPA" prensibini koruyorsa muhtemelen sayfa içi kalacak.
- Dark mode: tüm yeni renkler (accent tint'ler, uyarı/başarı kartları) CSS custom property'ler üzerinden tanımlanmalı, sabit hex değer kullanılmamalı (mevcut `--ai-red`/`--ai-yellow`/`--ai-green` gibi token'lar zaten var, bunlar kullanılacak).
