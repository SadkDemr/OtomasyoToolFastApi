"""
Java Test Generator Service
============================
Türkçe doğal dil test adımlarını Java Appium koduna çevirir.
Kural motoru — LLM fallback çağrısı router'da yapılır.

Locator/wait/assert stili appium_codegen_service üzerinden BDD Generator ile
BİREBİR aynıdır (referans: BDD Generator, üretimde çalışan taraf).
"""

import re

from services.appium_codegen_service import action_to_java

CLICK_WORDS     = r'(?:t[iı]kla|tikla|bas|click|tap|se[cç]|a[cç]|dokun|işaretle)'
INPUT_WORDS     = r'(?:yaz(?:[ıi]l[ıi]r)?\b|(?<![a-zğışöüçA-ZĞİŞÖÜÇ])gir(?!iş|iyor)|doldur|type|enter\b)'
ASSERT_WORDS    = r'(?:g[oö]r[uü]l[uü]r|g[oö]r[uü]n[uü]r|g[oö]r[uü]nt[uü]len|g[oö]r\b|do[gğ]rula|kontrol|assert|verify|var m[iı]|bekleniyor|görünmeli)'
CLEAR_WORDS     = r'(?:temizle|sil\b)'
LONGPRESS_WORDS = r'(?:uzun\s*bas|bas[iı]l[iı]\s*tut|long\s*press)'

# "X alanına Y yazılır" gibi eleman+değer (iki AYRI tırnaklı değer) kalıbını
# tırnak İÇİNDE tırnak geçen TEK bir değerden (örn. "Merhaba "Dünya" mesajı"
# yazılır) ayırt etmek için — sadece bu bağlaç varsa iki ayrı değer olduğu
# kabul edilir, yoksa tırnaklar tek bir (nested) değere ait sayılır.
FIELD_CONNECTOR_WORDS = r'(?:alan[ıi]na|kutusuna|kutucu[gğ]una|input(?:una)?|field(?:ine)?|k[ıi]sm[ıi]na)'

# ── Custom step işareti ───────────────────────────────────────────────────────
# Kullanıcı, elle yazılacak bir fonksiyon gereken adımın sonuna
# "(Fonksiyon gerekli)" yazar; bu adım için kod üretilmez, sadece yorum düşülür.
CUSTOM_FN_RE = re.compile(
    r'\s*[\(\[\{]?\s*fonks[iıİI]yon\s+gerekl[iıİI]\s*[\)\]\}]?\s*[.!]*\s*$',
    re.IGNORECASE
)

# ── Negatif doğrulama ─────────────────────────────────────────────────────────
# "gelmediği / görülmez / yer almadığı / bulunmaz ..." → elemanın EKRANDA
# OLMAMASI doğrulanır. Olumsuzluk eki (-me/-ma) tek başına yeterli değil:
# "gelmesi beklenir" olumlu, "gelmemesi beklenir" olumsuzdur. Bu yüzden ekten
# SONRA gelen kip/zaman eki de aranır (z / dığ / meli / mesi / yecek / yor ...).
NEG_ASSERT_RE = re.compile(
    r'(?<![a-zğışöüçA-ZĞİŞÖÜÇ])'
    r'(?:gel|g[oö]r[uü]l|g[oö]r[uü]n|g[oö]r[uü]nt[uü]len|listelen|yer\s*al|bulun|ol|[cç][iı]k|a[cç][iı]l)'
    r'm[aeuüıi]'
    r'(?:z(?![a-zğışöüç])|d[iıİI][gğ]|d[iıİI](?![a-zğışöüç])|m[eı]?[sş]|mel[iıİI]|mal[ıiİI]'
    r'|mes[iıİI]|mas[ıiİI]|yece|yaca|yor)',
    re.IGNORECASE
)

# ── Olumlu "beklenir" doğrulaması ─────────────────────────────────────────────
# "X butonunun gelmesi beklenir" gibi nominalize (-mesi/-ması) cümleler bir
# doğrulamadır, "5 saniye beklenir" gibi düz bekleme komutu değil. Kök burada
# NEG_ASSERT_RE ile birebir aynı listeden; tek fark negasyon eki (m[aeuüıi])
# olmadan doğrudan -mesi/-ması/-eceği/-acağı + beklenir/gerekir aranması —
# "gelmemesi beklenir" (olumsuz) NEG_ASSERT_RE'ye takılıp bu noktaya hiç
# gelmez (generate_step içinde NEG kontrolü önce yapılıp return edilir).
POS_ASSERT_RE = re.compile(
    r'(?<![a-zğışöüçA-ZĞİŞÖÜÇ])'
    r'(?:gel|g[oö]r[uü]l|g[oö]r[uü]n|g[oö]r[uü]nt[uü]len|listelen|yer\s*al|bulun|ol|[cç][iı]k|a[cç][iı]l'
    r'|y[uü]klen|tamamlan)'
    r'(?:mes[iıİI]|mas[ıiİI]|ece[gğ][iı]|aca[gğ][iı])'
    r'\s+(?:beklen|bekleniyor|gerek)',
    re.IGNORECASE
)

# Negatif ifadeden önceki hedef metnin sonundaki "butonunun / alanının /
# mesajının ..." gibi tamlama eklerini atmak için.
_NEG_TAIL_RE = re.compile(
    r'\s+(?:buton|element|alan|metin|metn|yaz[ıi]|se[cç]enek|se[cç]ene[gğ]|sekme|tab|link'
    r'|ba[gğ]lant[ıi]|men[uü]|ekran|sayfa|uyar[ıi]|mesaj|ikon|simge|g[oö]rsel|resim|tu[sş]'
    r'|kutu|kutucu[gkğ]|bilgi|de[gğ]er|se[cç]imi?)[a-zğüşıöç]*\s*$',
    re.IGNORECASE
)
_NEG_HEAD_RE = re.compile(
    r'^(?:ekranda|sayfada|listede|ekran[ıi]nda|alan[ıi]nda|[uü]zerinde|i[cç]inde|art[ıi]k)\s+',
    re.IGNORECASE
)

# Adım içindeki ${Degisken} yer tutucusu.
VAR_TOKEN_RE = re.compile(r'\$\{\s*[A-Za-z0-9_\-.]+\s*\}')

# ── Inline platform xpath: "Geri butonu tıklanır.IOS(<xp>) AND(<xp>)" ────────
# Tester adımın sonuna kendi xpath'ini iki platform için ayrı ayrı yazabilir;
# convert sırasında o an üretilen platforma göre ilgili xpath doğrudan
# komuta gömülür (locator metin aramasına gerek kalmaz). "AND" burada
# "Android" kısaltması — ki 'and' kelimesiyle karışmasın diye sadece hemen
# ardından '(' gelen "AND(" / "IOS(" kalıpları aranır (bkz. _extract_inline_xpaths).
_INLINE_IOS_RE = re.compile(r'\bIOS\s*\(', re.IGNORECASE)
_INLINE_AND_RE = re.compile(r'\bAND\s*\(', re.IGNORECASE)


