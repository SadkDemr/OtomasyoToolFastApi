#!/bin/bash
# ══════════════════════════════════════════════════════════
# OtomasyoTool — Sunucu İlk Kurulum Scripti
# Sunucuda bir kez çalıştır:  sudo bash setup.sh
# ══════════════════════════════════════════════════════════

set -e

# ── Değişkenler (gerekirse değiştir) ──────────────────────
APP_DIR="/opt/otomasyon"
APP_USER="otomasyon"
REPO_URL="git@github.com:KULLANICI_ADI/OtomasyoToolFastApi.git"
BRANCH="main"
# ─────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   OtomasyoTool Kurulum Başlıyor...   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# 1. Sistem bağımlılıkları
echo "[1/7] Sistem paketleri kuruluyor..."
# Bozuk PostgreSQL repo varsa temizle (proje SQLite kullanır, PostgreSQL gerekmez)
rm -f /etc/apt/sources.list.d/pgdg.list /etc/apt/sources.list.d/postgresql.list
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl

# 2. Uygulama kullanıcısı
echo "[2/7] Kullanıcı oluşturuluyor: $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -s /bin/bash -m -d "/home/$APP_USER" "$APP_USER"
fi

# 3. SSH Deploy Key
echo "[3/7] SSH Deploy Key ayarlanıyor..."
SSH_DIR="/home/$APP_USER/.ssh"
KEY_FILE="$SSH_DIR/github_deploy"

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

if [ ! -f "$KEY_FILE" ]; then
    sudo -u "$APP_USER" ssh-keygen -t ed25519 -C "otomasyon-deploy@$(hostname)" -f "$KEY_FILE" -N ""
fi

chown -R "$APP_USER:$APP_USER" "$SSH_DIR"

# SSH config — GitHub için bu key'i kullan
cat > "$SSH_DIR/config" <<EOF
Host github.com
    HostName github.com
    User git
    IdentityFile $KEY_FILE
    StrictHostKeyChecking no
EOF
chown "$APP_USER:$APP_USER" "$SSH_DIR/config"
chmod 600 "$SSH_DIR/config"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              GITHUB'A EKLEMEN GEREKEN DEPLOY KEY             ║"
echo "╠══════════════════════════════════════════════════════════════╣"
cat "$KEY_FILE.pub"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Adımlar:                                                    ║"
echo "║  1. GitHub → Repo → Settings → Deploy Keys → Add deploy key ║"
echo "║  2. Yukarıdaki public key'i yapıştır                        ║"
echo "║  3. 'Allow write access' TIKLAМА — sadece okuma yeterli     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
read -p "Deploy key'i GitHub'a ekledin mi? [E/h]: " CONFIRM
if [[ "$CONFIRM" =~ ^[Hh] ]]; then
    echo "Kurulum iptal edildi. Key'i ekleyip tekrar çalıştır."
    exit 1
fi

# 4. Repo clone
echo "[4/7] Repo klonlanıyor..."
mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
    echo "  → Repo zaten mevcut, pull yapılıyor..."
    sudo -u "$APP_USER" git -C "$APP_DIR" pull origin "$BRANCH"
else
    sudo -u "$APP_USER" git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

# 5. Python venv + bağımlılıklar
echo "[5/7] Python ortamı kuruluyor..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/backend/.venv"
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

# 6. Deploy scripti için sudo yetkisi
echo "[6/7] Deploy yetkisi ayarlanıyor..."
SUDOERS_LINE="$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart otomasyon.service"
echo "$SUDOERS_LINE" > /etc/sudoers.d/otomasyon
chmod 440 /etc/sudoers.d/otomasyon

# deploy.sh çalıştırılabilir yap
chmod +x "$APP_DIR/deploy/deploy.sh"

# 7. Systemd servislerini yükle
echo "[7/7] Systemd servisleri yükleniyor..."
cp "$APP_DIR/deploy/otomasyon.service" /etc/systemd/system/
cp "$APP_DIR/deploy/otomasyon-deploy.service" /etc/systemd/system/
cp "$APP_DIR/deploy/otomasyon-deploy.timer" /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now otomasyon.service
systemctl enable --now otomasyon-deploy.timer

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              Kurulum Tamamlandı! ✓                   ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Uygulama  : http://$(hostname -I | awk '{print $1}'):8000/ui"
echo "║  Servis    : systemctl status otomasyon"
echo "║  Loglar    : journalctl -u otomasyon -f"
echo "║  Deploy log: journalctl -u otomasyon-deploy -f"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
