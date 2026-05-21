#!/bin/bash
# ══════════════════════════════════════════════════════════
# OtomasyoTool — Otomatik Deploy Scripti
# Systemd timer tarafından her 60 saniyede çalıştırılır.
# Yeni commit yoksa hiçbir şey yapmaz.
# ══════════════════════════════════════════════════════════

APP_DIR="/opt/otomasyon"
BRANCH="main"
LOG_TAG="otomasyon-deploy"

cd "$APP_DIR" || exit 1

# Remote'u kontrol et
git fetch origin "$BRANCH" --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    # Değişiklik yok — sessizce çık
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') — Yeni commit bulundu: ${REMOTE:0:7}"
echo "$(date '+%Y-%m-%d %H:%M:%S') — Pull yapılıyor..."

git fetch origin "$BRANCH" --quiet
git reset --hard "origin/$BRANCH"

# Yeni bağımlılık varsa yükle
if git diff "$LOCAL" "$REMOTE" --name-only | grep -q "requirements.txt"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') — requirements.txt değişti, paketler güncelleniyor..."
    "$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"
fi

# Servisi yeniden başlat
echo "$(date '+%Y-%m-%d %H:%M:%S') — Servis yeniden başlatılıyor..."
sudo systemctl restart otomasyon.service

echo "$(date '+%Y-%m-%d %H:%M:%S') — Deploy tamamlandı. ✓"
