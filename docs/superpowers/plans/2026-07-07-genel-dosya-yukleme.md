# Genel: Dosya Yükleme Alanı Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Login'li kullanıcıların foto/video yükleyip görebildiği, admin'in tüm dosyaları görebildiği
ve kullanıcılara "sadece dosya yükleme" kısıtlı modu atayabildiği yeni bir sayfa eklemek.

**Architecture:** Yeni `UploadedFile` tablosu + `User.upload_only` bayrağı; dosyalar
`backend/uploads/<user_id>/` altında diskte, erişim sahiplik/admin kontrollü bir API
(`/api/uploads`) üzerinden; imza (magic-byte) tabanlı içerik doğrulama uzantı sahteciliğini
engeller; yeni `dosya-yukleme.html` sayfası sidebar'ın "Genel" bölümüne eklenir, `upload_only`
kullanıcılar için sidebar minimalleştirilir.

**Tech Stack:** Python (FastAPI router, SQLAlchemy model), düz HTML/JS/CSS (mevcut `app.js`/
`sidebar.js` desenleri). Test framework yok (proje genelinde pytest kullanılmıyor); backend
doğrulamaları `backend/venv/Scripts/python.exe` ile çalıştırılan bağımsız kontrol scriptleriyle
(gerekirse `fastapi.testclient.TestClient` veya doğrudan fonksiyon çağrısıyla, DB'ye gerçek ama
sonunda temizlenen geçici satırlar yazarak) yapılır; frontend doğrulaması manuel tarayıcı testiyle.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-07-genel-dosya-yukleme-design.md` — bu plan o tasarımın
  uygulamasıdır.
- Dosya boyutu limiti: **50 MB** (`52_428_800` byte), hem `Content-Length` hem gerçek okunan byte
  sayısı kontrol edilir.
- Kabul edilen uzantılar: `jpg, jpeg, png, webp, heic` (resim) ve `mp4, mov, webm, avi` (video).
  Başka hiçbir uzantı kabul edilmez.
- İçerik doğrulama uzantıya değil gerçek dosya baytlarına (magic number/imza) bakar; yeni bir
  sistem bağımlılığı (`python-magic`/libmagic) EKLENMEZ, elle yazılan imza tablosu kullanılır.
  jpg/png/webp için ek olarak `PIL.Image.verify()` çalıştırılır; HEIC'te Pillow eklentisi
  olmadığı için bu adım atlanır.
- `upload_only` kısıtlaması SADECE arayüz (sidebar) düzeyinde; backend API'lerde ayrı bir
  zorlama YOK (bilinçli kapsam dışı bırakma — spec Self-Review notlarına bakınız).
- Proje kökünde boşluk içeren yol var (`C:\Users\Sadik Demir\...`) — tüm komutlarda çift tırnak.
- Yüklenen dosyalar `/ui` gibi genel statik dizin olarak mount EDİLMEZ; her erişim
  `/api/uploads/{id}/file` üzerinden sahiplik/admin kontrolüyle yapılır.
- Kendi dosyasını silme herkese açık (owner), admin her dosyayı silebilir/görebilir.

---

### Task 1: Veri modeli — `UploadedFile` tablosu + `User.upload_only`

**Files:**
- Modify: `backend/models/db_models.py` — `User` sınıfına yeni sütun, yeni `UploadedFile` sınıfı
- Modify: `backend/database.py` — `_run_migrations()` listesine yeni satır
- Modify: `backend/models/schemas.py` — `UserResponse`'a `upload_only` alanı

**Interfaces:**
- Produces: `UploadedFile` ORM sınıfı (`id, user_id, original_filename, stored_filename,
  file_type, mime_type, size_bytes, note, uploaded_at, user` ilişkisi), `User.upload_only: bool`.
- Consumes: yok (en alt seviye, bağımsız).

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_upload_model.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from database import init_db, SessionLocal
from models.db_models import User, UploadedFile
from models.schemas import UserResponse
from datetime import datetime

init_db()
db = SessionLocal()
try:
    u = User(username="_check_upload_model_user", email="_check_upload_model@test.local",
              hashed_password="x", role="user", upload_only=True, created_at=datetime.utcnow())
    db.add(u)
    db.commit()
    db.refresh(u)
    assert u.upload_only is True, "FAIL: upload_only kaydedilmedi"

    f = UploadedFile(user_id=u.id, original_filename="a.png", stored_filename="x.png",
                      file_type="image", mime_type="image/png", size_bytes=10, note="test",
                      uploaded_at=datetime.utcnow())
    db.add(f)
    db.commit()
    db.refresh(f)
    assert f.user.username == "_check_upload_model_user", "FAIL: UploadedFile.user iliskisi calismiyor"

    resp = UserResponse.model_validate(u)
    assert resp.upload_only is True, "FAIL: UserResponse.upload_only alani yok/yanlis"

    print("OK")
finally:
    u2 = db.query(User).filter_by(username="_check_upload_model_user").first()
    if u2:
        db.query(UploadedFile).filter_by(user_id=u2.id).delete()
        db.delete(u2)
    db.commit()
    db.close()
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_upload_model.py yolu>`
Expected: `TypeError: 'upload_only' is an invalid keyword argument for User` (henüz sütun yok) veya
`ImportError: cannot import name 'UploadedFile'`.

- [ ] **Step 3: `User` modeline `upload_only` sütunu ekle**

`backend/models/db_models.py` içinde, `role = Column(String, default="user")` satırının hemen
altına ekle:

```python
    role = Column(String, default="user") # admin, user
    upload_only = Column(Boolean, default=False)  # True ise login sonrasi sadece dosya yukleme sayfasi gorunur
```

- [ ] **Step 4: `UploadedFile` modelini ekle**

`User` sınıfının bittiği yere (son satırı `workspaces = relationship("UserWorkspace",
back_populates="user")`), `Folder` sınıfı başlamadan önce ekle:

