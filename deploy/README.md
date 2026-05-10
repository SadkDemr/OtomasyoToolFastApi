# Sunucu Kurulum Rehberi

## İlk Kurulum (tek seferlik)

**1. `setup.sh` içindeki repo URL'ini düzenle:**
```bash
nano /opt/otomasyon/deploy/setup.sh
# REPO_URL satırını kendi GitHub URL'inle değiştir
```

**2. Scripti çalıştır:**
```bash
sudo bash setup.sh
```

Bu kadar. Uygulama ayağa kalkar ve her 60 saniyede GitHub'ı kontrol eder.

---

## Geliştirici iş akışı

```bash
# Geliştirme PC'de
git push origin main

# Sunucu otomatik olarak 60 saniye içinde:
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
