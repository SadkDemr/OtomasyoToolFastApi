#!/bin/bash
# ══════════════════════════════════════════════════════════
# OtomasyoTool — Sunucu İlk Kurulum Scripti
# Sunucuda bir kez çalıştır:  sudo bash setup.sh
# ══════════════════════════════════════════════════════════

set -e

# ── Değişkenler (gerekirse değiştir) ──────────────────────
APP_DIR="/opt/otomasyon"
APP_USER="otomasyon"
REPO_URL="https://github.com/KULLANICI_ADI/OtomasyoToolFastApi.git"
BRANCH="main"
# ─────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   OtomasyoTool Kurulum Başlıyor...   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# 1. Sistem bağımlılıkları
echo "[1/6] Sistem paketleri kuruluyor..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl

# 2. Uygulama kullanıcısı
echo "[2/6] Kullanıcı oluşturuluyor: $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -s /bin/bash -d "$APP_DIR" "$APP_USER"
fi

# 3. Repo clone
echo "[3/6] Repo klonlanıyor: $REPO_URL"
mkdir -p "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    echo "  → Repo zaten mevcut, pull yapılıyor..."
    git -C "$APP_DIR" pull origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# 4. Python venv + bağımlılıklar
echo "[4/6] Python ortamı kuruluyor..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/backend/.venv"
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

# 5. Deploy scripti için sudo yetkisi
echo "[5/6] Deploy yetkisi ayarlanıyor..."
SUDOERS_LINE="$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart otomasyon.service"
if ! grep -qF "$SUDOERS_LINE" /etc/sudoers.d/otomasyon 2>/dev/null; then
    echo "$SUDOERS_LINE" > /etc/sudoers.d/otomasyon
    chmod 440 /etc/sudoers.d/otomasyon
fi

# 6. Systemd servislerini yükle
echo "[6/6] Systemd servisleri yükleniyor..."
cp "$APP_DIR/deploy/otomasyon.service" /etc/systemd/system/
cp "$APP_DIR/deploy/otomasyon-deploy.service" /etc/systemd/system/
cp "$APP_DIR/deploy/otomasyon-deploy.timer" /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now otomasyon.service
systemctl enable --now otomasyon-deploy.timer

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              Kurulum Tamamlandı!                     ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Uygulama  : http://$(hostname -I | awk '{print $1}'):8000/ui"
echo "║  Servis    : systemctl status otomasyon"
echo "║  Loglar    : journalctl -u otomasyon -f"
echo "║  Deploy log: journalctl -u otomasyon-deploy -f"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
