# AI Generator: If/Else Dallarında Görsel Yakalama + Sağa/Sola Kaydır

## Bağlam

AI Generator (`backend/WebArayuz/ai-generator.html` + `backend/routers/ai_test_generator_router.py`)
hibrit adım editöründe iki eksiklik var:

1. If/Else adımının then/else dallarına görsel (image) adım eklerken crop/point
   yakalama modalı açılmıyor — adım boş/kırık thumbnail ile ekleniyor, kullanıcı
   manuel doldurmak zorunda kalıyor.
2. Mobile/Web/Desktop kural motorlarının hiçbirinde "sağa kaydır" / "sola kaydır"
   (yatay swipe/scroll) desteği yok. Bu ifadeler yazılınca generic fallback
   devreye girip sessizce aşağı kaydırma kodu üretiyor (yanlış yön, hata yok).

## 1. If/Else Dallarında Görsel Yakalama

### Kök Neden

Görsel yakalama pipeline'ı üst seviye `steps` dizisine düz index (`_captureTargetStepIdx`)
ile yazıyor:
- `removeEmptyImageStep()` → `steps.splice(idx, 1)`
- `confirmPoints()` → `steps.splice(_captureTargetStepIdx, 1, ...newSteps)`
- `confirmDrag()` → `steps.splice(_captureTargetStepIdx, 1, newStep)`

Dal içi diziler (`steps[parentIdx].then_steps` / `else_steps`) bu koddan
ulaşılamıyor. `addImageStep(parentIdx, branch, insertAt)` bu yüzden sadece
`branch` boşken (üst seviye) `startImageCapture()` çağırıyordu; dal içinde
capture'ı hiç tetiklemiyordu (bilinçli olarak, kod içi yorumla belgelenmişti).

### Çözüm

Capture context'i tek `_captureTargetStepIdx` yerine üç parçalı hale getirilecek:
`_captureTargetIdx`, `_captureTargetParentIdx`, `_captureTargetBranch`
(veya eşdeğer bir obje `{ idx, parentIdx, branch }`).

Zaten var olan `_container(parentIdx, branch)` helper'ı (tüm diğer CRUD
fonksiyonlarının kullandığı) capture pipeline'ında da kullanılacak:

- `startImageCapture(idx, parentIdx, branch)` → context'i saklar
- `addImageStep` → `branch` fark etmeksizin her zaman `startImageCapture` çağırır
  (mevcut `if (!branch) startImageCapture(localIdx)` guard'ı kaldırılır)
- `removeEmptyImageStep()` → `_container(parentIdx, branch).splice(idx, 1)`
- `confirmPoints()` → `_container(parentIdx, branch).splice(idx, 1, ...newSteps)`
- `confirmDrag()` → `_container(parentIdx, branch).splice(idx, 1, newStep)`
- `cancelCrop()` → context temizliği aynı kalır, sadece `removeEmptyImageStep`
  üzerinden dolaylı düzelir

### Sonuç

If/Else dalına "+ Görsel" eklemek, üst seviyedeki "Görsel" butonuyla birebir
aynı deneyimi verir: dosya seçilir → crop modal otomatik açılır → bölge/nokta
seçilir → adım(lar) dal içine yazılır.

## 2. Sağa/Sola Kaydır

Mevcut "aşağı/yukarı kaydır" desenleriyle aynı öncelik seviyesinde, generic
`kaydır/scroll/swipe` fallback'inden **önce** yeni regex dalları eklenecek.

**Yön semantiği** (mevcut aşağı/yukarı ile tutarlı — isim = yeni içeriğin
geldiği yön, parmak hareketi ters yönde):
- "sağa kaydır" → sağdaki içerik gelir, parmak sola sürüklenir
- "sola kaydır" → soldaki/sonraki içerik gelir, parmak sağa sürüklenir

### Mobile (`_rule_mobile`, `ai_test_generator_router.py` ~satır 442)

```python
if re.search(r'(?:sa[gğ]a\s*kaydır|swipe\s*right|scroll\s*right)', sl):
    return [f'# {s}', 'driver.swipe(900, 800, 150, 800, 800)', 'time.sleep(0.5)']
if re.search(r'(?:sola\s*kaydır|swipe\s*left|scroll\s*left)', sl):
    return [f'# {s}', 'driver.swipe(150, 800, 900, 800, 800)', 'time.sleep(0.5)']
```

(mevcut aşağı/yukarı kontrollerinden hemen sonra, generic fallback'ten önce)

### Web (`_rule_web`, ~satır 639)

```python
if re.search(r'(?:sa[gğ]a\s*kaydır|scroll\s*right)', sl):
    return [f'# {s}', 'driver.execute_script("window.scrollBy(400, 0);")', 'time.sleep(0.4)']
if re.search(r'(?:sola\s*kaydır|scroll\s*left)', sl):
    return [f'# {s}', 'driver.execute_script("window.scrollBy(-400, 0);")', 'time.sleep(0.4)']
```

### Desktop (`_rule_desktop`, ~satır 779)

pyautogui'nin native `hscroll` fonksiyonu Windows'ta güvenilir değil; standart
Windows konvansiyonu olan Shift+tekerlek kullanılacak:

```python
if re.search(r'(?:sa[gğ]a\s*kaydır|scroll\s*right|swipe\s*right)', sl):
    return [f'# {s}', "_pag.keyDown('shift')", '_pag.scroll(-5)', "_pag.keyUp('shift')", 'time.sleep(0.3)']
if re.search(r'(?:sola\s*kaydır|scroll\s*left|swipe\s*left)', sl):
    return [f'# {s}', "_pag.keyDown('shift')", '_pag.scroll(5)', "_pag.keyUp('shift')", 'time.sleep(0.3)']
```

### Frontend İpucu Panelleri

`ai-generator.html` içindeki mobile/web/desktop hint-grid bölümlerine
"sağa kaydır" / "sola kaydır" örnekleri eklenecek (mevcut "aşağı kaydır"
satırlarının yanına), kullanıcı yeni sözdizimini keşfedebilsin diye.

## Kapsam Dışı

- LLM fallback prompt'undaki (`api_note`) örnek listesi güncellenmeyecek —
  rule engine bu ifadeleri LLM'e düşmeden yakalayacağı için gerekli değil.
- Mobile görsel (image) adımlar hâlâ desteklenmiyor (önceki kısıtlama devam
  ediyor, bu spec'in kapsamı dışında).

## Test Planı

Manuel doğrulama (dev sunucuda):
1. AI Generator'da If/Else adımı ekle → then dalına "+ Görsel" tıkla → crop
   modalın otomatik açıldığını doğrula → bölge seç → adımın dal içine doğru
   b64 ile eklendiğini doğrula. Aynısını else dalı için tekrarla.
2. Mobile/Web/Desktop platformlarının her birinde "sağa kaydır" ve
   "sola kaydır" adımlarını yazıp script üret → üretilen Python kodunda
   doğru yön (mobile: doğru x1/x2 sırası, web: doğru scrollBy işareti,
   desktop: shift+scroll yönü) olduğunu doğrula.
