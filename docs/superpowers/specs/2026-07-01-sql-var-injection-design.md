# SQL Adımına Değişken Enjeksiyonu — Tasarım

**Tarih:** 2026-07-01
**Kapsam:** AI Test Generator — iki parça:
- **A) SQL→SQL:** `sql` step tipi (Web/Desktop/Mobil ortak, platform bağımsız)
- **B) Ekran değeri→SQL:** Web ve Mobil'de bir elementin görüntülenen değerini (ör. kur değeri,
  müşteri numarası) değişkene okuyup A'daki mekanizmayla SQL sorgusunda kullanma. Desktop bu
  kapsamda yok — DOM olmadığı için OCR + ekran bölgesi seçimi gerekiyor, bu da henüz
  tasarlanmamış "Bölgesel nokta & sürükleme işaretleme" alt projesinin altyapısına bağımlı;
  Desktop değer-okuma o alt proje tamamlanınca aynı `_VARS` mekanizmasına otomatik bağlanacak.

## Bölüm A: SQL→SQL Değişken Aktarımı

### Problem

`backend/routers/ai_test_generator_router.py::_sql_step_code()` fonksiyonu, bir SQL adımının
`sql_query` alanını kod üretimi (codegen) anında `repr(query)` ile üretilen script'e sabit
(literal) string olarak gömüyor. Script içinde zaten bir `_VARS` sözlüğü var (önceki bir SQL/API
adımının `var_name` alanına yazdığı değerleri tutuyor) ama bu değerler `sql_query` metninin içine
hiçbir şekilde enjekte edilemiyor — çünkü gerçek değer ancak script *çalışırken* belli oluyor,
codegen anında değil.

Kullanıcı isteği: bir SELECT sorgusundan `_VARS`'a kaydedilen bir değeri, sonraki bir SQL adımının
sorgu metninin içinde kullanabilmek (ör: `SELECT * FROM orders WHERE user_id = {{user_id}}`).

### Çözüm

Üretilen script'in başına (her platform şablonunda `_VARS = {}` satırının hemen yanına), tek
seferlik, tekrar kullanılabilir bir runtime yardımcı fonksiyon eklenecek:

```python
_VARS = {}  # adımlar arası değişken havuzu
def _sub_vars(_s):
    for _k, _v in _VARS.items():
        _s = _s.replace('{{' + _k + '}}', str(_v))
    return _s
```

`_sql_step_code()` içindeki üç dal da (sqlite / pyodbc / sqlalchemy) `execute()` çağrısını
`_sub_vars(...)` ile sarmalayacak şekilde güncellenecek:

- Öncesi: `_cur_{idx}.execute({query_r})`
- Sonrası: `_cur_{idx}.execute(_sub_vars({query_r}))`

Bu değişiklik `_VARS = {}` satırının bulunduğu 3 platform şablonunda (`_build_mobile_template`,
`_build_web_template`, `_build_desktop_template`) tek noktadan (`_sub_vars` tanımı) uygulanacak; `_sql_step_code`
fonksiyonunda platform ayrımı yapılmıyor, tüm platformlarda aynı şekilde çalışacak.

### Davranış

- `{{degisken}}` deseni sorgu metninde neredeyse birden fazla kez geçse bile hepsi değiştirilir
  (`str.replace` tüm eşleşmeleri kapsar).
- `_VARS` içinde olmayan bir değişken adı kullanılırsa (`{{typo}}` gibi), token olduğu gibi kalır
  ve muhtemelen SQL syntax hatası verir — bu kasıtlı: sessiz başarısızlık yerine görünür, anlaşılır
  bir hata tercih ediliyor.

### Frontend

`ai-generator.html` içindeki `sql_query` textarea'sına (satır ~1796), `var_name` input'undaki
tooltip'e benzer bir ipucu eklenecek: *"İçinde {{değişken}} kullanabilirsiniz — önceki adımlarda
kaydedilen değerlerle değiştirilir."*

### Kapsam Dışı (Bölüm A)

- `api_url` / `api_headers` / `api_body` alanlarında aynı boşluk var ama bu tasarımın kapsamında
  değil — kullanıcı sadece DB/SQL tarafını istedi. `_sub_vars` fonksiyonu ileride API adımına da
  aynı şekilde uygulanabilir (ayrı bir istek olarak).
- Parametrik sorgu (`:param` bind) kullanılmıyor — düz string-replace, kod tabanındaki mevcut
  stille tutarlı. Güvenlik riski var ama bu bir test-otomasyon aracı (kullanıcı kendi test DB'sine
  karşı çalıştırıyor), dış kullanıcı girdisi işlenmiyor.

## Bölüm B: Ekran Değeri → Değişken (Web + Mobil)

### Problem

