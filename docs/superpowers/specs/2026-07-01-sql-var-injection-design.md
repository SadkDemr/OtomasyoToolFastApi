# SQL Adımına Değişken Enjeksiyonu — Tasarım

**Tarih:** 2026-07-01
**Kapsam:** AI Test Generator — `sql` step tipi (Web/Desktop/Mobil ortak, platform bağımsız)

## Problem

`backend/routers/ai_test_generator_router.py::_sql_step_code()` fonksiyonu, bir SQL adımının
`sql_query` alanını kod üretimi (codegen) anında `repr(query)` ile üretilen script'e sabit
(literal) string olarak gömüyor. Script içinde zaten bir `_VARS` sözlüğü var (önceki bir SQL/API
adımının `var_name` alanına yazdığı değerleri tutuyor) ama bu değerler `sql_query` metninin içine
hiçbir şekilde enjekte edilemiyor — çünkü gerçek değer ancak script *çalışırken* belli oluyor,
codegen anında değil.

Kullanıcı isteği: bir SELECT sorgusundan `_VARS`'a kaydedilen bir değeri, sonraki bir SQL adımının
sorgu metninin içinde kullanabilmek (ör: `SELECT * FROM orders WHERE user_id = {{user_id}}`).

## Çözüm

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

## Kapsam Dışı

- `api_url` / `api_headers` / `api_body` alanlarında aynı boşluk var ama bu tasarımın kapsamında
  değil — kullanıcı sadece DB/SQL tarafını istedi. `_sub_vars` fonksiyonu ileride API adımına da
  aynı şekilde uygulanabilir (ayrı bir istek olarak).
- Parametrik sorgu (`:param` bind) kullanılmıyor — düz string-replace, kod tabanındaki mevcut
  stille tutarlı. Güvenlik riski var ama bu bir test-otomasyon aracı (kullanıcı kendi test DB'sine
  karşı çalıştırıyor), dış kullanıcı girdisi işlenmiyor.

## Etkilenen Dosyalar

- `backend/routers/ai_test_generator_router.py` — `_sub_vars` helper'ının 3 şablona eklenmesi,
  `_sql_step_code()`'daki 3 `execute()` çağrısının güncellenmesi
- `backend/WebArayuz/ai-generator.html` — `sql_query` textarea tooltip/placeholder güncellemesi

## Test Planı

- Manuel: iki SQL adımlı bir Desktop/Web senaryosu — ilk adım `SELECT id FROM users LIMIT 1` →
  `var_name=user_id`; ikinci adım `SELECT * FROM orders WHERE user_id = {{user_id}}` → üretilen
  script çalıştırıldığında ikinci sorgunun doğru ID ile çalıştığı loglardan doğrulanacak.
