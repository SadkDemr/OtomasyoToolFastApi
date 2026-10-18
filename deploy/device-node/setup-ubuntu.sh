#!/usr/bin/env bash
# ============================================================================
# Cihaz Sunucusu (Device Node) kurulumu — Ubuntu 22.04 / 24.04
# ----------------------------------------------------------------------------
# Telefonların USB ile takılı olduğu makinede (ör. KVM ana makinesi) çalıştırılır.
# Kurar:
#   - Android platform-tools (güncel adb) + udev kuralları
#   - Node.js 20 + Appium 2 + UiAutomator2 sürücüsü (+ Java, ANDROID_HOME)
#   - systemd servisleri:
#       otomasyon-adb     → adb -a -P 5037 nodaemon server start  (ağı dinler)
#       otomasyon-appium  → appium --address 0.0.0.0 --port 4723
#   - Güvenlik duvarı: 5037 ve 4723 portları YALNIZCA uygulama VM'ine açık
#
# Kullanım:
#   sudo ./setup-ubuntu.sh --app-ip 192.168.1.50            # uygulamanın (Windows VM) IP'si
#   sudo ./setup-ubuntu.sh --app-ip 192.168.1.50 --app-ip 192.168.1.51   # birden fazla
#   Seçenekler: --adb-port 5037  --appium-port 4723  --no-firewall
# ============================================================================
set -euo pipefail

ADB_PORT=5037
APPIUM_PORT=4723
APP_IPS=()
FIREWALL=1
SVC_USER=devicenode
SDK=/opt/android-sdk

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-ip)      APP_IPS+=("$2"); shift 2 ;;
    --adb-port)    ADB_PORT="$2"; shift 2 ;;
    --appium-port) APPIUM_PORT="$2"; shift 2 ;;
    --no-firewall) FIREWALL=0; shift ;;
    -h|--help)     sed -n 2,20p "$0"; exit 0 ;;
    *) echo "Bilinmeyen seçenek: $1"; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "sudo ile çalıştırın"; exit 1; }
