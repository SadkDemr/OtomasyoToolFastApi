"""
Java Step Template Service
============================
Admin tarafından tanımlanan "kalıp step -> Java komutu" eşleşmelerini ve
platform bazlı varsayılan login bloklarını yönetir.

Java Generator convert sırasında:
  - find_step_override(): adım metni bir kalıpla TAM eşleşirse (case-insensitive,
    trim), o kalıbın java_code'u kural motorunu (generate_step) bypass ederek
    doğrudan kullanılır.
  - get_active_login(): include_default_login açıksa, platform için admin'in
    işaretlediği aktif login bloğu senaryo başına eklenir. DB'de kayıt yoksa
    (henüz hiç admin girmediyse) java_generator_service içindeki sabit
    DEFAULT_LOGIN_IOS/DEFAULT_LOGIN_ANDROID'e düşülür — böylece davranış hiç
    admin girmeden önce de bozulmaz.

Eşleşme Python tarafında (case-insensitive .lower()) yapılır; SQLite'ın
LOWER() fonksiyonu Türkçe büyük/küçük İ-I dönüşümünü doğru yapmadığı için
DB seviyesinde case-insensitive filtre YANLIŞ eşleşme üretebilir.
"""

import hashlib

from sqlalchemy.orm import Session

from models.db_models import JavaStepTemplate
from services.java_generator_service import DEFAULT_LOGIN_IOS, DEFAULT_LOGIN_ANDROID
from services.appium_codegen_service import action_to_java

# Kodda daha once varsayilan olan login bloklarinin sha256'si (strip edilmis).
# DB'deki login kaydi bunlardan biriyle birebir ayniysa admin elle duzenlememis
# demektir -> guncel varsayilana yukseltilir. Admin'in duzenledigi kayda dokunulmaz.
# Varsayilan login degistiginde, eski metnin hash'ini buraya eklemeyi unutma.
_ESKI_VARSAYILAN_LOGIN_HASHLERI = {
    "ios": {
        "474445d745ad2ad7bd784097105ecf544dd069465d1911a8d40251e19f37f7a7",  # 2026-09-10
        "f881ab66a46598026ee60f7260caad224923b9ea13b223a8772c0546a8f2ef75",  # 2026-10-01 ara surum (sadece adim)
    },
    "android": {
        "8084053b54dcea7cb38291ddc7d0c18bbd71741af072d9eacd36e83f5221bb30",  # 2026-09-10
        "3a6a374e32ed1b22f3874fc8ff93c543163f4e3ac4b1e6e2d1a37cdfe16d07fb",  # 2026-10-01 ara surum (sadece adim)
    },
}


def _norm(text: str | None) -> str:
    return (text or "").strip().lower().rstrip(".").strip()


def _default_login(platform: str) -> str:
    return DEFAULT_LOGIN_IOS if platform == "ios" else DEFAULT_LOGIN_ANDROID


def _eski_varsayilan_mi(platform: str, java_code: str | None) -> bool:
    digest = hashlib.sha256((java_code or "").strip().encode("utf-8")).hexdigest()
    return digest in _ESKI_VARSAYILAN_LOGIN_HASHLERI.get(platform, set())


def upgrade_stale_default_logins(db: Session) -> int:
    """Admin'in hic dokunmadigi (eski varsayilanla birebir ayni) login kayitlarini
    guncel varsayilana yukseltir. Guncellenen kayit sayisini doner."""
    rows = db.query(JavaStepTemplate).filter(JavaStepTemplate.kind == "login").all()
    guncellenen = 0
    for r in rows:
        if _eski_varsayilan_mi(r.platform, r.java_code):
            r.java_code = _default_login(r.platform)
            guncellenen += 1
    if guncellenen:
        db.commit()
    return guncellenen


def find_step_override(db: Session, step_text: str, platform: str) -> list[str] | None:
    """Adım metni aktif bir 'step' kalıbıyla tam eşleşirse Java satırlarını döner."""
    norm = _norm(step_text)
    if not norm:
        return None
    rows = (
        db.query(JavaStepTemplate)
        .filter(JavaStepTemplate.platform == platform)
        .filter(JavaStepTemplate.kind == "step")
        .filter(JavaStepTemplate.is_active == True)  # noqa: E712
        .all()
    )
    for r in rows:
        if _norm(r.trigger_text) == norm and r.java_code:
            return r.java_code.splitlines()
    return None


def get_active_login(db: Session, platform: str) -> str:
    """Platform için aktif login bloğunu döner; DB'de yoksa kod içindeki
    varsayılana düşer (ilk kurulumda/DB boşken davranış bozulmasın diye)."""
    upgrade_stale_default_logins(db)
    row = (
        db.query(JavaStepTemplate)
        .filter(JavaStepTemplate.platform == platform)
        .filter(JavaStepTemplate.kind == "login")
        .filter(JavaStepTemplate.is_active == True)  # noqa: E712
        .order_by(JavaStepTemplate.updated_at.desc())
        .first()
    )
    if row and row.java_code and row.java_code.strip():
        return row.java_code
    return _default_login(platform)


def ensure_login_seeds(db: Session) -> None:
    """Android/iOS için hiç login kaydı yoksa kod içindeki sabitlerden seed
    eder — admin sayfayı ilk açtığında boş değil, dolu (düzenlenebilir) görsün.
    Idempotent: zaten kayıt varsa hiçbir şey yapmaz."""
    for platform, default_code in (("android", DEFAULT_LOGIN_ANDROID), ("ios", DEFAULT_LOGIN_IOS)):
        exists = (
            db.query(JavaStepTemplate)
            .filter(JavaStepTemplate.platform == platform)
            .filter(JavaStepTemplate.kind == "login")
            .first()
        )
        if exists:
            upgrade_stale_default_logins(db)
            continue
        db.add(JavaStepTemplate(
            platform=platform,
            kind="login",
            trigger_text=None,
            java_code=default_code,
            note="Varsayılan login akışı (kod içinden seed edildi)",
            is_active=True,
        ))
    db.commit()


def build_java_from_xpath(
    action: str, xpath: str, value: str | None, trigger_text: str, platform: str
) -> str:
    """Admin sadece bir xpath + aksiyon girdiğinde (tam Java kodu değil),
    appium_codegen_service.action_to_java ile aynı stildeki komutu üretir —
    Java Generator'ın kural motorunun ürettiği kodla birebir aynı görünüm."""
    lines, _ = action_to_java(action, None, value, trigger_text, platform, full_xpath=xpath)
    return "\n".join(lines)


def deactivate_conflicts(db: Session, platform: str, kind: str, trigger_text: str | None, exclude_id: int | None) -> None:
    """Aynı (platform, kind, trigger_text) için başka aktif kayıt varsa pasif
    hale getirir — 'step' kalıplarında belirsiz eşleşme, 'login'de birden
    fazla aktif blok olmasın diye (platform başına TEK aktif login)."""
    q = (
        db.query(JavaStepTemplate)
        .filter(JavaStepTemplate.platform == platform)
        .filter(JavaStepTemplate.kind == kind)
        .filter(JavaStepTemplate.is_active == True)  # noqa: E712
    )
    if exclude_id is not None:
        q = q.filter(JavaStepTemplate.id != exclude_id)
    for row in q.all():
        if kind == "login" or _norm(row.trigger_text) == _norm(trigger_text):
            row.is_active = False
    db.commit()
