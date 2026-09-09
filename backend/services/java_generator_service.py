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


def _clean_step(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r'^(adım|adim|step)\s*\d+\s*[:\-\.\)]\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*[→>]+\s*[Bb]eklenen:.*$', '', s)
    return s.strip()


def _extract_quoted(text: str) -> list[str]:
    return re.findall(
        r'["“”‘’]([^"“”‘’]+)["“”‘’]',
        text
    )


_QUOTE_SPAN_RE = re.compile(r'["“”‘’][^"“”‘’]*["“”‘’]')


def _mask_quoted(text: str) -> str:
    """Tırnak içindeki element/metin değerlerini boşlukla değiştirir.
    Örn. "Seçimi" içindeki "seç" fiil regex'ini yanıltmasın diye fiil tespiti bu maskeli metin üzerinde yapılır."""
    return _QUOTE_SPAN_RE.sub(lambda m: ' ' * len(m.group(0)), text)


def _quoted_target(raw_group: str, quoted: list[str]) -> str:
    """Pasif kalıplarda (X butonuna tıklanır / X açılır) hedef metni belirler.
    Tırnaklı değer varsa onu kullanır (tırnak karakterleri metne karışmasın diye),
    yoksa yakalanan ham metinden olası tırnak karakterlerini temizler."""
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
    num_m = re.search(r'\b(\d{2,})\b', ctx)
    if num_m:
        return num_m.group(1), False
    return _auto_fill_value(ctx), True


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
        lines, _ = action_to_java("assert_not_visible", target, None, s, platform)
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
        lines, _ = action_to_java("assert", target, None, s, platform)
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
        lines, _ = action_to_java("click", text, None, s, platform)
        return lines

    # ── "Uygulama açılır" — uygulama zaten başlatıldı, sadece yorum ─────────
    if re.search(r'^uygulama\s+a[çc][ıi]l[ıi]r\.?\s*$', sl):
        return [f'// {s}']

    # ── "X açılır" (tıklama + yeni ekranın yüklenmesi için ek bekleme) ───────
    _AC = re.search(r'^(.+?)\s+a[çc][ıi]l[ıi]r\.?\s*$', s, re.IGNORECASE)
    if _AC:
        text = _quoted_target(_AC.group(1).strip(), quoted)
        lines, _ = action_to_java("click", text, None, s, platform)
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
        lines, _ = action_to_java("type", element, _VT.group(0), s, platform)
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
        lines, _ = action_to_java("assert", quoted[0], None, s, platform)
        return lines

    # ── Uzun bas / basılı tut (Tıklama'dan önce: "bas" CLICK_WORDS'te de var,
    #   "uzun bas" düz tıklamaya düşmesin diye burada öncelikli kontrol) ──────
    if re.search(LONGPRESS_WORDS, sl) and quoted:
        lines, _ = action_to_java("long_press", quoted[0], None, s, platform)
        return lines

    # ── Tıklama ───────────────────────────────────────────────────────────────
    if re.search(CLICK_WORDS, sl) and quoted:
        lines, _ = action_to_java("click", quoted[0], None, s, platform)
        return lines

    # ── Temizle ───────────────────────────────────────────────────────────────
    if re.search(CLEAR_WORDS, sl) and quoted:
        lines, _ = action_to_java("clear", quoted[0], None, s, platform)
        return lines

    # ── Metin girişi: alan + değer (iki tırnak) → bul, tıkla, yaz (tek eleman) ─
    if re.search(INPUT_WORDS, sl) and len(quoted) >= 2:
        lines, _ = action_to_java("type", quoted[0], quoted[-1], s, platform)
        return lines

    # ── Sadece yaz (tek tırnak) ───────────────────────────────────────────────
    if re.search(INPUT_WORDS, sl) and len(quoted) == 1:
        lines, _ = action_to_java("type", None, quoted[0], s, platform)
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