def _extract_balanced(text: str, open_idx: int) -> tuple[str, int] | None:
    """text[open_idx] == '(' varsayılır. Eşleşen kapanış parantezine kadar
    olan içeriği döner (içerik, kapanış_index). Tırnak içindeki parantezler
    (xpath attribute değerlerinde nadiren geçebilir) derinlik sayımına dahil
    edilmez ki xpath'in kendi iç içe parantezleri (örn. "(//X)[1]") doğru
    eşleşsin."""
    depth = 0
    in_quote = None
    i = open_idx
    start = open_idx + 1
    while i < len(text):
        ch = text[i]
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return text[start:i], i
        i += 1
    return None


def _extract_inline_xpaths(step: str) -> tuple[str, str | None, str | None]:
    """Adımda '.IOS(<ios xpath>) AND(<android xpath>)' kalıbı varsa ayıklar.
    İkisi de opsiyonel ve sırasız olabilir. Returns (clean_step, ios_xpath,
    android_xpath) — clean_step bu bloklar çıkarılmış haliyle döner ki fiil/
    aksiyon tespiti (tıkla/doğrula/yaz...) geri kalan doğal dil üzerinden
    yapılabilsin."""
    ios_xpath = None
    android_xpath = None
    spans: list[tuple[int, int]] = []

    m = _INLINE_IOS_RE.search(step)
    if m:
        res = _extract_balanced(step, m.end() - 1)
        if res:
            content, close_idx = res
            ios_xpath = content.strip()
            spans.append((m.start(), close_idx + 1))

    m2 = _INLINE_AND_RE.search(step)
    if m2:
        res = _extract_balanced(step, m2.end() - 1)
        if res:
            content, close_idx = res
            android_xpath = content.strip()
            spans.append((m2.start(), close_idx + 1))

    if not spans:
        return step, None, None

    clean = step
    for s0, e0 in sorted(spans, reverse=True):
        clean = clean[:s0] + clean[e0:]
    clean = re.sub(r'\s{2,}', ' ', clean).strip()
    return clean, ios_xpath, android_xpath


def _detect_inline_action(text: str) -> str:
    """Inline xpath'li adımlarda fiil tespiti — locator xpath'ten geldiği için
    sadece AKSİYON (click/assert/clear/type/long_press) belirlenir. Öncelik
    sırası generate_step'in normal akışıyla aynı (assert/long_press, click'i
    içerebilecek kelimelerden önce kontrol edilir). Hiçbiri eşleşmezse en
    yaygın durum olan 'click' varsayılır."""
    sl = _mask_quoted(text).lower()
    if re.search(LONGPRESS_WORDS, sl):
        return "long_press"
    if re.search(ASSERT_WORDS, sl):
        return "assert"
    if re.search(CLEAR_WORDS, sl):
        return "clear"
    if re.search(INPUT_WORDS, sl):
        return "type"
    return "click"


def _clean_step(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r'^(adım|adim|step)\s*\d+\s*[:\-\.\)]\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*[→>]+\s*[Bb]eklenen:.*$', '', s)
    return s.strip()


def _extract_quoted(text: str) -> list[str]:
    # Tırnak içi baş/son boşluklar ("Başka Hesaba Transfer ") xpath'i eşleşmez yapar
    return [q.strip() for q in re.findall(
        r'["“”‘’]([^"“”‘’]+)["“”‘’]',
        text
    ) if q.strip()]


_QUOTE_SPAN_RE = re.compile(r'["“”‘’][^"“”‘’]*["“”‘’]')


def _mask_quoted(text: str) -> str:
    """Tırnak içindeki element/metin değerlerini boşlukla değiştirir.
    Örn. "Seçimi" içindeki "seç" fiil regex'ini yanıltmasın diye fiil tespiti bu maskeli metin üzerinde yapılır.

    Metinde tırnak İÇİNDE tırnak varsa (örn. "Ödeme "Onayla" ekranı") ilk ve
    son tırnak arasındaki HER ŞEY tek blok olarak maskelenir — aksi halde
    _QUOTE_SPAN_RE ilk iç tırnakta durur, ortadaki metin (örn. "Onayla")
    maskesiz kalıp fiil regex'ini yanıltabilir (örn. içinde "aç" geçen bir
    kelime yanlışlıkla tıklama/açılma fiili sanılabilir)."""
    idxs = [i for i, ch in enumerate(text) if ch in '"“”‘’']
    if len(idxs) < 2:
        return text
    chars = list(text)
    for i in range(idxs[0], idxs[-1] + 1):
        chars[i] = ' '
    return ''.join(chars)


def _single_quoted_value(text: str) -> str | None:
    """Metindeki TEK bir tırnaklı hedefi döner (assert/click/clear/long_press/
    pasif tıklama/açılır gibi tek hedef bekleyen aksiyonlar için).

    Değerin İÇİNDE tırnak geçiyorsa ("X "Y" Z" gibi) ilk tırnaktan SON
    tırnağa kadar olan TÜM içerik tek parça olarak alınır — _extract_quoted
    (ya da quoted[0]) ilk iç tırnakta durup değeri yarıda keserdi.
    NOT: type aksiyonunun iki AYRI değeri (eleman + yazılacak metin) için
    kullanılmaz, orada _extract_quoted'in ayrı ayrı döndürdüğü liste kullanılır."""
    idxs = [i for i, ch in enumerate(text) if ch in '"“”‘’']
    if len(idxs) < 2:
        return None
    return text[idxs[0] + 1: idxs[-1]].strip()


def _quoted_target(raw_group: str, quoted: list[str]) -> str:
    """Pasif kalıplarda (X butonuna tıklanır / X açılır) hedef metni belirler.
    Tırnaklı değer varsa onu kullanır (tırnak karakterleri metne karışmasın diye,
    ve tırnak içinde tırnak varsa yarıda kesilmeden), yoksa yakalanan ham
    metinden olası tırnak karakterlerini temizler."""
    sq = _single_quoted_value(raw_group)
    if sq is not None:
        return sq
    if quoted:
        return quoted[-1]
    return raw_group.strip('"“”‘’\'')


def _auto_fill_value(ctx: str) -> str:
    """Değer hiçbir şekilde tespit edilemeyen 'X girilir' cümlelerinde son çare tahmini değer."""
    if re.search(r'şifre|sifre|password|pin|parola', ctx, re.IGNORECASE):
        return '121212'
    if re.search(r'tc|kimlik', ctx, re.IGNORECASE):
        return '12345678901'
    return 'test_degeri'


def is_custom_step(step: str) -> bool:
    """Adım '(Fonksiyon gerekli)' ile işaretlenmiş mi? (rapor rozeti için)"""
    return bool(CUSTOM_FN_RE.search(_clean_step(step)))