```python
    workspaces = relationship("UserWorkspace", back_populates="user")

# --- DOSYA YUKLEME (Genel) ---
class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"))
    original_filename = Column(String)
    stored_filename    = Column(String)   # disk uzerindeki uuid tabanli ad
    file_type         = Column(String)    # "image" | "video"
    mime_type         = Column(String)    # imza kontrolunden tespit edilen gercek tip
    size_bytes        = Column(Integer)
    note              = Column(Text, nullable=True)
    uploaded_at       = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

# --- KLASOR YAPISI (AGAC) ---
class Folder(Base):
```

- [ ] **Step 5: `database.py`'de migration satırı ekle**

`_run_migrations()` içindeki `migrations` listesine ekle:

```python
    migrations = [
        "ALTER TABLE repositories ADD COLUMN provider TEXT NOT NULL DEFAULT 'generic'",
        "ALTER TABLE repositories ADD COLUMN editor_type TEXT NOT NULL DEFAULT 'ai'",
        "ALTER TABLE scenario_share_permissions ADD COLUMN owner_user_id INTEGER",
        "ALTER TABLE users ADD COLUMN last_login DATETIME",
        "ALTER TABLE users ADD COLUMN upload_only BOOLEAN NOT NULL DEFAULT 0",
    ]
```

- [ ] **Step 6: `UserResponse` şemasına `upload_only` ekle**

`backend/models/schemas.py` içinde:

```python
class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: str = "user"
    upload_only: bool = False

    class Config:
        from_attributes = True
```

- [ ] **Step 7: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add backend/models/db_models.py backend/database.py backend/models/schemas.py
git commit -m "feat: dosya yukleme icin UploadedFile tablosu ve User.upload_only bayragi"
```

---

### Task 2: Dosya doğrulama servisi (`upload_validation.py`)

**Files:**
- Create: `backend/services/upload_validation.py`

**Interfaces:**
- Produces: `validate_upload(filename: str, content: bytes) -> tuple[str, str]` — başarısızsa
  `ValueError(mesaj)` fırlatır, başarılıysa `(file_type, mime_type)` döner (`file_type` ∈
  `{"image","video"}`). `MAX_UPLOAD_SIZE: int = 52_428_800`, `ALLOWED_EXTENSIONS: dict[str,str]`.
- Consumes: yok (bağımsız, sadece `PIL.Image` opsiyonel olarak kullanılır — proje zaten Pillow'a
  bağımlı).

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_upload_validation.py`:

```python
import sys, io
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from services.upload_validation import validate_upload, MAX_UPLOAD_SIZE
from PIL import Image

# 1. Gecerli PNG (PIL ile gercekten uretilmis, Image.verify() gecmeli)
buf = io.BytesIO()
Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
file_type, mime = validate_upload("foto.png", buf.getvalue())
assert file_type == "image" and mime == "image/png", f"FAIL png: {file_type} {mime}"

# 2. Gecerli JPEG
buf2 = io.BytesIO()
Image.new("RGB", (4, 4), (0, 255, 0)).save(buf2, format="JPEG")
file_type, mime = validate_upload("foto.jpg", buf2.getvalue())
assert file_type == "image" and mime == "image/jpeg", f"FAIL jpg: {file_type} {mime}"

# 3. Gecerli WEBP
buf3 = io.BytesIO()
Image.new("RGB", (4, 4), (0, 0, 255)).save(buf3, format="WEBP")
file_type, mime = validate_upload("foto.webp", buf3.getvalue())
assert file_type == "image" and mime == "image/webp", f"FAIL webp: {file_type} {mime}"

# 4. Sentetik HEIC (ftyp box, brand 'heic') - Pillow olmadan sadece imza kontrolu
heic_bytes = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100
file_type, mime = validate_upload("foto.heic", heic_bytes)
assert file_type == "image" and mime == "image/heic", f"FAIL heic: {file_type} {mime}"

# 5. Sentetik MP4 (ftyp box, brand 'isom')
mp4_bytes = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 100
file_type, mime = validate_upload("video.mp4", mp4_bytes)
assert file_type == "video" and mime == "video/mp4", f"FAIL mp4: {file_type} {mime}"

# 6. Sentetik MOV (ftyp box, brand 'qt  ')
mov_bytes = b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 100
file_type, mime = validate_upload("video.mov", mov_bytes)
assert file_type == "video" and mime == "video/quicktime", f"FAIL mov: {file_type} {mime}"

# 7. Sentetik WEBM (EBML header)
webm_bytes = b"\x1a\x45\xdf\xa3" + b"\x00" * 100
file_type, mime = validate_upload("video.webm", webm_bytes)
assert file_type == "video" and mime == "video/webm", f"FAIL webm: {file_type} {mime}"

# 8. Sentetik AVI (RIFF....AVI )
avi_bytes = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"\x00" * 100
file_type, mime = validate_upload("video.avi", avi_bytes)
assert file_type == "video" and mime == "video/avi", f"FAIL avi: {file_type} {mime}"

# 9. Desteklenmeyen uzanti
try:
    validate_upload("zararli.exe", b"MZ\x90\x00" + b"\x00" * 50)
    assert False, "FAIL: .exe uzantisi reddedilmeliydi"
except ValueError:
    pass

# 10. UZANTI SAHTECILIGI: gercek EXE (MZ header) icerigi .png uzantisiyla
try:
    validate_upload("sahte.png", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100)
    assert False, "FAIL: MZ-header icerik .png olarak KABUL EDILMEMELIYDI"
except ValueError:
    pass

# 11. Boyut limiti
too_big = b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_UPLOAD_SIZE + 1)
try:
    validate_upload("buyuk.png", too_big)
    assert False, "FAIL: 50MB ustu dosya reddedilmeliydi"
except ValueError:
    pass

# 12. Bozuk PNG (dogru imza ama gecersiz govde) - Pillow verify() yakalamali
try:
    validate_upload("bozuk.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    assert False, "FAIL: bozuk PNG reddedilmeliydi"
except ValueError:
    pass

print("OK")
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_upload_validation.py yolu>`
Expected: `ModuleNotFoundError: No module named 'services.upload_validation'`

