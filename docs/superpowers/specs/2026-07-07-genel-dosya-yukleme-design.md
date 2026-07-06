# Genel: Dosya Yükleme Alanı — Tasarım

**Tarih:** 2026-07-07
**Kapsam:** Yeni sayfa — sidebar'ın "Genel" bölümüne eklenen, login'li kullanıcıların foto/video
yükleyip görebildiği bir alan. Admin tüm kullanıcıların dosyalarını görebilir ve kullanıcılara
"sadece dosya yükleme" kısıtlı modu atayabilir.

## Problem

Mobil uygulama testçileri fiziksel telefonlarla test yapıyor; bug bulduklarında ekran görüntüsü/
ekran kaydı alıp bunu bilgisayara sadece e-posta yoluyla aktarabiliyorlar. Şirket ağında bu
platformu ayağa kaldırıp aynı ağdaki telefonlardan doğrudan tarayıcı üzerinden dosya yükleyebilecekleri
basit, mobil uyumlu bir alan istiyoruz. Ayrıca sadece bu iş için eklenen kullanıcı hesaplarının
platformun geri kalanını (senaryolar, testler, workspace vb.) hiç görmemesi isteniyor.

## Çözüm

### Veri modeli (`backend/models/db_models.py`)

Yeni tablo:

```python
class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"))
    original_filename = Column(String)
    stored_filename   = Column(String)   # disk üzerindeki uuid tabanlı ad
    file_type         = Column(String)   # "image" | "video"
    mime_type         = Column(String)   # imza kontrolünden tespit edilen gerçek tip
    size_bytes        = Column(Integer)
    note              = Column(Text, nullable=True)
    uploaded_at       = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
```

`User` modeline tek yeni sütun:

```python
upload_only = Column(Boolean, default=False)  # True ise login sonrası sadece dosya yükleme sayfası görünür
```

### Depolama