def _assert_target(s: str, quoted: list[str], verb_start: int) -> str | None:
    """Negatif/olumlu 'beklenir' tarzı doğrulama adımlarında hedef element
    metnini çıkarır. Tırnaklı değer varsa o kullanılır; yoksa fiil kökünden
    önceki metinden tamlama ekleri ('butonunun', 'mesajının' ...) ve yer
    zarfları temizlenir.

    "\"Cebe Havale\" butonunun gelmediği görülür" → Cebe Havale
    "Ekranda hata mesajının görülmediği kontrol edilir" → hata
    "Devam butonunun gelmesi beklenir"              → Devam
    """
    sq = _single_quoted_value(s)
    if sq is not None:
        return sq
    if quoted:
        return quoted[0]
    head = s[:verb_start].strip()
    head = _NEG_TAIL_RE.sub('', head).strip()
    head = _NEG_HEAD_RE.sub('', head).strip()
    head = head.strip('"“”‘’\' .,:;-')
    return head or None


def _girilir_value(ctx: str) -> tuple[str, bool]:
    """
    'X girilir' cümlesindeki asıl değeri bulmaya çalışır (Azure DevOps export'ta
    değerler çoğunlukla tırnaksız/düz yazılır: "777 datası girilir.", "121212 girilir.").
    Öncelik: "<değer> gibi" kalıbı > düz sayısal token > son çare tahmin.
    Returns (value, is_guessed)
    """
    var_m = VAR_TOKEN_RE.search(ctx)
    if var_m:
        return var_m.group(0), False
    like_m = re.search(r'(\S+)\s+gibi\b', ctx, re.IGNORECASE)
    if like_m:
        return like_m.group(1), False
    # Binlik/ondalık ayraçlı sayılar bütün alınır: "1.000 TL" → 1.000 (000 değil)
    num_m = re.search(r'(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+(?:,\d+)?|\d{2,}(?:,\d+)?)(?!\d)', ctx)
    if num_m:
        return num_m.group(1), False
    return _auto_fill_value(ctx), True


# ── Tırnaklı hedef xpath mi, düz etiket metni mi? ─────────────────────────────
# Tester bazı adımlarda hedefi hazır xpath olarak yazabiliyor (locator'ı
# elle biliyorsa). Bu durumda metin arama xpath'ine ('//*[@text='X']')
# sarmak yanlış/çalışmayan locator üretir — "//" ile başlıyorsa ya da
# XCUIElementType/android.widget/android.view içeriyorsa doğrudan xpath
# olarak (full_xpath) kullanılır.
_XPATH_LIKE_RE = re.compile(r'^\(?\s*//|XCUIElementType|android\.widget\.|android\.view\.')


def _looks_like_xpath(val: str) -> bool:
    return bool(val) and bool(_XPATH_LIKE_RE.search(val.strip()))


def _resolve_target(target: str | None) -> tuple[str | None, str | None]:
    """(xpath_val, full_xpath) döner — hedef xpath'e benziyorsa full_xpath'e,
    aksi halde düz etiket metni olarak xpath_val'e konur."""
    if target and _looks_like_xpath(target):
        return None, target
    return target, None


def _action_java(action: str, target: str | None, param: str | None, s: str, platform: str):
    xv, fx = _resolve_target(target)
    return action_to_java(action, xv, param, s, platform, full_xpath=fx)


# ── Çoklu hedefli tek cümle: "X","Y","Z" ... kartının listelendiği görülür ───
# Tester bir doğrulama cümlesinde birden fazla hedefi virgül/noktalı virgülle
# art arda sıralayıp sona TEK bir ortak fiil (görülür/beklenir) koyabiliyor.
# Bu durumda her hedef AYRI bir adım/assert olarak üretilmeli — aksi halde
# ilk hedef dışındakiler tamamen kaybolurdu (generate_step tek cümlede sadece
# quoted[0]'ı kullanır).
def _split_list_items(s: str) -> list[str]:
    """Metni üst seviye ',' ve ';' karakterlerinden ayırır. Tırnak içi
    (xpath'lerde iç içe geçen tırnaklar dahil, kabaca) ve parantez içi
    ayraçlar (xpath fonksiyonları: contains(@text, "x") gibi) korunur,
    bölünmez — bu sayede xpath'in kendi virgülleri parçalanmaz."""
    parts: list[str] = []
    depth = 0
    in_quote = False
    buf: list[str] = []
    for ch in s:
        if ch in '"“”‘’':
            in_quote = not in_quote
            buf.append(ch)
            continue
        if not in_quote:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
            elif ch in (',', ';') and depth == 0:
                parts.append(''.join(buf))
                buf = []
                continue
        buf.append(ch)
    parts.append(''.join(buf))
    return parts


def _list_verb_mode(step: str) -> str | None:
    """Cümledeki ortak fiili tespit eder — negatif/olumlu 'beklenir'/düz
    'görülür' tarzı. NEG/POS_ASSERT_RE cümlenin GENELİNDE arandığından
    (tek bir parçada değil) her zaman doğru sırayla (neg > pos > assert)
    kontrol edilir; aksi halde "gelmemesi beklenir" yanlışlıkla pos sayılır."""
    masked = _mask_quoted(step)
    if NEG_ASSERT_RE.search(masked):
        return "neg"
    if POS_ASSERT_RE.search(masked):
        return "pos_beklenir"
    if re.search(ASSERT_WORDS, masked.lower()):
        return "assert"
    return None


_LIST_VERB_SUFFIX = {
    "neg":           " görülmez.",
    "pos_beklenir":  " görülmesi beklenir.",
    "assert":        " görülür.",
}


def _fragment_has_own_verb(fragment: str) -> bool:
    """Bu parça zaten kendi fiilini içeriyor mu (tıklanır/açılır/girilir/
    görülür ...)? İçeriyorsa ortak fiil eklenmez — olduğu gibi ayrı bir
    adım olarak bırakılır."""
    masked = _mask_quoted(fragment)
    ml = masked.lower()
    if NEG_ASSERT_RE.search(masked) or POS_ASSERT_RE.search(masked):
        return True
    if re.search(ASSERT_WORDS, ml):
        return True
    if re.search(CLICK_WORDS, ml) or re.search(INPUT_WORDS, ml) or re.search(CLEAR_WORDS, ml) or re.search(LONGPRESS_WORDS, ml):
        return True
    if re.search(r't[ıi]klan[ıi]r|a[çc][ıi]l[ıi]r|girilir|yaz[ıi]l[ıi]r', ml):
        return True
    return False