Kullanıcı, test sırasında ekranda görüntülenen dinamik bir değeri (kur değeri, müşteri numarası
vb.) okuyup `_VARS`'a kaydetmek, sonra bu değeri Bölüm A'daki `{{degisken}}` mekanizmasıyla bir
SQL sorgusunda kullanmak istiyor. Şu an `_VARS`'a yalnızca SQL/API adımlarından yazılabiliyor;
ekrandaki bir elementin değerini okuyup değişkene atayan bir mekanizma yok.

### Çözüm

Mevcut `{{varname}} yaz` deseninin (yazma yönü) aynası olarak, yeni bir **okuma** deseni eklenir —
metin adımı içine yazılır, ek bir UI alanı gerekmez:

```
"Kur Değeri" oku {{kur}}
```

**Kod tabanı düzeltmesi:** `_safe_click`, `_safe_input`, `_safe_assert` (mobil) ve
`_safe_click_web`, `_safe_assert_web` (web) modül seviyesinde gerçek fonksiyon gibi görünse de
aslında `VISION_HELPER` (mobil, satır ~668) ve `VISION_HELPER_WEB` (web, satır ~1131) adlı büyük
üçlü-tırnaklı string sabitlerinin İÇİNDEKİ düz metin — üretilen script'e olduğu gibi kopyalanıyor.
Yeni helper'lar da aynı şekilde bu string sabitlerinin içine eklenecek.

**Web — `_safe_read_web(driver, hint)`** (`VISION_HELPER_WEB` içine, `_safe_assert_web`'in hemen
altına, ~satır 1128 `'''` kapanışından önce):

```python
def _safe_read_web(driver, hint):
    """Hedef metni içeren elementin görünen değerini okur (contains eşleşmesi)."""
    from selenium.webdriver.common.by import By
    for xp in [
        f'//*[contains(normalize-space(.),"{hint}")]',
        f'//*[contains(@value,"{hint}")]',
        f'//*[contains(@placeholder,"{hint}")]',
    ]:
        try:
            el = driver.find_element(By.XPATH, xp)
            val = (el.text or el.get_attribute("value") or "").strip()
            if val:
                return val
        except Exception:
            continue
    print(f"[WARN] Okunamadı: {hint}")
    return ""
```

`_safe_assert_web` ile aynı 3 XPath eşleştirmesini dener, ama assert etmek yerine değeri döndürür.

**Mobil — `_safe_read(driver, text, key_text=None)`** (`VISION_HELPER` içine, `_safe_assert`'in
hemen altına, ~satır 1128 `'''` kapanışından önce):

```python
def _safe_read(driver, text, key_text=None):
    """Hedef metni/içeriği içeren elementin text/content-desc değerini okur (scroll ile arar)."""
    _all_texts = [t for t in [text, key_text] if t]

    def _try_find():
        for _t in _all_texts:
            for _xp in [
                f'//*[contains(@text,"{_t}")]',
                f'//*[contains(@content-desc,"{_t}")]',
            ]:
                try:
                    el = driver.find_element(AppiumBy.XPATH, _xp)
                    val = (el.get_attribute("text") or el.get_attribute("content-desc") or "").strip()
                    if val:
                        return val
                except Exception:
                    continue
        return None

    val = _try_find()
    if val is not None:
        print(f"[OK] Okundu: {text}")
        return val

    print(f"[SCROLL↓] '{text}' aranıyor...")
    driver.swipe(540, 1400, 540, 500, 800); time.sleep(0.7)
    val = _try_find()
    if val is not None:
        return val

    print(f"[SCROLL↑] '{text}' aranıyor...")
    driver.swipe(540, 500, 540, 1400, 800); time.sleep(0.7)
    val = _try_find()
    if val is not None:
        return val

    print(f"[WARN] '{text}' ekranda bulunamadı — değer okunamadı")
    return ""
```

`_safe_assert`'in `@text`/`@content-desc` eşleştirme + scroll mantığını kullanır ama Vision
fallback'i YOK (vision API koordinat döndürüyor, metin değil — bu MVP kapsamı dışı).

**Adım kuralı ekleme:** `_rule_web` (satır ~382) ve `_rule_mobile` (satır ~222) içinde, mevcut
`{{varname}} yaz` regex bloğunun (`_vm`) hemen altına:

```python
# ── "hedef" oku {{varname}} — elementten değer oku ────────────────────────
_rm = re.match(r'^"([^"]+)"\s*oku\s*\{\{(\w+)\}\}\.?\s*$', s, re.IGNORECASE)
if _rm:
    hint, vn = _rm.group(1), _rm.group(2)
    return [
        f'# "{hint}" oku {{{{ {vn} }}}}',
        f"_VARS[{repr(vn)}] = _safe_read_web(driver, {repr(hint)})",  # mobilde: _safe_read(driver, ...)
        f"print(f'[OKU→_VARS] {vn} = {{_VARS[{repr(vn)}]}}')",
    ]
```

