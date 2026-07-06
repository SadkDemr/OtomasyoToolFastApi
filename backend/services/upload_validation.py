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