def _normalize_nested_quotes(text: str) -> str:
    """Bir liste-parçasında (tek hedef temsil eder) 2'den fazla tırnak
    karakteri varsa, bu genelde xpath attribute değerlerinin de çift
    tırnakla yazılmasından kaynaklanır (@name="X", @content-desc="Y" gibi,
    dıştaki tırnağın İÇİNDE). _extract_quoted/_mask_quoted ilk kapanan
    tırnakta durduğundan bu durumda hedef metni yarıda kesilir/karışır.
    İlk ve son tırnak DIŞINDAKİ tüm tırnaklar tek tırnağa çevrilir — xpath
    söz diziminde attribute değerini tek tırnakla sarmak da geçerlidir,
    böylece dış çift tırnak tek, doğru sınır olarak kalır."""
    idxs = [i for i, ch in enumerate(text) if ch in '"“”‘’']
    if len(idxs) <= 2:
        return text
    chars = list(text)
    for i in idxs[1:-1]:
        chars[i] = "'"
    return ''.join(chars)


# ── Tek satırda birden fazla cümle: "X" butonuna tıklanır.  "Y" başlığı görülür.
# Azure/Excel export'larında adımlar bazen tek satırda nokta ile art arda
# geliyor. Bölünmezse _single_quoted_value ilk-son tırnak arasını tek değer
# sanıp "X\" butonuna tıklanır. \"Y" gibi bozuk xpath üretir.
_SENT_END_CHARS = '.!?'