if [[ $FIREWALL -eq 1 && ${#APP_IPS[@]} -eq 0 ]]; then
  echo "HATA: --app-ip <uygulama VM IP> gerekli (portlar yalnız ona açılır). Güvenlik duvarı istemiyorsanız --no-firewall."
  exit 1
fi

step() { echo; echo "==> $*"; }

step "Paketler"
apt-get update -y
apt-get install -y curl unzip ca-certificates openjdk-17-jre-headless android-sdk-platform-tools-common

step "Android platform-tools (güncel adb) → $SDK/platform-tools"
mkdir -p "$SDK"
tmp=$(mktemp -d)
curl -fsSL -o "$tmp/pt.zip" https://dl.google.com/android/repository/platform-tools-latest-linux.zip
rm -rf "$SDK/platform-tools"
unzip -q "$tmp/pt.zip" -d "$SDK"
rm -rf "$tmp"
ln -sf "$SDK/platform-tools/adb" /usr/local/bin/adb
adb version | head -1

step "Servis kullanıcısı: $SVC_USER (USB erişimi için plugdev grubunda)"
id "$SVC_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$SVC_USER"
usermod -aG plugdev "$SVC_USER"
udevadm control --reload-rules && udevadm trigger || true

step "Node.js 20 + Appium 2 + UiAutomator2"
if ! command -v node &>/dev/null || [[ $(node -v | sed 's/v\([0-9]*\).*/\1/') -lt 18 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
npm install -g appium@2
sudo -u "$SVC_USER" -H env ANDROID_HOME="$SDK" appium driver install uiautomator2 || \
  sudo -u "$SVC_USER" -H env ANDROID_HOME="$SDK" appium driver update uiautomator2 || true
APPIUM_BIN=$(command -v appium)

step "systemd servisleri"
cat > /etc/systemd/system/otomasyon-adb.service <<EOF
[Unit]
Description=Otomasyon - adb sunucusu (ag uzerinden, port $ADB_PORT)
After=network-online.target
Wants=network-online.target

[Service]
User=$SVC_USER
Environment=HOME=/home/$SVC_USER
ExecStartPre=-$SDK/platform-tools/adb -P $ADB_PORT kill-server
ExecStart=$SDK/platform-tools/adb -a -P $ADB_PORT nodaemon server start
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/otomasyon-appium.service <<EOF
[Unit]
Description=Otomasyon - Appium (port $APPIUM_PORT)
After=otomasyon-adb.service
Requires=otomasyon-adb.service

[Service]
User=$SVC_USER
Environment=HOME=/home/$SVC_USER
Environment=ANDROID_HOME=$SDK
Environment=ANDROID_SDK_ROOT=$SDK
Environment=ANDROID_ADB_SERVER_PORT=$ADB_PORT
Environment=PATH=$SDK/platform-tools:/usr/local/bin:/usr/bin:/bin
# adb_shell: JMeter'a üretilen Java kodu 'mobile: shell' kullanıyor
ExecStart=$APPIUM_BIN --address 0.0.0.0 --port $APPIUM_PORT --allow-insecure adb_shell --log-timestamp
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now otomasyon-adb.service
sleep 2
systemctl enable --now otomasyon-appium.service

if [[ $FIREWALL -eq 1 ]]; then
  step "Güvenlik duvarı: $ADB_PORT ve $APPIUM_PORT yalnız ${APP_IPS[*]} için"
  # DİKKAT: Bu bir KVM ana makinesi. ufw'yi burada AÇMIYORUZ — varsayılan "gelen/yönlendirme
  # engelle" politikası bridge üzerindeki VM'lerin ağını ve makinedeki diğer servisleri kesebilir.
  # ufw zaten açıksa ona kural eklenir; değilse yalnızca bu iki porta iptables INPUT kuralı konur.
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    for ip in "${APP_IPS[@]}"; do
      ufw allow from "$ip" to any port "$ADB_PORT" proto tcp
      ufw allow from "$ip" to any port "$APPIUM_PORT" proto tcp
    done
    ufw deny "$ADB_PORT"/tcp
    ufw deny "$APPIUM_PORT"/tcp
    ufw status numbered
  else
    for port in "$ADB_PORT" "$APPIUM_PORT"; do
      # önceki kurulumdan kalan kurallar (tekrar çalıştırmada çoğalmasın)
      while iptables -D INPUT -p tcp --dport "$port" -j DROP 2>/dev/null; do :; done
      for ip in "${APP_IPS[@]}"; do
        while iptables -D INPUT -p tcp -s "$ip" --dport "$port" -j ACCEPT 2>/dev/null; do :; done
      done
      iptables -A INPUT -p tcp --dport "$port" -j DROP
      for ip in "${APP_IPS[@]}"; do
        iptables -I INPUT -p tcp -s "$ip" --dport "$port" -j ACCEPT
      done
      iptables -I INPUT -p tcp -s 127.0.0.1 --dport "$port" -j ACCEPT   # makinenin kendisi
    done
    DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
    netfilter-persistent save
    iptables -S INPUT | grep -E -- "--dport ($ADB_PORT|$APPIUM_PORT)"
  fi
fi

step "Durum"
sleep 3
systemctl --no-pager --lines=0 status otomasyon-adb otomasyon-appium || true
echo
adb -P "$ADB_PORT" devices -l || true
IP=$(hostname -I | awk '{print $1}')
cat <<EOF

Kurulum tamam.
  • Telefonları USB ile takın; telefonda "USB hata ayıklamaya izin ver" sorusunu ONAYLAYIN
    ("Bu bilgisayardan her zaman izin ver" işaretli). İzin bekleyen telefon 'unauthorized' görünür.
  • KVM: Telefonlar daha önce VM'e USB passthrough ile verildiyse VM ayarlarından KALDIRIN —
    telefonu aynı anda yalnız bir adb sunucusu tutabilir.
  • Uygulamada: Cihaz Havuzu → Cihaz Sunucuları → Ekle
        Adres: $IP   adb portu: $ADB_PORT   Appium: http://$IP:$APPIUM_PORT
    "Bağlantıyı test et" ile adb ve Appium'u doğrulayın.
  • Windows VM'den elle deneme:  adb -H $IP -P $ADB_PORT devices
  • Loglar: journalctl -u otomasyon-adb -f   |   journalctl -u otomasyon-appium -f
EOF
