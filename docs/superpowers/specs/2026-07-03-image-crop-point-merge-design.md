# Görsel Adımı: Kırpma + Nokta Seçme Birleştirmesi — Tasarım

**Tarih:** 2026-07-03
**Kapsam:** AI Test Generator — görsel (image) adım tipi, Web + Desktop (Mobil'de görsel adım UI'da
zaten gizli, kapsam dışı).

## Problem

Görsel adım eklerken bugün iki ayrı, birbirinden bağımsız mod var:

- **Bölge Kırp:** Küçük, ayırt edici bir alan kırpılıp saklanıyor. Çalışma zamanında OpenCV
  çoklu-ölçek template matching (`_find_image_on_screen`) ile ekranda aranıyor — küçük/ayırt edici
  görsel olduğu için eşleştirme sağlam, ama her zaman eşleşen alanın **merkezine** tıklanıyor.
  Alan içinde belirli bir noktaya (ör. büyük bir kartın köşesindeki küçük bir X butonuna) tıklamak
  mümkün değil.
- **Nokta İşaretle:** TÜM sayfanın ekran görüntüsü saklanıyor, kullanıcı üzerinde 1+ nokta
  işaretliyor. Çalışma zamanında `pyautogui.locateOnScreen` ile bu koca görselin **bütünü** ekranda
  aranıyor (tek ölçekli, hassas piksel eşleşmesi gerektiriyor) — sayfa kaydırılmış veya pencere
  boyutu değişmişse eşleşme kolayca bozuluyor.

Ayrıca inceleme sırasında gizli bir bug bulundu: `_find_b64_on_screen` (ve dolayısıyla
`_find_b64_on_screen_web`) fonksiyonu, yalnızca Desktop şablonlarında tanımlanan `_WINDOW_TITLE`
değişkenine referans veriyor. Web şablonlarında bu değişken hiç tanımlı değil → Web platformunda
"Bölge Kırp" tıklama adımı çalıştırıldığında `NameError` ile patlıyor. Web platformunda "Nokta
İşaretle" modu ise `_image_step_code`'un web dalında `click_x`/`click_y` hiç kontrol edilmediği
için zaten hiç çalışmıyor (sessizce crop-mantığına düşüyor).

## Çözüm

İki modu tek bir sıralı akışta birleştiriyoruz: **önce kırp (ayırt edici, sağlam eşleşen küçük
alan), sonra o kırpılmış alan üzerinde nokta(lar) işaretle.** Çalışma zamanında: kırpılan küçük
görsel çoklu-ölçek eşleştirmeyle ekranda bulunur, işaretlenen nokta bu eşleşen alana göre normalize
edilip mutlak ekran koordinatına çevrilir ve oraya tıklanır. Böylece hem eşleştirme sağlamlığı
(küçük/ayırt edici template) hem de serbest nokta hassasiyeti aynı anda elde edilir.

### Frontend akışı (`ai-generator.html`)

- `showCropModal(b64)` artık **tek** bir başlangıç aşaması açar: "Alan Seç". Mevcut dikdörtgen
  çizme mantığı (`onCropDown/Move/Up`) değişmeden kalır.
- `tabCrop`/`tabPoint` sekmeleri ve `setModalMode()` kaldırılır. Yerine dikdörtgen çizilmeden aktif
  olmayan bir "İleri: Nokta Seç →" butonu gelir (şu anki `btnCropConfirm`'in yerini alır).
- "İleri" tıklanınca: mevcut `confirmCrop()`'taki kırpma mantığı (canvas'a `sx,sy,sw,sh` ile çizip
  `croppedB64` üretme) çalışır, ama step OLUŞTURMAZ — modal Aşama 2'ye geçer: canvas'ta artık
  sadece kırpılan küçük görsel, modal boyutuna göre büyütülmüş halde gösterilir (küçük ikonlarda
  hassas nokta seçimi için).
- Aşama 2: mevcut nokta işaretleme mantığı (`onPointClick`, `_drawAllPoints`, `_updatePointsUI`,
  `pointsList`, numaralı kırmızı işaretçiler) aynen yeniden kullanılır, sadece artık `_screenImg`
  yerine kırpılmış görsele (`_croppedImg`) bağlıdır. "← Geri" butonu Aşama 1'e (dikdörtgen yeniden
  çizmeye) döner, mevcut kırpma seçimini sıfırlamaz sadece yeniden çizmeye izin verir.