def _split_sentences(line: str) -> list[str]:
    """Satırı cümle sonlarından (. ! ?) böler. Tırnak ve parantez içi
    (inline IOS(...)/AND(...) xpath'leri, "T.C. Kimlik No" gibi değerler)
    korunur. Nokta sadece ardından boşluk + tırnak/büyük harf geliyorsa
    (ya da doğrudan tırnak) cümle sonu sayılır — "1.000 TL" bölünmez."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote = False
    n = len(line)
    i = 0
    while i < n:
        ch = line[i]
        buf.append(ch)
        if ch in '"“”‘’':
            in_quote = not in_quote
        elif not in_quote:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
            elif ch in _SENT_END_CHARS and depth == 0:
                j = i + 1
                while j < n and line[j].isspace():
                    j += 1
                # "tıklanır.IOS(" gibi boşluksuz devamlar cümle sonu değil;
                # boşluksuz bölme sadece hemen ardından tırnak geliyorsa
                if j < n and (line[j] in '"“”‘’' or (j > i + 1 and line[j].isalpha() and line[j].isupper())):
                    parts.append(''.join(buf))
                    buf = []
                    i = j
                    continue
        i += 1
    parts.append(''.join(buf))
    parts = [p.strip() for p in parts if p.strip()]
    return _split_ve_clauses(parts)


_VE_RE = re.compile(r'\s+ve\s+', re.IGNORECASE)


def _split_ve_clauses(parts: list[str]) -> list[str]:
    """"X" butonuna tıklanır ve "Y" başlığı görülür → iki ayrı adım.
    Sadece 've'nin İKİ tarafı da kendi fiilini içeriyorsa bölünür
    ("Ad ve Soyad" alanı görülür gibi tek hedefli cümleler korunur)."""
    out: list[str] = []
    for p in parts:
        # Her tırnak çifti AYRI maskelenir — _mask_quoted ilk-son tırnak
        # arasını tek blok maskelediğinden aradaki 've'yi de gizlerdi.
        # (boşluk değil 'x' ile — \s+ maskeyi yutup hedef metni kesmesin)
        masked = _QUOTE_SPAN_RE.sub(lambda m: 'x' * len(m.group(0)), p)
        cut = None
        for m in _VE_RE.finditer(masked):
            left, right = p[:m.start()], p[m.end():]
            if _fragment_has_own_verb(left) and _fragment_has_own_verb(right):
                cut = m
                break
        if cut:
            out.append(p[:cut.start()].strip())
            out.extend(_split_ve_clauses([p[cut.end():].strip()]))
        else:
            out.append(p)
    return out


def expand_multi_target_step(step: str) -> list[str]:
    """Satırı önce cümlelere böler (_split_sentences), sonra her cümleyi
    çoklu hedef listesi olarak genişletir (_expand_list_step)."""
    sentences = _split_sentences(step)
    if len(sentences) <= 1:
        return _expand_list_step(step)
    out: list[str] = []
    for sent in sentences:
        out.extend(_expand_list_step(sent))
    return out


def _expand_list_step(step: str) -> list[str]:
    """Virgül/noktalı virgülle ayrılmış çoklu hedefli TEK bir cümleyi, her
    hedef için ayrı bir adım cümlesine böler.

    Ortak fiil (görülür/görülmez/beklenir) genelde sadece SON parçada geçer;
    kendi fiili olmayan önceki parçalara bu fiil otomatik eklenir ki her biri
    generate_step tarafından bağımsız, doğru assert olarak işlenebilsin.
    Tek parça varsa (ayraç yoksa) adım değişmeden döner."""
    raw_parts = _split_list_items(step)
    parts = [p.strip(' ,;') for p in raw_parts]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return [step]

    # Her parça TEK bir hedef temsil eder (liste öğesi) — iç içe tırnaklı
    # xpath'ler _extract_quoted'ı yanıltmasın diye burada normalize edilir.
    parts = [_normalize_nested_quotes(p) for p in parts]

    mode = _list_verb_mode(step)
    if not mode:
        # Ortak fiil belirlenemedi — yine de ayrı adımlara böl, her biri
        # kendi başına tanınabiliyorsa (kendi fiili varsa) doğru işlenir.
        return parts

    suffix = _LIST_VERB_SUFFIX[mode]
    out = []
    for p in parts:
        if _fragment_has_own_verb(p):
            out.append(p)
        else:
            out.append(p.rstrip('.').rstrip() + suffix)
    return out


def generate_step(step: str, platform: str = "android") -> list[str] | None:
    """
    Tek bir Türkçe test adımını Java satırlarına çevirir.
    Tanınmazsa None döner (çağıran taraf LLM fallback'e düşürür).
    """
    s = _clean_step(step)
    if not s:
        return None

    # ── Custom step: "... (Fonksiyon gerekli)" ───────────────────────────────
    # Kod üretilmez; kullanıcı bu noktaya kendi fonksiyonunu yazacak.
    # LLM fallback'e de düşmemesi için en başta kontrol edilir.
    _CF = CUSTOM_FN_RE.search(s)
    if _CF:
        desc = s[:_CF.start()].strip().rstrip('-–—:,').strip()
        return [f'// {desc}' if desc else f'// {s}', '//Fonksiyon gerekli']

    # ── Inline platform xpath: "X tıklanır.IOS(<xp>) AND(<xp>)" ──────────────
    # En başta kontrol edilir — tester xpath'i elle verdiyse, aşağıdaki
    # tırnaklı-metin tabanlı locator kalıplarının hiçbiri devreye girmesin.
    _clean_for_xpath, _ios_xp, _and_xp = _extract_inline_xpaths(s)
    if _ios_xp or _and_xp:
        inline_xpath = _ios_xp if platform == "ios" else _and_xp
        if inline_xpath:
            action = _detect_inline_action(_clean_for_xpath)
            value = None
            if action == "type":
                _iq = _extract_quoted(_clean_for_xpath)
                value = _iq[0] if _iq else _auto_fill_value(_clean_for_xpath)
            lines, _ = action_to_java(action, None, value, s, platform, full_xpath=inline_xpath)
            return lines
        # Bu platform için xpath verilmemiş — normal kural motoruna düş
        # (temizlenmiş metin üzerinden devam: inline blok tekrar eşleşmesin).
        s = _clean_for_xpath

    quoted = _extract_quoted(s)
    sl     = _mask_quoted(s).lower()  # fiil tespiti: tırnaklı değerler maskeli

    # ── Klavye gizle ─────────────────────────────────────────────────────────
    if re.search(r'klavye\s*kapat|klavyeyi\s*kapat|kapat.*klavye|hide.*keyboard|klavye.*kapand', sl):
        lines, _ = action_to_java("hide_keyboard", None, None, s, platform)
        return lines

    # ── Ekran görüntüsü ───────────────────────────────────────────────────────
    if re.search(r'ekran\s*görüntüsü|screenshot|capture\s*screen', sl):
        lines, _ = action_to_java("screenshot", None, None, s, platform)
        return lines

    # ── Negatif doğrulama: "X butonunun gelmediği görülür" ───────────────────
    # Olumlu doğrulama/tıklama dallarından ÖNCE bakılır: "görülmez" içindeki
    # "gör", "açılmaz" içindeki "açıl" gibi kökler aşağıdaki kalıplara takılıp
    # yanlışlıkla tıklama/olumlu assert üretmesin.
    _NEG = NEG_ASSERT_RE.search(_mask_quoted(s))
    if _NEG:
        target = _assert_target(s, quoted, _NEG.start())
        if not target:
            return [f'// {s}  // negatif assertion: eleman metni belirtilmemiş, manuel doğrula']
        lines, _ = _action_java("assert_not_visible", target, None, s, platform)
        return lines

    # ── Olumlu "beklenir" doğrulaması: "X butonunun gelmesi beklenir" ────────
    # NEG kontrolünden SONRA: "gelmemesi beklenir" (olumsuz) yukarıda zaten
    # yakalanıp return edildiği için buraya sadece olumlu biçim ulaşır. Aksi
    # halde generic "bekle|wait|sleep" dalına düşüp yanlışlıkla Thread.sleep
    # üretirdi (bu adım aslında bir durum doğrulaması, süreli bekleme değil).
    _POS = POS_ASSERT_RE.search(_mask_quoted(s))
    if _POS:
        target = _assert_target(s, quoted, _POS.start())
        if not target:
            return [f'// {s}  // assertion: eleman metni belirtilmemiş, manuel doğrula']
        lines, _ = _action_java("assert", target, None, s, platform)
        return lines

    # ── Pasif Türkçe: "X butonuna tıklanır" ──────────────────────────────────
    _PC = re.search(
        r'^(.+?)\s+(?:butonu?na|elementine|alanına|üzerine|simgesine|ikonuna'
        r'|bağlantısına|sekmesin[ei]|linkine|metnine|metine|metinine|yazısına|tab[ıi]na'
        r'|men[uü]s[uü]ne|sayfas[ıi]na|kutusuna|kutucu[gğ]una|se[cç]ene[gğ]ine|resmine|g[oö]rseline)\s+t[ıi]klan[ıi]r\.?\s*$',
        s, re.IGNORECASE
    )
    if _PC:
        text = _quoted_target(_PC.group(1).strip(), quoted)
        lines, _ = _action_java("click", text, None, s, platform)
        return lines

    # ── "Uygulama açılır" — uygulama zaten başlatıldı, sadece yorum ─────────
    if re.search(r'^uygulama\s+a[çc][ıi]l[ıi]r\.?\s*$', sl):
        return [f'// {s}']

    # ── "X açılır" (tıklama + yeni ekranın yüklenmesi için ek bekleme) ───────
    _AC = re.search(r'^(.+?)\s+a[çc][ıi]l[ıi]r\.?\s*$', s, re.IGNORECASE)
    if _AC:
        text = _quoted_target(_AC.group(1).strip(), quoted)
        lines, _ = _action_java("click", text, None, s, platform)
        return lines + ['Thread.sleep(1000);']

    # ── Değişkenli değer: "Telefon alanına ${Musteri_Tel} yazılır" ──────────
    # ${X} tırnaksız yazıldığı için aşağıdaki metin girişi kalıplarına takılmaz;
    # burada yakalanıp değer olarak geçirilir (kod tarafında vars.get("X")).
    _VT = VAR_TOKEN_RE.search(s)
    if _VT and re.search(INPUT_WORDS + r'|yaz[ıi]l[ıi]r|doldurulur|se[cç]ilir', sl):
        # ${X} tırnak içine alınmışsa o değer hedef element değil, yazılacak veridir
        non_var_quoted = [q for q in quoted if not VAR_TOKEN_RE.search(q)]
        if non_var_quoted:
            element = non_var_quoted[0]
        else:
            fm = re.search(
                r'^(.*?)\s*(?:alan[ıi]na|kutusuna|kutucu[gğ]una|input(?:una)?|field(?:ine)?)\b',
                s[:_VT.start()], re.IGNORECASE
            )
            element = fm.group(1).strip(' "“”‘’\'') if fm and fm.group(1).strip() else None
        lines, _ = _action_java("type", element, _VT.group(0), s, platform)
        return lines

    # ── "bir X girilir/yazılır" (değer belirtilmemiş, quotesuz — Azure export
    #    tipik: "777 datası girilir.", "100 yazılır.") ─────────────────────────
    if re.search(r'\b(?:girilir|yaz[ıi]l[ıi]r)\b', sl) and not quoted:
        _GM = re.search(r'^(.*?)\s*(?:girilir|yaz[ıi]l[ıi]r)\.?\s*$', s, re.IGNORECASE)
        ctx = _GM.group(1) if _GM else s
        value, guessed = _girilir_value(ctx)
        lines, _ = action_to_java("type", None, value, s, platform)
        if guessed and lines:
            lines[0] = lines[0] + f'  [otomatik değer: {value}]'
        return lines

    # ── Doğrulama (Tıklama'dan önce kontrol edilir: "görülür/doğrula/kontrol"
    #   gibi daha spesifik fiiller, tıklama kelimeleriyle çakıştığında öncelikli) ─
    if re.search(ASSERT_WORDS, sl) and quoted:
        lines, _ = _action_java("assert", _single_quoted_value(s) or quoted[0], None, s, platform)
        return lines

    # ── Uzun bas / basılı tut (Tıklama'dan önce: "bas" CLICK_WORDS'te de var,
    #   "uzun bas" düz tıklamaya düşmesin diye burada öncelikli kontrol) ──────
    if re.search(LONGPRESS_WORDS, sl) and quoted:
        lines, _ = _action_java("long_press", _single_quoted_value(s) or quoted[0], None, s, platform)
        return lines

    # ── Tıklama ───────────────────────────────────────────────────────────────
    if re.search(CLICK_WORDS, sl) and quoted:
        lines, _ = _action_java("click", _single_quoted_value(s) or quoted[0], None, s, platform)
        return lines

    # ── Temizle ───────────────────────────────────────────────────────────────
    if re.search(CLEAR_WORDS, sl) and quoted:
        lines, _ = _action_java("clear", _single_quoted_value(s) or quoted[0], None, s, platform)
        return lines

    # ── Metin girişi: alan + değer (iki tırnak) → bul, tıkla, yaz (tek eleman) ─
    # NOT: burada quoted[0]/quoted[-1] BİLEREK korunuyor — bu tek dalda iki
    # AYRI değer (eleman + yazılacak metin) bekleniyor, _single_quoted_value
    # ile birleştirmek ikisini yanlışlıkla tek değere karıştırırdı. "alanına"
    # gibi bir bağlaç YOKSA bu iki tırnak aslında tek (nested) bir değere
    # ait olabilir (örn. "Merhaba "Dünya" mesajı" yazılır) — bu yüzden iki-
    # değer yorumu sadece bağlaç varken uygulanır.
    # FIELD_CONNECTOR_WORDS RAW `s` üzerinde aranır — "alanına" iki tırnak
    # ARASINDA yer aldığından yeni _mask_quoted (ilk-son tırnak arası tek
    # blok maskeler) bunu `sl` içinde de maskeleyip kaybederdi.
    if re.search(INPUT_WORDS, sl) and len(quoted) >= 2 and re.search(FIELD_CONNECTOR_WORDS, s, re.IGNORECASE):
        lines, _ = _action_java("type", quoted[0], quoted[-1], s, platform)
        return lines

    # ── Sadece yaz (tek tırnak — nested tırnaklı tek değer dahil) ────────────
    if re.search(INPUT_WORDS, sl) and quoted:
        lines, _ = action_to_java("type", None, _single_quoted_value(s) or quoted[-1], s, platform)
        return lines

    # ── Scroll ────────────────────────────────────────────────────────────────
    if re.search(r'a[sş]a[gğ][iı]\s*kaydır|scroll\s*down|swipe\s*down', sl):
        lines, _ = action_to_java("scroll_down", None, None, s, platform)
        return lines
    if re.search(r'yukar[iı]\s*kaydır|scroll\s*up|swipe\s*up', sl):
        lines, _ = action_to_java("scroll_up", None, None, s, platform)
        return lines
    if re.search(r'sola\s*kaydır|swipe\s*left', sl):
        lines, _ = action_to_java("swipe_left", None, None, s, platform)
        return lines
    if re.search(r'sağa\s*kaydır|swipe\s*right', sl):
        lines, _ = action_to_java("swipe_right", None, None, s, platform)
        return lines
    if re.search(r'(?:kaydır|scroll|swipe)', sl):
        lines, _ = action_to_java("scroll_down", None, None, s, platform)
        return lines

    # ── Geri ──────────────────────────────────────────────────────────────────
    if re.search(r'geri\s*d[oö]n|geri\s*git|back\b', sl):
        lines, _ = action_to_java("back", None, None, s, platform)
        return lines

    # ── Bekle ─────────────────────────────────────────────────────────────────
    if re.search(r'bekle|wait|sleep', sl):
        m = re.search(r'(\d+)', s)
        sec = m.group(1) if m else None
        lines, _ = action_to_java("wait", None, sec, s, platform)
        return lines

    # ── Tırnaksız doğrulama/durum (görülür, açıldı, kapandı — quoted olmadan) ─
    if re.search(ASSERT_WORDS, sl) and not quoted:
        return [f'// {s}  // assertion: eleman metni belirtilmemiş, manuel doğrula']

    return None  # Tanınmadı → LLM


# ══════════════════════════════════════════════════════════════════════════════
# VARSAYILAN LOGIN BETIKLERI
# ══════════════════════════════════════════════════════════════════════════════
# Kullanıcı isteği (2026-10-01): dönüşüm çıktısının başı, ekibin JMeter'da
# kullandığı login betiğiyle BİREBİR aynı olsun (import, config, driver,
# login adımları dahil — hiçbir değişiklik yapılmadan). Senaryo adımları bu
# betiğin altına eklenir; betikte açık kalan blokları (try { ...) dönüşüm
# build_from_login_script() ile kapatır. Admin sayfasından tam betik olarak
# düzenlenebilir (is_full_login_script). Eski tip — sadece adım içeren — login
# kaydı varsa router eski şablon yoluna (build_*_template) düşer.

DEFAULT_LOGIN_IOS = r"""import io.appium.java_client.AppiumBy;
import io.appium.java_client.ios.IOSDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.DesiredCapabilities;
import org.openqa.selenium.support.ui.ExpectedConditions;
import org.openqa.selenium.support.ui.WebDriverWait;
import java.net.URL;
import java.time.Duration;
import java.util.Map;
import java.util.HashMap;

// ── CONFIG ────────────────────────────────────────────────────────
DesiredCapabilities capabilities = new DesiredCapabilities();
capabilities.setCapability("platformName", "iOS");
capabilities.setCapability("platformVersion", vars.get("PLATFORM_VERSION"));
capabilities.setCapability("deviceName", vars.get("DEVICE_NAME"));
capabilities.setCapability("udid", vars.get("UDID"));
capabilities.setCapability("gads:clientSecret", vars.get("CLIENT_SECRET"));
capabilities.setCapability("gads:queueTimeout", 60);
capabilities.setCapability("automationName", "XCUITest");
capabilities.setCapability("noReset", true);
capabilities.setCapability("bundleId", "com.vakifkatilim.mobile.enterprise");
capabilities.setCapability("wdaLaunchTimeout",120000);
capabilities.setCapability("newCommandTimeout",300);
// ── CONFIG END ────────────────────────────────────────────────────

IOSDriver driver = null;
try {
    driver = new IOSDriver(new URL(vars.get("APPIUM_URL")), capabilities);
    driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));
    WebDriverWait wait = new WebDriverWait(driver, Duration.ofSeconds(10));