- [ ] **Step 3: `upload_validation.py`'yi yaz**

```python
"""
Dosya yukleme dogrulama - uzanti + gercek icerik (magic-byte) kontrolu.
Yeni bir sistem bagimliligi (python-magic/libmagic) EKLENMEDEN, elle yazilan imza tablosuyla
gercek dosya baytlarina bakilir. Bu, bir .exe'nin uzantisini .png yaparak yuklenmesini engeller.
"""
import io

MAX_UPLOAD_SIZE = 52_428_800  # 50 MB

ALLOWED_EXTENSIONS = {
    "jpg": "image", "jpeg": "image", "png": "image", "webp": "image", "heic": "image",
    "mp4": "video", "mov": "video", "webm": "video", "avi": "video",
}

_MIME_TO_TYPE = {
    "image/png": "image", "image/jpeg": "image", "image/webp": "image", "image/heic": "image",
    "video/mp4": "video", "video/quicktime": "video", "video/webm": "video", "video/avi": "video",
}

_HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1"}
_MP4_BRANDS  = {b"isom", b"mp42", b"mp41", b"M4V "}


def _detect_mime(content: bytes):
    """Ilk birkac byte'a bakarak gercek dosya tipini tespit eder. Bulamazsa None doner."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"AVI ":
        return "video/avi"
    if content.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand in _HEIC_BRANDS:
            return "image/heic"
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in _MP4_BRANDS:
            return "video/mp4"
    return None


def validate_upload(filename: str, content: bytes):
    """Uzanti + boyut + gercek icerik (magic-byte) dogrulamasi.
    Basarisizsa ValueError firlatir. Basarili olursa (file_type, mime_type) doner."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Desteklenmeyen dosya uzantisi: .{ext}")

    if len(content) > MAX_UPLOAD_SIZE:
        raise ValueError(f"Dosya boyutu {MAX_UPLOAD_SIZE // (1024*1024)} MB limitini asiyor")

    detected_mime = _detect_mime(content)
    if detected_mime is None:
        raise ValueError("Dosya icerigi taninamadi — bozuk veya desteklenmeyen format")

    expected_type = ALLOWED_EXTENSIONS[ext]
    detected_type = _MIME_TO_TYPE[detected_mime]
    if detected_type != expected_type:
        raise ValueError("Dosya icerigi uzantiyla uyusmuyor — guvenlik nedeniyle reddedildi")

    if detected_mime in ("image/png", "image/jpeg", "image/webp"):
        try:
            from PIL import Image
            Image.open(io.BytesIO(content)).verify()
        except Exception:
            raise ValueError("Gorsel dosyasi bozuk veya gecersiz")

    return detected_type, detected_mime
```

- [ ] **Step 4: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/services/upload_validation.py
git commit -m "feat: dosya yukleme icin magic-byte icerik dogrulama servisi"
```

---

### Task 3: Backend API (`uploads_router.py`) + `main.py` entegrasyonu

**Files:**
- Create: `backend/routers/uploads_router.py`
- Modify: `backend/main.py` — import + `include_router`

**Interfaces:**
- Consumes: Task 1'in `UploadedFile`/`User` modelleri, Task 2'nin `validate_upload()`.
- Produces: `router` (prefix `/api/uploads`) — `POST /`, `GET /`, `GET /{id}/file`,
  `DELETE /{id}`. Diskte depolama: `backend/uploads/<user_id>/<uuid>_<guvenli-ad>`.

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_uploads_router.py`:

```python
import sys, io, asyncio, os
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from database import init_db, SessionLocal
from models.db_models import User, UploadedFile
from datetime import datetime
from PIL import Image
from fastapi import HTTPException

init_db()
db = SessionLocal()


class _FakeUploadFile:
    def __init__(self, filename, content):
        self.filename = filename
        self._content = content
    async def read(self):
        return self._content


def _mkuser(username, role):
    u = User(username=username, email=f"{username}@test.local", hashed_password="x",
              role=role, created_at=datetime.utcnow())
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


user_a = _mkuser("_check_upl_a", "user")
user_b = _mkuser("_check_upl_b", "user")
admin  = _mkuser("_check_upl_admin", "admin")

try:
    from routers.uploads_router import upload_file, list_uploads, get_upload_file, delete_upload

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    fake = _FakeUploadFile("bug.png", buf.getvalue())

    result = asyncio.run(upload_file(file=fake, note="test not", current_user=user_a, db=db))
    assert result["success"] is True, "FAIL: yukleme basarisiz"
    upload_id = result["file"]["id"]

    on_disk = db.query(UploadedFile).filter_by(id=upload_id).first()
    assert on_disk is not None, "FAIL: DB satiri olusmadi"

    # B kendi dosyasi degil, listede gormemeli
    listed_b = asyncio.run(list_uploads(user_id=None, current_user=user_b, db=db))
    assert all(f["id"] != upload_id for f in listed_b["files"]), "FAIL: B, A'nin dosyasini gormemeliydi"

    # Admin tum dosyalari gormeli
    listed_admin = asyncio.run(list_uploads(user_id=None, current_user=admin, db=db))
    assert any(f["id"] == upload_id for f in listed_admin["files"]), "FAIL: admin dosyayi gormedi"

    # B, A'nin dosyasini indirmeye calisirsa 403
    try:
        asyncio.run(get_upload_file(upload_id=upload_id, current_user=user_b, db=db))
        assert False, "FAIL: B 403 almaliydi"
    except HTTPException as e:
        assert e.status_code == 403, f"FAIL: beklenen 403, gelen {e.status_code}"

    # A kendi dosyasini silebilir
    del_result = asyncio.run(delete_upload(upload_id=upload_id, current_user=user_a, db=db))
    assert del_result["success"] is True, "FAIL: silme basarisiz"
    assert db.query(UploadedFile).filter_by(id=upload_id).first() is None, "FAIL: DB satiri hala duruyor"

    print("OK")
finally:
    db.query(UploadedFile).filter(UploadedFile.user_id.in_([user_a.id, user_b.id, admin.id])).delete(synchronize_session=False)
    for u in (user_a, user_b, admin):
        db.delete(u)
    db.commit()
    db.close()
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_uploads_router.py yolu>`
Expected: `ModuleNotFoundError: No module named 'routers.uploads_router'`

