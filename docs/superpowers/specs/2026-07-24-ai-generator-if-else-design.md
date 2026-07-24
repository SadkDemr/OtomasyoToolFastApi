# AI Test Generator: Adım Bazlı If/Else (Koşullu Dallanma) — Tasarım

**Tarih:** 2026-07-24
**Kapsam:** `backend/routers/ai_test_generator_router.py` (`StepItem`, `_generate_steps`) ve
`backend/WebArayuz/ai-generator.html` (adım listesi yönetimi). Mobile/Web/Desktop'ın **üçü birden**
— platform şablon fonksiyonları (`_build_mobile_template`/`_build_web_template`/
`_build_desktop_template`) değişmiyor, çünkü kod üretimi zaten tek ortak `_generate_steps`
fonksiyonunda toplanmış ve şablonlar sadece üretilen `steps_code` string'ini bir `try:` bloğuna
indentleyip sarıyor.

**Nesting sınırı (bilinçli tercih):** Sadece **1 seviye** — bir `condition` adımının `then_steps`/
`else_steps` dalları içine metin/görsel/sql/api/yorum adımı eklenebilir, ama başka bir `condition`
eklenemez. Sınırsız iç içe geçiş, frontend'in path-bazlı (`[3,"then",1,"else",0]` gibi) genel bir
çözüme yeniden yazılmasını gerektirirdi; 1 seviye ile mevcut render/ekle/sil/sürükle fonksiyonları
neredeyse aynı kalıp sadece iki mini-liste ekleniyor.

## Problem

Adım listesi (`steps` / `steps_list`) tamamen doğrusal: her adım sırayla, koşulsuz çalışıyor.
Özellikle görsel (image) adımlarında — bir popup'ın açılıp açılmadığı, bir butonun aktif olup
olmadığı gibi ekran durumuna göre değişen senaryolarda — kullanıcının "eğer bu görsel/element varsa
X yap, yoksa Y yap" şeklinde dallanma ihtiyacı var. Şu an bunun hiçbir karşılığı yok; en yakın şey
`if not _ok_{idx}: raise ...` gibi adım-içi hata kontrolleri, ama bunlar akışı asla dallandırmıyor,
sadece başarısızlıkta script'i durduruyor.

## Çözüm

### 1. Veri Modeli — `StepItem` (`ai_test_generator_router.py:138-160`)

```python
class StepItem(BaseModel):
    type:          str = "text"   # ..., "condition" eklendi
    disabled:      bool = False
    content:       str = ""
    image_b64:      str = ""
    action:        str = "click"
    ...
    # ── Koşullu dallanma (condition) ──────────────────────────────────────
    condition_type: str = ""      # "" | "image_exists" | "element_exists" | "variable_compare"
    compare_var:    str = ""      # variable_compare: {{degisken}} adı (_VARS anahtarı)
    compare_op:     str = ""      # variable_compare: "eq" | "neq" | "contains"
    compare_value:  str = ""      # variable_compare: karşılaştırılacak sabit değer
    then_steps:     list["StepItem"] = []
    else_steps:     list["StepItem"] = []

StepItem.model_rebuild()   # self-referential model — forward ref çözümü için gerekli
```

`condition_type` alanına göre hangi mevcut alanların kullanıldığı:
- `image_exists` → `image_b64` (mevcut görsel yükleme akışı aynen kullanılır)
- `element_exists` → `content` (aranacak metin/element ipucu)
- `variable_compare` → `compare_var` + `compare_op` + `compare_value`

`then_steps`/`else_steps` içindeki elemanlar da `StepItem` — ama üretim tarafında (`_generate_steps`)
`item.type == "condition"` olan iç içe elemanlar reddedilir/yok sayılır (1-seviye sınırı burada
uygulanır, frontend zaten böyle bir adım eklemeyi teklif etmeyecek ama backend da güvenlik için
kontrol eder).

### 2. Kod Üretimi — `_generate_steps` (`ai_test_generator_router.py:3133-3235`)

Mevcut fonksiyon düz bir `for idx, item in enumerate(structured)` döngüsü. Bu, paylaşılan bir sayaç
alan recursive bir yardımcıya çevrilir:

```python
def _steps_to_code(items: list[StepItem], platform: str, counter: list[int], indent: str = "") -> str:
    """items listesini (üst seviye ya da bir then/else dalı) Python koduna çevirir.
    counter=[n] paylaşılan/mutable sayaç — dal içindeki adımlar da aynı artan idx'i kullanır,
    STEP_START/STEP_DONE/STEP_FAIL protokolü (SSE log akışı) bozulmaz."""
    blocks = []
    for item in items:
        idx = counter[0]; counter[0] += 1
        label = _step_label(item)

        if item.disabled:
            blocks.append(f"{indent}# [DEVRE DIŞI] {label}")
            continue

        if item.type == "condition":
            cond_expr = _condition_expr(item, platform, idx)
            then_code = _steps_to_code(item.then_steps, platform, counter, indent + "    ") or f"{indent}    pass"
            else_code = _steps_to_code(item.else_steps, platform, counter, indent + "    ") or f"{indent}    pass"
            blocks.append(
                f"{indent}_check_stop()\n"
                f"{indent}print('STEP_START:{idx}')\n"
                f"{indent}_cond_{idx} = {cond_expr}\n"
                f"{indent}if _cond_{idx}:\n{then_code}\n"
                f"{indent}else:\n{else_code}\n"
                f"{indent}print('STEP_DONE:{idx}')"
            )
            continue

        # ... mevcut image/sql/api/text dallarının aynısı, sadece satır başına {indent} eklenir
        blocks.append(_existing_step_code(item, platform, idx, indent))
    return "\n\n".join(blocks)
```

`_condition_expr(item, platform, idx)` üç şartı **raise etmeyen, bool dönen** ifadelere çevirir:

| `condition_type` | Üretilen ifade (özet) |
|---|---|
| `image_exists` | Mevcut `_find_b64_on_screen`/vision çağrısının try/except ile sarılmış, `True`/`False` dönen hali — mevcut `_image_step_code`'daki arama mantığı **aynen** tekrar kullanılır, sadece `assert`/`raise` yerine bool döner. |
| `element_exists` | Mevcut `_safe_assert*` mantığının non-raising varyantı (mobile: `_safe_assert(driver, hint, raise_on_fail=False)` gibi — mevcut fonksiyona `raise_on_fail` parametresi eklenir, varsayılan `True` kalır ki eski çağrılar bozulmasın). |
| `variable_compare` | `str(_VARS.get({compare_var!r}, '')) {op} {compare_value!r}` — `op`: `==` / `!=` / `in` (contains için `compare_value in _VARS.get(...)`). |

Üst seviye çağrı `generate_script` içinde değişmiyor gibi görünür ama `_generate_steps`'in içi
`_steps_to_code(structured, req.platform, [0])` çağırır — `counter` artık `enumerate` yerine bu
listeye taşınmış oluyor.

**`_build_mobile/web/desktop_template` fonksiyonlarına dokunulmuyor** — bunlar zaten `steps_code`
string'ini olduğu gibi 4 boşluk indent'leyip tek bir üst `try:` bloğuna yerleştiriyor
(`ai_test_generator_router.py:2179-2352`, `:2355-2520`, `:2523+`); recursive üretim çıktısı da
sonuçta düz bir string olduğu için bu sarmalama katmanı aynen çalışır.

### 3. Frontend — Adım Listesi (`ai-generator.html`)

`condition` step type'ı `TYPE_META`'ya eklenir (`:1998-2004` civarı). `renderStepRow` içinde
`condition` dalı: şart tipini seçen bir dropdown (`image_exists`/`element_exists`/
`variable_compare`) + ilgili alan(lar) (görsel yükleme / metin input / değişken+operatör+değer),
altında **iki başlıklı mini-liste** ("✅ Eğer" / "❌ Değilse") render eder.

Mevcut ekle/sil/güncelle/sürükle fonksiyonları üçüncü bir opsiyonel parametre alacak şekilde
genişletilir:

```js
// Önce:  deleteStep(idx)                 → steps.splice(idx, 1)
// Sonra: deleteStep(idx, branch, bIdx)   → branch=null ise eskisi gibi steps.splice(idx,1)
//                                          branch="then"|"else" ise steps[idx][branch+"_steps"].splice(bIdx,1)
function _container(idx, branch) {
    return branch ? steps[idx][branch + "_steps"] : steps;
}
window.deleteStep = function(idx, branch, bIdx) {
    const arr = _container(idx, branch);
    arr.splice(branch ? bIdx : idx, 1);
    renderStepList(); updateGenerateBtn();
};
```