// ── TEST ADIMLARI ─────────────────────────────────────────────────
//driver.terminateApp('com.vakifkatilim.mobile.enterprise')
driver.activateApp('com.vakifkatilim.mobile.enterprise')


driver.findElement(AppiumBy.xpath("(//XCUIElementTypeStaticText[@name='titleLabel'])[1]")).click();


driver.findElement(AppiumBy.xpath("(//*[@name='Test' or @label='Test' or @value='Test'])[1]")).click();

driver.findElement(AppiumBy.xpath("(//*[@name='Devam Et' or @label='Devam Et' or @value='Devam Et'])[1]")).click();
Thread.sleep(1000);
Thread.sleep(2000);
    // ── "Şifremi Unuttum" kontrolü ────────────────────────────────
    // implicitlyWait'i 0'a çek - yoksa findElements 10sn bekler
    driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(0));
    List<WebElement> sifremiUnuttumList = driver.findElements(AppiumBy.xpath(
        "(//XCUIElementTypeStaticText[@name='Şifremi Unuttum'])[1]"));
    // implicitlyWait'i geri aç
    driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));

    if (sifremiUnuttumList.isEmpty())
    {
        driver.findElement(AppiumBy.xpath(
            "(//*[@name='Bireysel' or @label='Bireysel' or @value='Bireysel'])[1]")).click();
             driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeStaticText[@name='Müşteri No/T.C. Kimlik No'])[1]")).click();

        // 6. Müşteri numarasını gir
        driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeTextField)[1]")).sendKeys("777");

        // 7. Şifre alanına tıkla
        driver.findElement(AppiumBy.xpath(
            "(//*[@name='Şifre' or @label='Şifre' or @value='Şifre'])[1]")).click();

        Thread.sleep(1000);

        // 8. Şifreyi gir
        driver.findElement(AppiumBy.xpath(
            "//XCUIElementTypeCell[2]")).sendKeys("121212");

        // 9. Done butonuna bas (klavyeyi kapat)
        driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeButton[@name='Done'])[1]")).click();

        // 10. Devam butonuna bas
        driver.findElement(AppiumBy.xpath(
            "(//*[@name='Devam' or @label='Devam' or @value='Devam'])[1]")).click();

        // 11. OTP sayfası bekleniyor
        Thread.sleep(3000);

        // 12. OTP kodunu gir
      driver.findElement(AppiumBy.xpath("//XCUIElementTypeOther")).sendKeys("121212");
    }
    else
    {

        // 1. Kullanıcı switch butonuna tıkla
        driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeButton[@name='user switch'])[1]")).click();

        // 2. Kayıtlı kullanıcıları düzenleme ekranına git
        driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeStaticText[@name='Kayıtlı Kullanıcıları Düzenle'])[1]")).click();




driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(0));
List<WebElement> trashIcons = driver.findElements(AppiumBy.xpath(
    "//XCUIElementTypeImage[@name='trash']"));
driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));

int baslangic = Math.min(trashIcons.size(), 3);

for (int i = baslangic; i >= 1; i--)
{
    driver.findElement(AppiumBy.xpath(
        "(//XCUIElementTypeImage[@name='trash'])[" + i + "]")).click();

    driver.findElement(AppiumBy.xpath(
        "(//XCUIElementTypeStaticText[@name='Evet'])[1]")).click();

    Thread.sleep(1000);
    driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(0));
    List<WebElement> bireyselList = driver.findElements(AppiumBy.xpath(
        "(//*[@name='Bireysel' or @label='Bireysel' or @value='Bireysel'])[1]"));
    driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));

    if (!bireyselList.isEmpty() && bireyselList.get(0).isDisplayed())
    {
        break;
    }



}

driver.findElement(AppiumBy.xpath(
            "(//*[@name='Bireysel' or @label='Bireysel' or @value='Bireysel'])[1]")).click();
             driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeStaticText[@name='Müşteri No/T.C. Kimlik No'])[1]")).click();

        // 6. Müşteri numarasını gir
        driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeTextField)[1]")).sendKeys("777");

        // 7. Şifre alanına tıkla
        driver.findElement(AppiumBy.xpath(
            "(//*[@name='Şifre' or @label='Şifre' or @value='Şifre'])[1]")).click();

        Thread.sleep(1000);

        // 8. Şifreyi gir
        driver.findElement(AppiumBy.xpath(
            "//XCUIElementTypeCell[2]")).sendKeys("121212");

        // 9. Done butonuna bas (klavyeyi kapat)
        driver.findElement(AppiumBy.xpath(
            "(//XCUIElementTypeButton[@name='Done'])[1]")).click();

        // 10. Devam butonuna bas
        driver.findElement(AppiumBy.xpath(
            "(//*[@name='Devam' or @label='Devam' or @value='Devam'])[1]")).click();

        // 11. OTP sayfası bekleniyor
        Thread.sleep(3000);

        // 12. OTP kodunu gir
      driver.findElement(AppiumBy.xpath("//XCUIElementTypeOther")).sendKeys("121212");


    }
"""

DEFAULT_LOGIN_ANDROID = r"""import io.appium.java_client.android.AndroidDriver;
import io.appium.java_client.android.nativekey.AndroidKey;
import io.appium.java_client.android.nativekey.KeyEvent;
import org.openqa.selenium.By;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.DesiredCapabilities;
import org.junit.Assert.*;
import java.net.URL;
import java.time.Duration;
import java.util.Map;
import io.appium.java_client.AppiumBy
import java.util.List;
import com.google.common.collect.ImmutableMap;
import org.openqa.selenium.WebElement
import org.openqa.selenium.Dimension;

// ── CONFIG ────────────────────────────────────────────────────────
DesiredCapabilities capabilities = new DesiredCapabilities();
capabilities.setCapability("platformName", "Android");
capabilities.setCapability("platformVersion", vars.get("PLATFORM_VERSION"));
capabilities.setCapability("deviceName", vars.get("DEVICE_NAME"));
capabilities.setCapability("udid", vars.get("UDID"));
if (vars.get("CLIENT_SECRET")) { capabilities.setCapability("gads:clientSecret", vars.get("CLIENT_SECRET")); }
capabilities.setCapability("gads:queueTimeout", 60);
capabilities.setCapability("automationName", "UiAutomator2");
capabilities.setCapability("appPackage", vars.get("APP_PACKAGE"));
capabilities.setCapability("appActivity", vars.get("APP_ACTIVITY"));
capabilities.setCapability("noReset", false);
capabilities.setCapability("systemPort", Integer.parseInt(vars.get("SYSTEM_PORT")));
capabilities.setCapability("ignoreHiddenApiPolicyError", true);
capabilities.setCapability("skipDeviceInitialization", true);
capabilities.setCapability("disableWindowAnimation", true);
// ── CONFIG END ────────────────────────────────────────────────────