- [ ] **Step 3: `uploads_router.py`'yi yaz**

```python
"""
Uploads Router - /api/uploads
Kullanicilarin foto/video yuklemesi icin genel dosya alani (bug ekran goruntusu/kaydi).
"""
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user
from models.db_models import User, UploadedFile as UploadedFileModel
from services.upload_validation import validate_upload

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOADS_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "uploads"


def _safe_name(filename: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "dosya")
    return base[-80:] or "dosya"


def _file_dict(f: "UploadedFileModel") -> dict:
    return {
        "id":                f.id,
        "user_id":           f.user_id,
        "username":          f.user.username if f.user else "?",
        "original_filename": f.original_filename,
        "file_type":         f.file_type,
        "mime_type":         f.mime_type,
        "size_bytes":        f.size_bytes,
        "note":              f.note,
        "uploaded_at":       f.uploaded_at.isoformat() if f.uploaded_at else None,
    }


@router.post("/")
async def upload_file(
    file: UploadFile = File(...),
    note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        file_type, mime_type = validate_upload(file.filename or "", content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    user_dir = UPLOADS_DIR / str(current_user.id)
    try:
        user_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{uuid.uuid4().hex}_{_safe_name(file.filename)}"
        dest = user_dir / stored_filename
        with open(dest, "wb") as f:
            f.write(content)
    except Exception:
        raise HTTPException(500, "Dosya kaydedilemedi")

    record = UploadedFileModel(
        user_id=current_user.id,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_type=file_type,
        mime_type=mime_type,
        size_bytes=len(content),
        note=note or None,
        uploaded_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"success": True, "file": _file_dict(record)}


@router.get("/")
async def list_uploads(
    user_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(UploadedFileModel)
    if current_user.role == "admin":
        if user_id is not None:
            query = query.filter(UploadedFileModel.user_id == user_id)
    else:
        query = query.filter(UploadedFileModel.user_id == current_user.id)
    files = query.order_by(UploadedFileModel.uploaded_at.desc()).all()
    return {"files": [_file_dict(f) for f in files]}


@router.get("/{upload_id}/file")
async def get_upload_file(
    upload_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(UploadedFileModel).filter_by(id=upload_id).first()
    if not record:
        raise HTTPException(404, "Dosya bulunamadi")
    if record.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Bu dosyaya erisim yetkiniz yok")

    path = UPLOADS_DIR / str(record.user_id) / record.stored_filename
    if not path.exists():
        raise HTTPException(404, "Dosya diskte bulunamadi")
    return FileResponse(path, media_type=record.mime_type, filename=record.original_filename,
                         content_disposition_type="inline")


@router.delete("/{upload_id}")
async def delete_upload(
    upload_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(UploadedFileModel).filter_by(id=upload_id).first()
    if not record:
        raise HTTPException(404, "Dosya bulunamadi")
    if record.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Bu dosyayi silme yetkiniz yok")

    path = UPLOADS_DIR / str(record.user_id) / record.stored_filename
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass

    db.delete(record)
    db.commit()
    return {"success": True}
```

- [ ] **Step 4: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 5: `main.py`'ye router'ı ekle**

Öncesi (import bloğu):
```python
# 🥒 BDD Generator
from routers.bdd_generator_router import router as bdd_gen_router
```
Sonrası:
```python
# 🥒 BDD Generator
from routers.bdd_generator_router import router as bdd_gen_router
# 📁 Genel Dosya Yukleme
from routers.uploads_router import router as uploads_router
```

Öncesi (`include_router` bloğu):
```python
# 🥒 BDD Generator
app.include_router(bdd_gen_router)
```
Sonrası:
```python
# 🥒 BDD Generator
app.include_router(bdd_gen_router)
# 📁 Genel Dosya Yukleme
app.include_router(uploads_router)
```

- [ ] **Step 6: Commit**

```bash
git add backend/routers/uploads_router.py backend/main.py
git commit -m "feat: /api/uploads router - yukleme/listeleme/indirme/silme"
```

---

### Task 4: Admin — `upload_only` yönetimi (`admin_users_router.py` + `admin-users.html`)

**Files:**
- Modify: `backend/routers/admin_users_router.py` — `UserCreate`/`UserUpdate` şemaları,
  `_user_dict()`, `create_user()`, `update_user()`
- Modify: `backend/WebArayuz/admin-users.html` — düzenleme modalına checkbox

**Interfaces:**
- Consumes: Task 1'in `User.upload_only` sütunu.
- Produces: `/api/admin/users` POST/PUT gövdesinde `upload_only: Optional[bool]`, `_user_dict()`
  çıktısında `"upload_only": bool`.

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_admin_upload_only.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.admin_users_router import UserCreate, UserUpdate, _user_dict
from database import init_db, SessionLocal
from models.db_models import User
from datetime import datetime

init_db()
db = SessionLocal()
try:
    body = UserCreate(username="_check_admin_upl", email="_check_admin_upl@test.local",
                       password="x1234", upload_only=True)
    assert body.upload_only is True, "FAIL: UserCreate.upload_only alani yok"

    upd = UserUpdate(upload_only=True)
    assert upd.upload_only is True, "FAIL: UserUpdate.upload_only alani yok"

    u = User(username="_check_admin_upl2", email="_check_admin_upl2@test.local",
              hashed_password="x", role="user", upload_only=True, created_at=datetime.utcnow())
    db.add(u); db.commit(); db.refresh(u)
    d = _user_dict(u, db)
    assert d["upload_only"] is True, f"FAIL: _user_dict upload_only donmuyor: {d}"

    print("OK")