- Onayla (`confirmPoints`) her nokta için bir `StepItem` üretir:
  `{ type:"image", content:"Nokta N tıkla", b64: croppedB64 (küçük!), action:"click",
  click_x: pt.ox, click_y: pt.oy, status:null }` — `click_x/y` artık kırpılan alana göre pikseldir
  (tam sayfaya göre DEĞİL).
- Modal'ı kapatma / boş adımı temizleme (`cancelCrop`) davranışı her iki aşamada da korunur.
- Adım oluştuktan sonraki "Sol Tık / Çift Tık / Sağ Tık / Görünmeli" action dropdown'ı
  (`renderStepRow` içinde) değişmeden kalır — capture akışına dokunmuyoruz, `assert` seçildiğinde
  `click_x/y` zaten kullanılmıyor.

### Backend eşleştirme mantığı (`ai_test_generator_router.py`)

- `_find_image_on_screen()` fonksiyonuna `return_bbox: bool = False` parametresi eklenir. `True`
  olduğunda merkez nokta yerine eşleşen alanın `(x, y, w, h)` dikdörtgenini döndürür (mevcut
  DPI-farkındalıklı çoklu-ölçek OpenCV eşleştirmesi aynen kullanılır, sadece dönüş değeri değişir).
  Var olan çağıranlar (`_find_b64_on_screen`) parametre vermeden eski davranışı (merkez nokta) almaya
  devam eder.