AndroidDriver driver = new AndroidDriver(new URL(vars.get("APPIUM_URL")), capabilities);
driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(20));
try {
  //driver.terminateApp("com.vakifkatilim.mobil.test");
       driver.activateApp("com.vakifkatilim.mobil.test");

try {
// "Ortam Seçimi" başlığı görülür.
driver.findElement(By.xpath("(//*[@text='Ortam Seçimi' or @content-desc='Ortam Seçimi'])[1]")).isDisplayed();

// "Continue" butonuna tıklanır.
driver.findElement(By.xpath("(//*[@text='Continue' or @content-desc='Continue'])[1]")).click();


// "Bireysel" Tabına tıklanır.
driver.findElement(By.xpath("(//*[@text='Bireysel' or @content-desc='Bireysel'])[1]")).click();

// "Giriş Yap" Başlığı görülür.
driver.findElement(By.xpath("(//*[@text='Giriş Yap' or @content-desc='Giriş Yap'])[1]")).isDisplayed();

// "Müşteri No/T.C Kimlik No" input alanının görülür.
driver.findElement(By.xpath("(//*[@text='Müşteri No/T.C. Kimlik No' or @content-desc='Müşteri No/T.C Kimlik No'])[1]")).isDisplayed();

// "Müşteri No/T.C Kimlik No" input alanına tıklanır.
driver.findElement(By.xpath("(//*[@text='Müşteri No/T.C. Kimlik No' or @content-desc='Müşteri No/T.C Kimlik No'])[1]")).click();

// Klavye açılır ve değer girilebildiği görülür.  // assertion: eleman metni belirtilmemiş, manuel doğrula

// "777" datası girilir.
//driver.executeScript("mobile: type", Map.of("text", "7777"));
driver.switchTo().activeElement().sendKeys("777");
try { driver.hideKeyboard(); } catch (Exception ignored) {}

// "Müşteri No/T.C Kimlik No" alanının dolduğu görülür.
driver.findElement(By.xpath("(//*[@text='Müşteri No/T.C. Kimlik No' or @content-desc='Müşteri No/T.C. Kimlik No'])[1]")).isDisplayed();

// "Şifre alanına" tıklanır.
driver.findElement(By.xpath("(//*[@text='Şifre' or @content-desc='Şifre'])[1]")).click();

// Klavye açılır ve değer girilebildiği görülür.  // assertion: eleman metni belirtilmemiş, manuel doğrula

driver.switchTo().activeElement().sendKeys("121212");
try { driver.hideKeyboard(); } catch (Exception ignored) {}

// "Devam" butonu aktif olduğu görülür.
driver.findElement(By.xpath("(//*[@text='Devam' or @content-desc='Devam'])[1]")).isDisplayed();

// "Devam" butonuna tıklanır.
driver.findElement(By.xpath("(//*[@text='Devam' or @content-desc='Devam'])[1]")).click();

// "SMS Doğrulama" başlıklı OTP sayfası görülür.
driver.findElement(By.xpath("(//*[@text='SMS Doğrulama' or @content-desc='SMS Doğrulama'])[1]")).isDisplayed();
Thread.sleep(3000);
String otp = "121212";
for (int i = 0; i < otp.length(); i++) {
    if (i == 0) driver.findElement(By.xpath("//android.view.View[@index='0']/android.view.View[@index='3']/android.view.View[@index='0']/android.view.View[@index='" + i + "']")).click();
    driver.pressKey(new io.appium.java_client.android.nativekey.KeyEvent(io.appium.java_client.android.nativekey.AndroidKey.valueOf("DIGIT_" + otp.charAt(i))));
    Thread.sleep(300);
}
"""


# Senaryo adımlarının ihtiyaç duyabildiği sınıflar; login betiği import etmiyorsa
# betiğin ÜSTÜNE eklenir (betiğin kendisi değiştirilmez). java.util.* Groovy'de
# otomatik import edildiği için (List, Map, Arrays) listede yok.
_ADIM_IMPORTLARI = {
    "AppiumBy": "io.appium.java_client.AppiumBy",
    "By": "org.openqa.selenium.By",
    "WebElement": "org.openqa.selenium.WebElement",
    "Dimension": "org.openqa.selenium.Dimension",
    "PointerInput": "org.openqa.selenium.interactions.PointerInput",
    "Sequence": "org.openqa.selenium.interactions.Sequence",
    "KeyEvent": "io.appium.java_client.android.nativekey.KeyEvent",
    "AndroidKey": "io.appium.java_client.android.nativekey.AndroidKey",
    "WebDriverWait": "org.openqa.selenium.support.ui.WebDriverWait",
    "ExpectedConditions": "org.openqa.selenium.support.ui.ExpectedConditions",
}


def is_full_login_script(code: str) -> bool:
    """Login kaydı driver'ı kendisi oluşturan tam bir betik mi (yoksa sadece adım mı)?"""
    return "DesiredCapabilities" in (code or "")


def _acik_bloklar(code: str) -> list[bool]:
    """Kodda kapanmamış '{' bloklarını dıştan içe döner; True = try bloğu.
    Yorumlar ve string literal'ler ('...' / "...") atlanır."""
    stack: list[bool] = []
    i, n = 0, len(code)
    while i < n:
        if code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
            continue
        if code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        c = code[i]
        if c in "\"'":
            i += 1
            while i < n and code[i] != c and code[i] != "\n":
                i += 2 if code[i] == "\\" else 1
            i += 1
            continue
        if c == "{":
            stack.append(bool(re.search(r"\btry\s*$", code[:i])))
        elif c == "}" and stack:
            stack.pop()
        i += 1
    return stack


def build_from_login_script(login_script: str, steps_code: str) -> str:
    """Login betiği (birebir) + senaryo adımları + açık blokların kapanışı.
    En dıştaki try'a finally { driver.quit() } eklenir."""
    login = login_script.rstrip() + "\n"
    steps = steps_code.rstrip()

    eksik = [
        imp for ad, imp in _ADIM_IMPORTLARI.items()
        if re.search(rf"\b{ad}\b", steps) and not re.search(rf"import\s+[\w.]*\b{ad}\b", login)
    ]
    ust = ""
    if eksik:
        ust = "// Senaryo adımları için ek importlar\n" + "".join(f"import {imp};\n" for imp in eksik) + "\n"

    acik = _acik_bloklar(login)
    ilk_try = acik.index(True) if True in acik else -1
    kapanis = []
    for idx in range(len(acik) - 1, -1, -1):
        if not acik[idx]:
            kapanis.append("}")
        elif idx == ilk_try:
            kapanis.append(
                "} catch (Exception e) {\n"
                "    throw e;\n"
                "} finally {\n"
                "    if (driver != null) { driver.quit(); }\n"
                "}"
            )
        else:
            kapanis.append("} catch (Exception e) {\n    throw e;\n}")
    if ilk_try < 0:
        kapanis.append("driver.quit();")

    return (
        ust + login + "\n" + steps + "\n\n"
        "// ── TEST SONU ─────────────────────────────────────────────────────\n"
        + "\n".join(kapanis) + "\n"
    )