finally:
    u2 = db.query(User).filter_by(username="_check_admin_upl2").first()
    if u2:
        db.delete(u2); db.commit()
    db.close()
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_admin_upload_only.py yolu>`
Expected: `pydantic.ValidationError` veya `KeyError: 'upload_only'` (alan henüz yok).

- [ ] **Step 3: `UserCreate`/`UserUpdate` şemalarına `upload_only` ekle**

Öncesi:
```python
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=4)
    full_name: Optional[str] = None
    role: str = Field(default="user")  # user | admin


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
```
Sonrası:
```python
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=4)
    full_name: Optional[str] = None
    role: str = Field(default="user")  # user | admin
    upload_only: bool = Field(default=False)


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    upload_only: Optional[bool] = None
```

- [ ] **Step 4: `_user_dict()` çıktısına `upload_only` ekle**

Öncesi:
```python
        "role":          u.role,
        "created_at":    u.created_at.isoformat() if u.created_at else None,
```
Sonrası:
```python
        "role":          u.role,
        "upload_only":   u.upload_only,
        "created_at":    u.created_at.isoformat() if u.created_at else None,
```

- [ ] **Step 5: `create_user()`'da `upload_only` set et**

Öncesi:
```python
    user = User(
        username=body.username,
        email=body.email,
        hashed_password=auth_service.hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        created_at=datetime.utcnow(),
    )
```
Sonrası:
```python
    user = User(
        username=body.username,
        email=body.email,
        hashed_password=auth_service.hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        upload_only=body.upload_only,
        created_at=datetime.utcnow(),
    )
```

- [ ] **Step 6: `update_user()`'da `upload_only` güncelle**

Öncesi:
```python
    if body.password:
        user.hashed_password = auth_service.hash_password(body.password)

    db.commit()
```
Sonrası:
```python
    if body.password:
        user.hashed_password = auth_service.hash_password(body.password)

    if body.upload_only is not None:
        user.upload_only = body.upload_only

    db.commit()
```

- [ ] **Step 7: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 8: `admin-users.html` düzenleme modalına checkbox ekle**

Öncesi (satır ~116-122):
```html
        <div class="form-group">
            <label>Rol</label>
            <select id="fRole">
                <option value="user">Kullanici</option>
                <option value="admin">Admin</option>
            </select>
        </div>
```
Sonrası:
```html
        <div class="form-group">
            <label>Rol</label>
            <select id="fRole">
                <option value="user">Kullanici</option>
                <option value="admin">Admin</option>
            </select>
        </div>
        <div class="form-group">
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
                <input type="checkbox" id="fUploadOnly" style="width:auto;">
                Sadece Dosya Yükleme (sidebar'da başka hiçbir sayfa görünmez)
            </label>
        </div>
```

Öncesi (`openCreateModal`):
```javascript
        document.getElementById("fRole").value = "user";
        document.getElementById("userModal").classList.add("active");
    };
```
Sonrası:
```javascript
        document.getElementById("fRole").value = "user";
        document.getElementById("fUploadOnly").checked = false;
        document.getElementById("userModal").classList.add("active");
    };
```

Öncesi (`openEditModal`):
```javascript
        document.getElementById("fRole").value = u.role;
        document.getElementById("userModal").classList.add("active");
    };
```
Sonrası:
```javascript
        document.getElementById("fRole").value = u.role;
        document.getElementById("fUploadOnly").checked = !!u.upload_only;
        document.getElementById("userModal").classList.add("active");
    };