Aynı desen `toggleStepDisabled`, `updateStepContent`, `updateStepField`, `addTextStep`/
`addImageStep`/`addSqlStep`/`addApiStep`/`addCommentStep` (artık hepsi opsiyonel `(branch, targetIdx)`
alıyor) ve sürükle-bırak (`stepDragStart`/`stepListDrop`, dal içi sürükleme sadece kendi dalı
içinde — dallar arası sürükleme bu round'a dahil değil, YAGNI) için tekrarlanır. Var olan
tek-parametreli tüm çağrılar (`onclick="deleteStep(${i})"` vb.) `branch`/`bIdx` `undefined` geçtiği
için **hiçbir değişiklik yapılmadan** eskisi gibi çalışmaya devam eder — geriye dönük uyumluluk
otomatik sağlanıyor.

`_stepToApiItem(s)` (`:2603-2623`) recursive hale getirilir: `type === "condition"` ise
`then_steps`/`else_steps` dizilerini de `.map(_stepToApiItem)` ile dönüştürür.

`updateGenerateBtn`'in "geçerli adım var mı" kontrolü (`:1678-1686`) ve `buildPayload`'daki text-only
özet filtresi (`:2628`) `condition` adımlarının dallarına da bakacak şekilde (tek seviye, düz
`.flatMap`) güncellenir.

## Test Planı

1. **image_exists — IF dalı:** Ekranda gerçekten var olan bir görselle `condition` adımı ekle,
   `then_steps`'e bir tıklama adımı, `else_steps`'e bir yorum adımı ekle; çalıştır, IF dalının
   çalıştığını, ELSE dalının atlandığını `STEP_START/DONE` loglarından doğrula.
2. **image_exists — ELSE dalı:** Ekranda olmayan bir görselle aynı senaryo; ELSE dalının çalıştığını
   doğrula, ayrıca `_check_stop()`/hata fırlatmadığını (script'in durmadığını) doğrula.
3. **element_exists:** Var olan ve olmayan bir metin ipucuyla aynı iki senaryo (mobile ve web'de).
4. **variable_compare — eq/neq/contains:** Önceden bir SQL adımıyla `_VARS['x']` kaydet, sonra
   `condition` adımıyla üç operatörü de test et.
5. **idx sürekliliği:** then/else dalları içindeki adımların `STEP_START:{idx}` numaralarının,
   condition adımından SONRAKİ düz adımlarla çakışmadığını (sayaç paylaşımının doğru çalıştığını)
   doğrula.
6. **disabled condition:** Condition adımının kendisi devre dışı bırakılınca hem koşulun hem
   iki dalın da hiç çalışmadığını (tek `# [DEVRE DIŞI]` satırı üretildiğini) doğrula.
7. **Boş dal:** `else_steps` boşken üretilen kodun geçerli Python olduğunu (otomatik `pass`
   eklendiğini) doğrula.
8. **Frontend geriye dönük uyumluluk:** Condition içermeyen eski bir senaryoyu (steps.json'dan) yükle,
   ekle/sil/sürükle işlemlerinin (branch parametresi olmadan) eskisi gibi çalıştığını doğrula.
9. **3 platform:** Aynı condition senaryosunu mobile/web/desktop'ta ayrı ayrı çalıştırıp şablon
   sarmalamasının (try/finally, driver.quit vb.) bozulmadığını doğrula.

## Self-Review Notları

- **Kapsam sınırlaması (1 seviye nesting):** Kullanıcıyla onaylandı — condition içinde condition
  YOK. İleride ihtiyaç çıkarsa ayrı bir spec ile path-bazlı genel çözüme geçilebilir.
- **`raise_on_fail` parametresi:** Mevcut `_safe_assert`/görsel-arama fonksiyonlarına yeni bir
  opsiyonel parametre eklemek, var olan tüm çağrı yerlerini bozmadan condition'ın "sessiz kontrol"
  ihtiyacını karşılıyor — yeni bir paralel fonksiyon seti yazmaktan kaçınıldı.
  **Doğrulanacak varsayım:** görsel arama ve `_safe_assert` fonksiyonlarının bugünkü gerçek imzaları
  bu tasarımı yazarken tam okunmadı (mimari harita ajan araştırmasından geldi) — implementasyona
  başlamadan önce bu fonksiyonların güncel halini okuyup `raise_on_fail`'in nereye ekleneceğini
  netleştirmek gerekiyor.
- **Dallar arası sürükleme yok:** Bir adımı "Eğer" dalından "Değilse" dalına ya da üst listeye
  sürükleyip taşıma bu round'a dahil değil (YAGNI) — gerekirse kullanıcı sil+yeniden ekle yapar.
- **`compare_op` değerleri:** Sadece `eq`/`neq`/`contains` — büyük/küçük karşılaştırma (`>`,`<`)
  kullanıcı tarafından bilinçli olarak kapsam dışı bırakıldı.
- **Geriye dönük uyumluluk:** Var/yok yeni `branch` parametresi opsiyonel ve `undefined` durumunda
  eski davranışa düşecek şekilde tasarlandı — mevcut kaydedilmiş senaryolar (`steps.json`, condition
  alanı olmayan eski `StepItem`'lar) Pydantic default değerleriyle sorunsuz yüklenir.