Dosyalar `backend/uploads/<user_id>/<uuid4>_<güvenli-orijinal-ad>.<ext>` yoluna kaydedilir. Bu
klasör **genel statik dizin olarak mount edilmez** (mevcut `/ui` mount'unun aksine) — her dosyaya
erişim `/api/uploads/{id}/file` endpoint'i üzerinden, sahiplik/admin kontrolüyle yapılır. Böylece
bir kullanıcı başka bir kullanıcının dosya URL'sini tahmin edip doğrudan açamaz.

### Dosya doğrulama (`backend/services/upload_validation.py`)

Yeni bir sistem bağımlılığı (ör. `python-magic` + libmagic) eklemeden, küçük bir imza tablosuyla
gerçek içerik kontrolü:

| Format | Kontrol |
|---|---|
| PNG | `\x89PNG\r\n\x1a\n` ile başlar |
| JPEG | `\xFF\xD8\xFF` ile başlar |
| WEBP | byte 0-3 `RIFF`, byte 8-11 `WEBP` |
| HEIC/HEIF | ISO-BMFF `ftyp` box, brand ∈ {`heic`,`heix`,`heim`,`heis`,`mif1`,`msf1`} |
| MP4/MOV | ISO-BMFF `ftyp` box, brand ∈ {`isom`,`mp42`,`mp41`,`qt  `,`M4V `} |
| WEBM/MKV | EBML header `\x1A\x45\xDF\xA3` |
| AVI | byte 0-3 `RIFF`, byte 8-11 `AVI ` |

Doğrulama akışı (`validate_upload(filename, content: bytes) -> (file_type, mime_type)`, hatada
`ValueError` fırlatır):

1. **Uzantı allowlist:** `jpg,jpeg,png,webp,heic,mp4,mov,webm,avi` dışı → red.
2. **Boyut:** hem `Content-Length` header'ı hem gerçek okunan byte sayısı 50 MB (`52_428_800` byte)
   üstündeyse → red. (İkisi de kontrol edilir; sadece header'a güvenilmez.)
3. **İmza kontrolü:** dosyanın ilk 32 byte'ı yukarıdaki tablo ile eşleşmiyorsa → red
   ("İçerik uzantıyla uyuşmuyor — dosya zararlı veya bozuk olabilir").
4. **Ekstra sağlamlık (sadece jpg/png/webp):** `PIL.Image.open(io.BytesIO(content)).verify()` — imza
   doğru ama gövde bozuksa (ör. kesik/kırık dosya) burada da yakalanır. HEIC için Pillow'un HEIC
   eklentisi projede yok, bu adım HEIC'te atlanır — sadece imza kontrolüyle yetinilir.

Bu, bir saldırganın `virus.exe`'yi `.png` uzantısıyla yüklemesini engeller: uzantı testinden geçse
bile ilk byte'ları `MZ` (Windows PE header) olduğu için imza kontrolünde reddedilir.

**Not:** HEIC dosyaları Chrome/Firefox/Edge'de `<img>` ile native önizlenemez (sadece Safari
destekler). Galeri görünümünde HEIC'ler için önizleme yerine genel bir dosya ikonu + indirme linki
gösterilecek; sunucu tarafında JPG'ye çevirme YOK (kapsam dışı, ek ağır bağımlılık gerektirir).

### Backend API (`backend/routers/uploads_router.py`, prefix `/api/uploads`)

- **`POST /api/uploads`** — multipart form: `file: UploadFile`, `note: Optional[str] = Form(None)`.
  `validate_upload()`'dan geçirir, `backend/uploads/<user_id>/` altına yazar, `UploadedFile` satırı
  oluşturur. `current_user = Depends(get_current_user)` (herhangi bir login'li kullanıcı — mevcut
  auth deseniyle aynı).
- **`GET /api/uploads`** — normal kullanıcı: `WHERE user_id = current_user.id`. Admin
  (`current_user.role == "admin"`): opsiyonel `?user_id=` filtresi yoksa TÜM kullanıcıların
  dosyalarını, her kayıtla birlikte yükleyen kullanıcı adını döner.
- **`GET /api/uploads/{id}/file`** — dosya içeriğini `inline` content-disposition ile stream eder
  (tarayıcıda görüntülenebilsin/oynatılabilsin diye). Yetki: `current_user.id == file.user_id or
  current_user.role == "admin"`, aksi halde 403.
- **`DELETE /api/uploads/{id}`** — aynı yetki kontrolü; hem DB satırı hem diskteki dosya silinir.

`main.py`'ye `uploads_router` eklenir. `admin_users_router.py`'deki `UserUpdate` şemasına
`upload_only: Optional[bool] = None` eklenir — admin bunu kullanıcı düzenleme ekranından
değiştirebilir (mevcut `role`/`password` güncelleme deseniyle aynı yerde).

### Frontend

Yeni sayfa: `backend/WebArayuz/dosya-yukleme.html`. `js/sidebar.js`'deki "Genel" bölümüne 3. madde:

```js
+     section("Genel",
        item("index",     "&#128202;", "Dashboard")
        + item("workspace","&#128188;", "Workspace")
        + item("dosya-yukleme", "&#128247;", "Dosya Yükleme")
      )
```

Sayfa içeriği:
- Yükleme alanı: `<input type="file" accept="image/*,video/*" multiple>` — telefonda dokununca
  native "Kamera / Galeri" seçimi çıkar; masaüstünde sürükle-bırak da desteklenir. Opsiyonel tek
  satırlık not alanı ("ör. login ekranında crash").
- Yükleme sonrası galeri: kart/grid görünüm — resimler için `<img>` thumbnail, video için native
  `<video controls>`, HEIC için dosya ikonu. Her kartta: not, tarih, boyut, indir butonu, ve
  **sadece kendi dosyasıysa** sil butonu (`file.user_id === currentUser.id || isAdmin`).
- Admin bu sayfaya girdiğinde üstte "Kullanıcıya göre filtrele" dropdown'ı görünür (varsayılan: tüm
  kullanıcılar), her kartta ek olarak "Yükleyen: <kullanıcı adı>" satırı gösterilir.
- Mobil öncelikli responsive CSS: grid `auto-fill, minmax(140px, 1fr)`, dokunma hedefleri ≥ 44px.

### Kısıtlı kullanıcı modu (`upload_only`)

Kapsam **sadece arayüz düzeyinde** — backend API'lerde ayrı bir zorlama YOK (bu kullanıcılar zaten
normal `user` rolündeki API yetkilerine sahip; iç ağdaki güvenilir test personeli için bu yeterli,
YAGNI). `sidebar.js`'de:

```js
var uploadOnly = user && user.upload_only;
if (uploadOnly) {
    // Sadece "Dosya Yükleme" linki + kullanıcı bilgisi + çıkış butonu içeren minimal sidebar render edilir.
    // Admin bölümü, Test/AI Araçlar bölümleri hiç render edilmez.
}
```

`Auth.getUser()`'ın döndürdüğü kullanıcı objesine `upload_only` alanı eklenmesi gerekir — bu alan
zaten `/api/auth/me` (veya login response) içinde dönen `User` serileştirmesine eklenmeli.
`upload_only=True` olan bir kullanıcı `dosya-yukleme.html` dışında bir sayfaya (ör. `index.html`)
URL ile giderse, o sayfa normal şekilde yüklenir (kısıt yok) — sadece sidebar linki yok, kazara
tıklayarak gitmez.

### Hata yönetimi

- 50 MB üstü, desteklenmeyen format, imza uyuşmazlığı → `HTTPException(400, <açıklayıcı mesaj>)`,
  frontend `Toast.error(...)` ile gösterir.
- Diske yazarken hata (disk dolu vb.) → `HTTPException(500, "Dosya kaydedilemedi")`, kısmi yazılan
  dosya `finally` bloğunda silinir.
- Silme sırasında disk dosyası zaten yoksa (elle silinmiş) → DB kaydı yine de silinir, hata
  fırlatılmaz (best-effort).

## Test Planı

1. **Geçerli yükleme:** jpg, png, webp, heic, mp4, mov, webm, avi — her biri için küçük geçerli
   örnek dosya yükleyip `UploadedFile` satırı oluştuğunu ve galeri'de göründüğünü doğrula.
2. **Uzantı sahteciliği:** bir `.exe` dosyasının uzantısını `.png` yapıp yüklemeyi dene — imza
   kontrolünde reddedildiğini doğrula.
3. **Boyut limiti:** 50 MB üstü bir dosya yüklemeyi dene — reddedildiğini doğrula.
4. **Yetki izolasyonu:** kullanıcı A dosya yükler, kullanıcı B (`admin` değil) `/api/uploads`
   çağırdığında A'nın dosyasını GÖRMEDİĞİNİ, `/api/uploads/{A'nın dosya id}/file` çağırdığında 403
   aldığını doğrula.
5. **Admin görünürlüğü:** admin `/api/uploads` çağırdığında hem A hem B'nin dosyalarını gördüğünü
   doğrula.
6. **Kendi dosyasını silme:** kullanıcı A kendi dosyasını siler, DB satırı ve disk dosyasının
   silindiğini doğrula. Kullanıcı B, A'nın dosyasını silmeye çalıştığında 403 aldığını doğrula.
7. **`upload_only` sidebar:** admin bir kullanıcıyı `upload_only=True` yapar, o kullanıcı login
   olduğunda sidebar'da sadece "Dosya Yükleme" linkinin göründüğünü doğrula.
8. **Mobil UI:** telefon tarayıcısından (veya dar viewport ile masaüstünde) sayfayı açıp dosya
   seçme diyalogunun native kamera/galeri seçimini sunduğunu, galerinin dar ekranda düzgün
   sarıldığını doğrula.

## Self-Review Notları

- **Kapsam:** Sadece bu yeni sayfa + admin'in `upload_only` bayrağını yönetmesini kapsıyor. Genel/
  genişletilebilir bir "her sayfa için ayrı izin" sistemi kasıtlı olarak kapsam dışı bırakıldı
  (YAGNI — şu an tek ihtiyaç bu).
- **Güvenlik sınırı:** `upload_only` kısıtlaması sadece arayüz düzeyinde; backend API'lerde
  zorlanmıyor. Bu kasıtlı bir tercih (iç ağdaki güvenilir personel), ileride gerçek bir güvenlik
  sınırı gerekirse ayrı bir iş olarak ele alınmalı.
- **Bağımlılık:** Yeni bir Python paketi eklenmiyor — imza kontrolü elle yazılan byte-tablosuyla,
  ekstra doğrulama mevcut `Pillow` ile yapılıyor.
- **Tutarlılık:** Yetki deseni (`current_user.id == owner or current_user.role == "admin"`) ve
  admin-only endpoint deseni (`Depends(require_admin)`), `admin_users_router.py`'deki mevcut
  desenlerle birebir aynı.