```

Öncesi (`saveUser`, her iki dal):
```javascript
        const role     = document.getElementById("fRole").value;

        if (_editUserId) {
            const body = { email, full_name: fullName, role };
            if (password) body.password = password;
            const r = await fetch(`${API}/admin/users/${_editUserId}`, {
                method:"PUT", headers:hdrs(), body:JSON.stringify(body)
            });
            const d = await r.json();
            if (!r.ok) { toast(d.detail || "Hata", false); return; }
            toast("Kullanici guncellendi");
        } else {
            const username = document.getElementById("fUsername").value.trim();
            if (!username || !email || !password) { toast("Zorunlu alanlar bos", false); return; }
            const body = { username, email, password, full_name: fullName, role };
            const r = await fetch(`${API}/admin/users/`, {
                method:"POST", headers:hdrs(), body:JSON.stringify(body)
            });
```
Sonrası:
```javascript
        const role       = document.getElementById("fRole").value;
        const uploadOnly = document.getElementById("fUploadOnly").checked;

        if (_editUserId) {
            const body = { email, full_name: fullName, role, upload_only: uploadOnly };
            if (password) body.password = password;
            const r = await fetch(`${API}/admin/users/${_editUserId}`, {
                method:"PUT", headers:hdrs(), body:JSON.stringify(body)
            });
            const d = await r.json();
            if (!r.ok) { toast(d.detail || "Hata", false); return; }
            toast("Kullanici guncellendi");
        } else {
            const username = document.getElementById("fUsername").value.trim();
            if (!username || !email || !password) { toast("Zorunlu alanlar bos", false); return; }
            const body = { username, email, password, full_name: fullName, role, upload_only: uploadOnly };
            const r = await fetch(`${API}/admin/users/`, {
                method:"POST", headers:hdrs(), body:JSON.stringify(body)
            });
```

- [ ] **Step 9: Commit**

```bash
git add backend/routers/admin_users_router.py backend/WebArayuz/admin-users.html
git commit -m "feat(ui): admin panelinden upload_only bayragi yonetimi"
```

---

### Task 5: Frontend sayfa — `dosya-yukleme.html`

**Files:**
- Create: `backend/WebArayuz/dosya-yukleme.html`

**Interfaces:**
- Consumes: Task 3'ün `/api/uploads` (`POST /`, `GET /`, `GET /{id}/file`, `DELETE /{id}`)
  endpoint'leri; `js/app.js`'teki `Auth`, `Toast`, `Utils`, `API_URL` global'leri (`<script
  src="js/app.js">` ile mevcut sayfalarda olduğu gibi yüklenir).
- Produces: yok (uç kullanıcı sayfası).

- [ ] **Step 1: Sayfayı oluştur**

```html
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dosya Yükleme - Test Otomasyon Platformu</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="css/style.css">
    <style>
        .page-content { padding: 24px; width: 100%; max-width: 1200px; box-sizing: border-box; }

        .upload-box {
            border: 2px dashed var(--border-color);
            border-radius: var(--radius-md);
            padding: 24px;
            text-align: center;
            margin-bottom: 20px;
            background: var(--bg-secondary);
        }
        .upload-box.dragover { border-color: var(--accent-primary); background: rgba(79,70,229,0.06); }
        .upload-note {
            width: 100%; max-width: 420px; margin: 12px auto 0; padding: 8px 12px;
            border: 1px solid var(--border-color); border-radius: var(--radius-md);
            background: var(--bg-primary); color: var(--text-primary); font-size: 0.85rem;
            box-sizing: border-box; display: block;
        }
        .btn-pick {
            display: inline-block; padding: 10px 20px; margin-top: 10px;
            background: var(--accent-primary); color: #fff; border-radius: var(--radius-md);
            font-size: 0.9rem; font-weight: 500; cursor: pointer;
        }

        .filter-row { display:flex; gap:10px; align-items:center; margin-bottom: 16px; flex-wrap: wrap; }
        .filter-row select {
            padding: 8px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md);
            background: var(--bg-secondary); color: var(--text-primary); font-size: 0.85rem;
        }

        .file-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
            gap: 14px;
        }
        .file-card {
            border: 1px solid var(--border-color); border-radius: var(--radius-md);
            overflow: hidden; background: var(--bg-secondary); display: flex; flex-direction: column;
        }
        .file-card .thumb {
            width: 100%; aspect-ratio: 1 / 1; object-fit: cover; background: #000; display: block;
        }
        .file-card video.thumb { object-fit: contain; }
        .file-card .icon-thumb {
            width: 100%; aspect-ratio: 1 / 1; display: flex; align-items: center; justify-content: center;
            font-size: 2.4rem; background: var(--bg-primary);
        }
        .file-card .meta { padding: 8px 10px; font-size: 0.78rem; color: var(--text-secondary); flex: 1; }
        .file-card .meta .fname { font-weight: 600; color: var(--text-primary); word-break: break-word; }
        .file-card .actions { display: flex; gap: 6px; padding: 0 10px 10px; }
        .file-card .actions a, .file-card .actions button {
            flex: 1; text-align: center; padding: 8px 6px; font-size: 0.78rem;
            border-radius: var(--radius-md); border: 1px solid var(--border-color);
            background: var(--bg-primary); color: var(--text-primary); cursor: pointer;
            text-decoration: none; min-height: 44px; display:flex; align-items:center; justify-content:center;
        }
        .file-card .actions .btn-del { color: #ef4444; border-color: rgba(239,68,68,.35); }

        @media (max-width: 600px) {
            .file-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
        }
    </style>
</head>
<body>
<div id="app-root">
    <div id="sidebar-container"></div>
    <div class="main-content">
        <header class="top-bar">
            <span class="top-bar-title">📷 Dosya Yükleme</span>
        </header>

        <div class="page-content">
            <div class="upload-box" id="uploadBox">
                <div>Fotoğraf veya video sürükle-bırak, ya da seç</div>
                <input type="file" id="fileInput" accept="image/*,video/*" multiple style="display:none;">
                <label class="btn-pick" for="fileInput">📁 Dosya Seç</label>
                <input type="text" id="noteInput" class="upload-note" placeholder="Not (opsiyonel) — ör. login ekranında crash">
                <div style="font-size:0.75rem; color:var(--text-muted); margin-top:8px;">
                    Kabul edilen: jpg, png, webp, heic, mp4, mov, webm, avi — dosya başına en fazla 50 MB
                </div>
            </div>

            <div class="filter-row" id="adminFilterRow" style="display:none;">
                <label style="font-size:0.85rem; color:var(--text-secondary);">Kullanıcı:</label>
                <select id="userFilter" onchange="loadFiles()">
                    <option value="">Tümü</option>
                </select>
            </div>

            <div id="fileGrid" class="file-grid"></div>
        </div>
    </div>
</div>

<script src="js/app.js"></script>
<script src="js/sidebar.js"></script>
<script>
(function () {
    "use strict";
    if (!Auth.checkAuth()) return;

    const isAdmin = Auth.isAdmin();
    const me = Auth.getUser();
    let _files = [];

    function fmtSize(bytes) {
        if (bytes > 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
        return Math.round(bytes / 1024) + " KB";
    }

    function cardHtml(f) {
        const url = `${API_URL}/uploads/${f.id}/file`;
        let thumb;
        if (f.file_type === "video") {
            thumb = `<video class="thumb" src="${url}" controls preload="metadata"></video>`;
        } else if (f.mime_type === "image/heic") {
            thumb = `<div class="icon-thumb">🖼️</div>`;
        } else {
            thumb = `<img class="thumb" src="${url}" loading="lazy" alt="${Utils.escapeHtml(f.original_filename)}">`;
        }
        const canDelete = isAdmin || (me && f.user_id === me.id);
        const uploaderLine = isAdmin ? `<div>Yükleyen: ${Utils.escapeHtml(f.username)}</div>` : "";
        return `
            <div class="file-card">
                ${thumb}
                <div class="meta">
                    <div class="fname">${Utils.escapeHtml(f.original_filename)}</div>
                    ${uploaderLine}
                    <div>${fmtSize(f.size_bytes)} · ${Utils.formatRelativeTime(f.uploaded_at)}</div>
                    ${f.note ? `<div>${Utils.escapeHtml(f.note)}</div>` : ""}
                </div>
                <div class="actions">
                    <a href="${url}" download="${Utils.escapeHtml(f.original_filename)}">İndir</a>
                    ${canDelete ? `<button class="btn-del" onclick="deleteFile(${f.id})">Sil</button>` : ""}
                </div>
            </div>`;
    }

    window.loadFiles = async function () {
        const grid = document.getElementById("fileGrid");
        grid.innerHTML = '<div style="color:var(--text-muted);">Yükleniyor...</div>';
        try {
            let endpoint = "/uploads";
            if (isAdmin) {
                const sel = document.getElementById("userFilter").value;
                if (sel) endpoint += `?user_id=${sel}`;
            }
            const data = await API.get(endpoint);
            _files = data.files || [];
            grid.innerHTML = _files.length
                ? _files.map(cardHtml).join("")
                : '<div style="color:var(--text-muted);">Henüz dosya yüklenmemiş.</div>';
        } catch (e) {
            Toast.error(e.message);
        }
    };

    window.deleteFile = async function (id) {
        if (!confirm("Bu dosya silinsin mi?")) return;
        try {
            await API.delete(`/uploads/${id}`);
            Toast.success("Dosya silindi");
            loadFiles();
        } catch (e) {
            Toast.error(e.message);
        }
    };

    async function uploadOne(file) {
        const form = new FormData();
        form.append("file", file);
        form.append("note", document.getElementById("noteInput").value.trim());
        const res = await fetch(`${API_URL}/uploads/`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${Auth.getToken()}` },
            body: form,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Yükleme hatası");
        return data;
    }

    async function handleFiles(fileList) {
        for (const file of fileList) {
            try {
                await uploadOne(file);
                Toast.success(`${file.name} yüklendi`);
            } catch (e) {
                Toast.error(`${file.name}: ${e.message}`);
            }
        }
        loadFiles();
    }

    document.getElementById("fileInput").addEventListener("change", (e) => {
        handleFiles(e.target.files);
        e.target.value = "";
    });

    const box = document.getElementById("uploadBox");
    box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("dragover"); });
    box.addEventListener("dragleave", () => box.classList.remove("dragover"));
    box.addEventListener("drop", (e) => {
        e.preventDefault();
        box.classList.remove("dragover");
        if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
    });

    async function initAdminFilter() {
        if (!isAdmin) return;
        document.getElementById("adminFilterRow").style.display = "flex";
        try {
            const data = await AdminAPI.listUsers();
            const sel = document.getElementById("userFilter");
            (data.users || []).forEach(u => {
                const opt = document.createElement("option");
                opt.value = u.id;
                opt.textContent = u.username;
                sel.appendChild(opt);
            });
        } catch (e) { /* filtre olmadan da calisir */ }
    }

    initAdminFilter();
    loadFiles();
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Manuel doğrulama**

Sunucuyu başlat (`cd backend && python main.py`), tarayıcıda `/ui/dosya-yukleme.html` sayfasını
aç (login'li). Bir resim yükle → galeri'de thumbnail göründüğünü doğrula. Bir video yükle →
`<video controls>` ile oynatılabildiğini doğrula. Kendi dosyanı sil → listeden kalktığını
doğrula. `.txt` dosyası yüklemeyi dene → 400 hatası + `Toast.error` gösterdiğini doğrula.

- [ ] **Step 3: Commit**

```bash
git add backend/WebArayuz/dosya-yukleme.html
git commit -m "feat(ui): dosya yukleme sayfasi (galeri + yukleme + silme)"
```

---

### Task 6: Sidebar entegrasyonu — nav linki + `upload_only` minimal sidebar

**Files:**
- Modify: `backend/WebArayuz/js/sidebar.js`

**Interfaces:**
- Consumes: Task 5'in `dosya-yukleme.html` sayfası, Task 1'in `UserResponse.upload_only` alanı
  (login/`/api/auth/me` yanıtında zaten geliyor, `Auth.getUser().upload_only` ile okunur).
- Produces: yok (son kullanıcı arayüzü).

- [ ] **Step 1: "Genel" bölümüne "Dosya Yükleme" linkini ekle**

Öncesi:
```javascript
            +     section("Genel",
                    item("index",     "&#128202;", "Dashboard")
                    + item("workspace","&#128188;", "Workspace")
                  )
```
Sonrası:
```javascript
            +     section("Genel",
                    item("index",     "&#128202;", "Dashboard")
                    + item("workspace","&#128188;", "Workspace")
                    + item("dosya-yukleme", "&#128247;", "Dosya Yükleme")
                  )
```

- [ ] **Step 2: `upload_only` kullanıcılar için minimal sidebar render et**

Öncesi (`injectSidebar` fonksiyonunun başı):
```javascript
    function injectSidebar() {
        var container = document.getElementById("sidebar-container");
        if (!container) return;

        var page    = getCurrentPage();
        var isAdmin = (typeof Auth !== "undefined" && Auth.isAdmin) ? Auth.isAdmin() : false;
        var user    = (typeof Auth !== "undefined" && Auth.getUser) ? Auth.getUser() : null;

        var userName = user ? (user.full_name || user.username || "User") : "User";
        var userRole = user ? (user.role === "admin" ? "Yönetici" : "Kullanıcı") : "";
        var initials = "?";
        if (userName && userName.length > 0) {
            initials = userName.split(" ").map(function(n){ return n[0]; }).join("").toUpperCase().slice(0, 2);
        }

        function item(pg, icon, label) {
```
Sonrası:
```javascript
    function injectSidebar() {
        var container = document.getElementById("sidebar-container");
        if (!container) return;

        var page    = getCurrentPage();
        var isAdmin = (typeof Auth !== "undefined" && Auth.isAdmin) ? Auth.isAdmin() : false;
        var user    = (typeof Auth !== "undefined" && Auth.getUser) ? Auth.getUser() : null;
        var uploadOnly = !!(user && user.upload_only);

        var userName = user ? (user.full_name || user.username || "User") : "User";
        var userRole = user ? (user.role === "admin" ? "Yönetici" : "Kullanıcı") : "";
        var initials = "?";
        if (userName && userName.length > 0) {
            initials = userName.split(" ").map(function(n){ return n[0]; }).join("").toUpperCase().slice(0, 2);
        }

        function item(pg, icon, label) {
```

Öncesi (nav bloğu ve devamı):
```javascript
        var html = ''
            + '<aside class="sidebar">'
            +   '<div class="sidebar-header">'
            +     '<div class="logo">'
            +       '<div class="logo-icon">&#129514;</div>'
            +       '<span>Test Platform <small style="opacity:0.6;font-size:0.7em;">v1.3.0</small></span>'
            +     '</div>'
            +   '</div>'
            +   '<nav class="sidebar-nav">'
            +     section("Genel",
                    item("index",     "&#128202;", "Dashboard")
                    + item("workspace","&#128188;", "Workspace")
                    + item("dosya-yukleme", "&#128247;", "Dosya Yükleme")
                  )
            +     section("Test",
                    item("web-test",     "&#127760;", "Web Test")
                    + item("mobile-test","&#128242;", "Mobil Test")
                    + item("desktop-test","&#128421;","Desktop Test")
                  )
            +     section("AI Araçlar",
                    item("ai-generator",   "&#129302;", "AI Test Generator")
                    + item("java-generator","&#9749;",  "Java Generator")
                    + item("bdd-generator","&#129405;", "BDD Generator")
                    + item("test-history", "&#128203;", "Test Geçmişi")
                  )
            +     adminBlock
            +   '</nav>'
```
Sonrası:
```javascript
        var navHtml = uploadOnly
            ? section("Genel", item("dosya-yukleme", "&#128247;", "Dosya Yükleme"))
            : (
                section("Genel",
                    item("index",     "&#128202;", "Dashboard")
                    + item("workspace","&#128188;", "Workspace")
                    + item("dosya-yukleme", "&#128247;", "Dosya Yükleme")
                  )
                + section("Test",
                    item("web-test",     "&#127760;", "Web Test")
                    + item("mobile-test","&#128242;", "Mobil Test")
                    + item("desktop-test","&#128421;","Desktop Test")
                  )
                + section("AI Araçlar",
                    item("ai-generator",   "&#129302;", "AI Test Generator")
                    + item("java-generator","&#9749;",  "Java Generator")
                    + item("bdd-generator","&#129405;", "BDD Generator")
                    + item("test-history", "&#128203;", "Test Geçmişi")
                  )
                + adminBlock
              );

        var html = ''
            + '<aside class="sidebar">'
            +   '<div class="sidebar-header">'
            +     '<div class="logo">'
            +       '<div class="logo-icon">&#129514;</div>'
            +       '<span>Test Platform <small style="opacity:0.6;font-size:0.7em;">v1.3.0</small></span>'
            +     '</div>'
            +   '</div>'
            +   '<nav class="sidebar-nav">'
            +     navHtml
            +   '</nav>'
```

- [ ] **Step 3: Manuel doğrulama**

Admin panelinden bir test kullanıcısına `upload_only` bayrağını aç, o kullanıcıyla login ol,
sidebar'da SADECE "Genel > Dosya Yükleme" linkinin (Admin/Test/AI Araçlar bölümleri olmadan)
göründüğünü doğrula. Aynı kullanıcı `index.html`'e URL ile giderse sayfanın yine de yüklendiğini
(kısıt olmadığını, sadece linkin gizli olduğunu) doğrula.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/js/sidebar.js
git commit -m "feat(ui): sidebar'a Dosya Yukleme linki + upload_only minimal sidebar"
```

---

## Self-Review Notları

- **Spec kapsaması:** "Veri modeli" → Task 1. "Dosya doğrulama" → Task 2. "Backend API" → Task 3.
  "Frontend" (sayfa) → Task 5, (sidebar) → Task 6. "Admin `upload_only` yönetimi" → Task 4.
  "Hata yönetimi" spec bölümü Task 3'ün `HTTPException` kullanımlarına gömülü. Spec'in Test
  Planı 1-3 (format/sahtecilik/boyut) → Task 2 kontrol scripti; 4-6 (yetki/admin/silme) → Task 3
  kontrol scripti; 7 (`upload_only` sidebar) → Task 6 Step 3; 8 (mobil UI) → Task 5 Step 2 +
  genel responsive CSS ile karşılanıyor (elle doğrulama, otomatik test yok — tarayıcı/DOM testi
  proje kapsamında zaten yok).
- **Placeholder taraması:** Yok — her adımda tam kod veya tam komut var.
- **Tip/isim tutarlılığı:** `UploadedFile` (Task 1) alan adları (`file_type`, `mime_type`,
  `size_bytes`, `note`, `original_filename`, `stored_filename`) Task 3'ün `uploads_router.py`
  ve Task 5'in frontend `cardHtml()`'inde birebir aynı isimlerle kullanılıyor.
  `validate_upload()` dönüş tipi `(file_type, mime_type)` Task 2'de tanımlandığı gibi Task 3'te
  `file_type, mime_type = validate_upload(...)` şeklinde aynı sırayla tüketiliyor.
- **Bağımlılık sırası:** Task 1 → Task 2 (bağımsız, paralel de olabilir) → Task 3 (1 ve 2'ye
  bağımlı) → Task 4 (sadece Task 1'e bağımlı) → Task 5 (Task 3'e bağımlı) → Task 6 (Task 1 ve
  5'e bağımlı). Sıralı ilerleme önerilir.
