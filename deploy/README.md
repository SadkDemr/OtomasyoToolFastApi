# Sunucu Kurulum Rehberi

## İlk Kurulum (tek seferlik)

**1. `setup.sh`'ı sunucuya kopyala** (USB, scp, elle yapıştır)

**2. Repo URL'ini düzenle:**
```bash
nano setup.sh
# REPO_URL satırını kendi GitHub SSH URL'inle değiştir:
# git@github.com:KULLANICI_ADIN/OtomasyoToolFastApi.git
```

**3. Çalıştır:**
```bash
sudo bash setup.sh
```

**4. Script SSH Deploy Key üretir ve ekranda gösterir:**
```
╔══════════════════════════════════════════════════╗
║         GITHUB'A EKLEMEN GEREKEN DEPLOY KEY      ║
╠══════════════════════════════════════════════════╣
ssh-ed25519 AAAAC3Nza... otomasyon-deploy@sunucu
╚══════════════════════════════════════════════════╝
```

**5. GitHub'a ekle:**
- Repo → **Settings** → **Deploy Keys** → **Add deploy key**
- Public key'i yapıştır, `Allow write access` **işaretleme**
- "Deploy key'i ekledin mi?" sorusuna **E** yaz

Kurulum tamamdır. Artık her `git push`'ta sunucu 60 saniye içinde güncellenir.

---

## Geliştirici iş akışı

```bash
# Geliştirme PC'de
git push origin main

# Sunucu otomatik olarak ~60 saniye içinde:
# → git pull yapar
# → requirements.txt değiştiyse pip install çalıştırır
# → FastAPI servisini yeniden başlatır
```

---

## Faydalı komutlar (sunucuda)

```bash
# Uygulama logları (canlı)
journalctl -u otomasyon -f

# Deploy logları (ne zaman pull yapıldı)
journalctl -u otomasyon-deploy -f

# Servis durumu
systemctl status otomasyon
systemctl status otomasyon-deploy.timer

# Manuel deploy tetikle (beklemeden)
sudo systemctl start otomasyon-deploy.service

# Servisi yeniden başlat
sudo systemctl restart otomasyon.service
```

---

## Dosya açıklamaları

| Dosya | Açıklama |
|-------|----------|
| `setup.sh` | İlk kurulum — bir kez çalıştırılır |
| `deploy.sh` | Git pull + restart scripti |
| `otomasyon.service` | FastAPI uygulamasını ayakta tutar |
| `otomasyon-deploy.service` | deploy.sh'ı çalıştıran oneshot servis |
| `otomasyon-deploy.timer` | Her 60sn'de deploy.service'i tetikler |