- Yeni fonksiyon `_find_b64_and_click_point(b64_data, click_x, click_y, action="click",
  threshold=0.80, timeout=10)`:
  - `b64_data`'yı PIL ile açıp orijinal genişlik/yükseklik alır, `click_x/click_y`'yi normalize eder
    (`norm_x = click_x/w`, `norm_y = click_y/h`).
  - `_find_b64_on_screen`'deki gibi zaman aşımına kadar giderek düşen eşikle (`threshold` →
    `max(0.50, threshold - ...)`) tekrar dener, her denemede
    `_find_image_on_screen(tmp_path, threshold=conf, region=..., return_bbox=True)` çağırır.
  - Eşleşme bulunca: `abs_x = bbox.x + norm_x*bbox.w`, `abs_y = bbox.y + norm_y*bbox.h`, `pyautogui`
    ile `click`/`doubleClick`/`rightClick` uygular, `True` döner.
  - Zaman aşımında `False` döner (adım `STEP_FAIL` olarak işaretlenir, mevcut hata deseniyle aynı).
  - Arama bölgesini kısıtlamak için `_get_window_region()` kullanılır (Desktop'ta pencere
    dikdörtgeni, Web'de her zaman `None` → tam ekran arar).
- Eski `_find_b64_and_click_at` (tam-sayfa `pyautogui.locateOnScreen` tabanlı, tek ölçekli)
  fonksiyonu **silinir** — yeni fonksiyon hem küçük kırpılmış görseller hem de (geriye dönük
  uyumluluk için) eski tam-sayfa görseller için aynı formülle çalışır, ayrı bir yola gerek yok.
- **Bug fix:** `_get_window_region()` içindeki `_wt = _WINDOW_TITLE` erişimi zaten `NameError`'ı
  yakalayıp `None` döndürüyor (bu kısım sorunsuz). Ama `_find_b64_on_screen()` içindeki çıplak
  `if _WINDOW_TITLE and _region is None:` ve `if _WINDOW_TITLE:` satırları web script'lerinde
  `NameError` fırlatıyor — bunlar `'_WINDOW_TITLE' in dir() and _WINDOW_TITLE` şeklinde güvenli hale
  getirilecek (kod tabanında zaten kullanılan `"_AI_CONFIG_PATH" in dir()` desenine benzer şekilde).

### `_image_step_code()` birleştirmesi

Desktop ve Web dalları için "tıklama" (assert olmayan) mantığı tek bir ortak şablona indirilir:

- `click_x >= 0` ise → yeni `_find_b64_and_click_point(...)` kullanılır. Bu, hem yeni kırp+nokta
  adımları hem de (geriye dönük uyumluluk) eski tam-sayfa-nokta adımları için aynı şekilde çalışır.
- `click_x < 0` ise → mevcut davranış korunur: `_find_b64_on_screen` (Desktop) /
  `_find_b64_on_screen_web` (Web) + eşleşen alanın merkezine tıkla. Bu, eski "sadece kırp"
  adımlarını (nokta olmadan oluşturulmuş) hâlâ çalışır durumda tutar.
- Tek platform farkı: Desktop dalı öncesinde `_refocus_window()` çağırır, Web dalı çağırmaz —
  bunun dışında üretilen kod birebir aynı yapıda olacak.
- `assert` action'ı hiç değişmiyor (zaten `click_x/y` kullanmıyor).

### Veri modeli

`StepItem` şemasında alan değişikliği YOK — `image_b64`, `click_x`, `click_y`, `action` alanları
zaten var. Sadece `click_x/y`'nin anlamı ("tam sayfaya göre" değil "kırpılan görsele göre") netleşir;
ilgili docstring/yorum güncellenir.

### Geriye dönük uyumluluk

Yeni `_find_b64_and_click_point` fonksiyonu şablon boyutundan bağımsız çalıştığı için (küçük kırpma
veya eski tam-sayfa görüntüsü fark etmeksizin aynı normalize-nokta formülünü uygular), DB'de kayıtlı
eski adımlar ek özel durum kodu gerekmeden çalışmaya devam eder:

- Eski **"sadece kırp"** adımları (`click_x=-1`) → mevcut merkez-tıklama yoluna düşer, davranış
  değişmez.
- Eski **"tam sayfa nokta"** adımları (`click_x>=0`, büyük b64) → yeni `_find_b64_and_click_point`
  yoluna düşer; öncekinden DAHA sağlam çalışır (çoklu-ölçek eşleştirme, eski tek-ölçekli
  `locateOnScreen`'den daha toleranslı).

### Test Planı

1. **Web bug-fix doğrulaması:** Web platformunda alan seç → İleri → kırpılmış alanda nokta
   işaretle → script üret + çalıştır; `NameError` almadan doğru noktaya tıklandığını doğrula (bu,
   Web'de şu an hiç çalışmayan bir senaryo).
2. **Desktop regresyon:** Aynı akışı Desktop'ta tekrarla, mevcut davranışın (artık nokta zorunlu)
   bozulmadığını doğrula.
3. **Çoklu nokta:** Tek kırpmada 3 nokta işaretleyip 3 ayrı adım oluştuğunu, her birinin aynı küçük
   görseli taşıdığını, doğru sırayla ayrı ayrı tıklandığını doğrula.
4. **Geriye dönük uyumluluk:** Elle bir kontrol scriptiyle `StepItem(click_x=-1, image_b64=...)`
   çalıştırıp hâlâ merkeze tıkladığını doğrula (gerçek eski senaryo yoksa sentetik veriyle).
5. **Modal navigasyonu:** "← Geri" ile Aşama 1'e dönüp alanı yeniden seçmenin, modalı kapatıp boş
   adımı temizlemenin (`cancelCrop`) hâlâ çalıştığını doğrula.

## Self-Review Notları

- **Kapsam:** Sadece görsel (image) adım tipinin kırp/nokta capture akışını ve çalışma zamanı
  eşleştirmesini kapsıyor; Mobil platformda görsel adım UI'da zaten gizli olduğu için kapsam dışı
  bırakıldı.
- **Bağımsızlık:** Bu değişiklik, aynı anda devam eden "Adım Çalıştırma & Yorum" planındaki (Task
  7-9) oturum/tek-adım-çalıştırma işiyle bağımsızdır — `_image_step_code()` her iki senaryoda da
  (fresh script veya session-attach script) aynı şekilde üretilen kod parçası olarak kullanılır,
  ekstra bir entegrasyon noktası gerekmez.
- **Tutarlılık:** `_find_b64_and_click_point` imzası, mevcut `_find_b64_on_screen`'in
  threshold/timeout/retry desenini birebir takip ediyor — yeni bir konvansiyon icat edilmiyor.