(Web'de `_safe_read_web`, Mobil'de `_safe_read` çağrılır — geri kalan kod birebir aynı.)

### Frontend

`ai-generator.html` satır ~1755'teki metin adımı placeholder'ı güncellenecek:

Öncesi: `'Adım açıklaması...  (değişken için: {{değişkenAdı}} yaz)'`
Sonrası: `'Adım açıklaması...  (değişken: {{ad}} yaz / "hedef" oku {{ad}})'`

### Kapsam Dışı (Bölüm B)

- **Desktop okuma** bu tasarımda yok — DOM olmadığı için ekran bölgesi seçimi + OCR gerekiyor, bu
  da "Bölgesel nokta & sürükleme işaretleme" alt projesinin (henüz tasarlanmadı) bölge-seçme
  UI'sine bağımlı. O alt proje bitince Desktop okuma aynı `_VARS`/`_sub_vars` mekanizmasına
  bağlanacak, iş tekrarı olmayacak.
- Vision AI fallback (okuma için) kapsam dışı — vision API şu an koordinat döndürüyor, metin değil.
- Değerin yalnızca sayısal kısmını ayıklama (regex extraction) kapsam dışı — kullanıcı yeterince
  spesifik bir hedef metni yazarak (tam değeri içeren en dar elementi işaret ederek) temiz değer
  almalı.

## Etkilenen Dosyalar

- `backend/routers/ai_test_generator_router.py`:
  - `_sub_vars` helper'ının 3 platform şablonuna eklenmesi (Bölüm A)
  - `_sql_step_code()`'daki 3 `execute()` çağrısının güncellenmesi (Bölüm A)
  - `_safe_read_web` → `VISION_HELPER_WEB` içine (Bölüm B)
  - `_safe_read` → `VISION_HELPER` içine (Bölüm B)
  - `_rule_web` ve `_rule_mobile`'a `"hedef" oku {{var}}` deseni (Bölüm B)
- `backend/WebArayuz/ai-generator.html`:
  - `sql_query` textarea tooltip/placeholder güncellemesi (Bölüm A)
  - Metin adımı placeholder güncellemesi (Bölüm B)

## Test Planı

- **Bölüm A (manuel):** iki SQL adımlı bir Desktop/Web senaryosu — ilk adım
  `SELECT id FROM users LIMIT 1` → `var_name=user_id`; ikinci adım
  `SELECT * FROM orders WHERE user_id = {{user_id}}` → üretilen script çalıştırıldığında ikinci
  sorgunun doğru ID ile çalıştığı loglardan doğrulanacak.
- **Bölüm B (manuel):** Web senaryosunda bir metin adımı `"Kur Değeri" oku {{kur}}` → arkasından
  bir SQL adımı `SELECT * FROM rates WHERE code = {{kur}}` → log çıktısında `[OKU→_VARS] kur = ...`
  satırı ve doğru sorgu sonucunun göründüğü doğrulanacak. Mobil için aynısı bir Appium senaryosuyla
  tekrarlanacak.

## Bilinen Sınırlamalar (final review sonrası eklendi, 2026-07-01)

- **`_safe_read_web` en dar (leaf) eşleşen elementi hedefler**, ama hedef metin sayfada birden çok
  yerde/iç içe geçiyorsa yine de en dıştaki değil en içteki eşleşen elementin TÜM metnini döner —
  eğer o element başka metinlerle birlikte tek bir kapsayıcıdaysa (ör. `<div>Kur Kodu: USD
  32.45</div>` tek element), okunan değer etiket+değeri birlikte içerir. Temiz değer için kullanıcı
  hedefi mümkün olduğunca dar/spesifik yazmalı (mümkünse sadece değeri saran elementin metnini).
- **Boş okuma adımı hata fırlatır** (element bulunamazsa `ValueError` → adım `STEP_FAIL` olarak
  işaretlenir) — bu bilinçli bir tasarım: sessizce boş bir değerin SQL sorgusuna sızıp yanlış-ama-
  makul bir sonuç üretmesindense, adımın görünür şekilde başarısız olması tercih edildi.
- **Genişleyen güven sınırı:** `{{degisken}}` değeri artık sadece önceki bir SQL sorgusundan değil,
  ekrandaki (potansiyel olarak test edilen uygulamanın kendi kullanıcı içeriğinden gelen) rastgele
  metinden de gelebiliyor. Bu metin `_sub_vars` ile parametrik olmayan (düz string-replace) bir SQL
  sorgusuna enjekte ediliyor. Yerel/kendi test veritabanına karşı çalışan bir test-otomasyon aracı
  için kabul edilebilir bulundu, ama ekrandan okunan değerin güvenilir/temiz olduğu varsayımı artık
  "bu değer benim kendi SQL sorgumdan geldi" garantisine dayanmıyor.
