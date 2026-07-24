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

CLICK_WORDS  = r'(?:t[iı]kla|tikla|bas|click|tap|se[cç]|a[cç]|dokun)'
INPUT_WORDS  = r'(?:yaz\b|(?<![a-zğışöüçA-ZĞİŞÖÜÇ])gir(?!iş|iyor)|doldur|type|enter\b)'
ASSERT_WORDS = r'(?:g[oö]r[uü]l[uü]r|g[oö]r[uü]n[uü]r|g[oö]r[uü]nt[uü]len|g[oö]r\b|do[gğ]rula|kontrol|assert|verify|var m[iı]|bekleniyor|görünmeli)'
CLEAR_WORDS  = r'(?:temizle|sil\b)'


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


def _girilir_value(ctx: str) -> tuple[str, bool]:
    """
    'X girilir' cümlesindeki asıl değeri bulmaya çalışır (Azure DevOps export'ta
    değerler çoğunlukla tırnaksız/düz yazılır: "777 datası girilir.", "121212 girilir.").
    Öncelik: "<değer> gibi" kalıbı > düz sayısal token > son çare tahmin.
    Returns (value, is_guessed)
    """
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

    # ── Pasif Türkçe: "X butonuna tıklanır" ──────────────────────────────────
    _PC = re.search(
        r'^(.+?)\s+(?:butonu?na|elementine|alanına|üzerine|simgesine|ikonuna'
        r'|bağlantısına|sekmesin[ei]|linkine|metnine|metine|metinine|yazısına|tab[ıi]na)\s+t[ıi]klan[ıi]r\.?\s*$',
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

    # ── "bir X girilir" (değer belirtilmemiş, quotesuz — Azure export tipik) ─
    if re.search(r'\bgirilir\b', sl) and not quoted:
        _GM = re.search(r'^(.*?)\s*girilir\.?\s*$', s, re.IGNORECASE)
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

    # ── Tıklama ───────────────────────────────────────────────────────────────
    if re.search(CLICK_WORDS, sl) and quoted:
        lines, _ = action_to_java("click", quoted[0], None, s, platform)
        return lines

    # ── Temizle ───────────────────────────────────────────────────────────────
    if re.search(CLEAR_WORDS, sl) and quoted:
        lines, _ = action_to_java("clear", quoted[0], None, s, platform)
        return lines

    # ── Metin girişi: alan + değer (iki tırnak) → tıkla + yaz ─────────────────
    if re.search(INPUT_WORDS, sl) and len(quoted) >= 2:
        field_lines, _ = action_to_java("click", quoted[0], None, s, platform)
        value_lines, _ = action_to_java("type", None, quoted[-1], s, platform)
        if value_lines and value_lines[0].startswith("//"):
            value_lines = value_lines[1:]
        return field_lines + value_lines

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
