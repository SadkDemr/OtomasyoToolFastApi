#!/usr/bin/env bash
# ============================================================================
# iOS Cihaz Sunucusu kurulumu — Mac mini (iPhone'lar USB ile bu Mac'e takılı)
# ----------------------------------------------------------------------------
# Kurar (giriş yapmış kullanıcı için; sudo İLE ÇALIŞTIRMAYIN):
#   - Node.js + Appium 2 + XCUITest sürücüsü, libimobiledevice (iPhone listesi)
#   - LaunchAgent'lar (oturum açılınca başlar, çökerse yeniden başlar):
#       com.otomasyon.appium     → appium --address 0.0.0.0 --port 4723
#       com.otomasyon.ios-agent  → ios-node-agent.py (iPhone listesi, port 4724, anahtarlı)
#   - WebDriverAgent imzası Appium'un varsayılan yeteneklerine yazılır
#     (uygulama tarafında ayrıca ayar gerekmez)
#
# Ön koşul: Xcode kurulu ve bir kez açılmış (lisans kabul), Homebrew kurulu,
#           Xcode → Settings → Accounts'ta Apple geliştirici hesabı ekli.
#
# Kullanım:
#   ./setup-macos.sh --team-id ABCDE12345
#   ./setup-macos.sh --team-id ABCDE12345 --wda-bundle-id com.sirket.WebDriverAgentRunner
#   Seçenekler: --port 4723  --agent-port 4724
# ============================================================================
set -euo pipefail

PORT=4723
AGENT_PORT=4724
TEAM_ID=""
WDA_BUNDLE=""
DIR="$HOME/otomasyon-node"
HERE="$(cd "$(dirname "$0")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --team-id)       TEAM_ID="$2"; shift 2 ;;
    --wda-bundle-id) WDA_BUNDLE="$2"; shift 2 ;;
    --port)          PORT="$2"; shift 2 ;;
    --agent-port)    AGENT_PORT="$2"; shift 2 ;;
    -h|--help)       sed -n 2,24p "$0"; exit 0 ;;
    *) echo "Bilinmeyen seçenek: $1"; exit 1 ;;
  esac
done

[[ $EUID -ne 0 ]] || { echo "sudo ile çalıştırmayın (LaunchAgent ve Xcode imzası kullanıcı hesabında çalışır)"; exit 1; }
[[ -n "$TEAM_ID" ]] || { echo "HATA: --team-id gerekli (Apple Developer → Membership → Team ID)"; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "HATA: Xcode bulunamadı. App Store'dan kurup bir kez açın."; exit 1; }
xcodebuild -version | head -1
command -v brew >/dev/null || { echo "HATA: Homebrew yok → https://brew.sh"; exit 1; }

step() { echo; echo "==> $*"; }

step "Node.js + libimobiledevice"
brew list node >/dev/null 2>&1 || brew install node
brew list libimobiledevice >/dev/null 2>&1 || brew install libimobiledevice

step "Appium 2 + XCUITest"
npm install -g appium@2
appium driver install xcuitest || appium driver update xcuitest || true
APPIUM_BIN=$(command -v appium)
NODE_DIR=$(dirname "$(command -v node)")

step "Ajan → $DIR"
mkdir -p "$DIR/logs"
cp "$HERE/ios-node-agent.py" "$DIR/ios-node-agent.py"
if [[ -f "$DIR/agent.token" ]]; then
  TOKEN=$(cat "$DIR/agent.token")          # yeniden kurulumda anahtar değişmesin
else
  TOKEN=$(openssl rand -hex 24)
  echo "$TOKEN" > "$DIR/agent.token"
  chmod 600 "$DIR/agent.token"
fi
PY=$(command -v python3)

CAPS="{\"appium:xcodeOrgId\":\"$TEAM_ID\",\"appium:xcodeSigningId\":\"Apple Development\""
[[ -n "$WDA_BUNDLE" ]] && CAPS="$CAPS,\"appium:updatedWDABundleId\":\"$WDA_BUNDLE\""
CAPS="$CAPS}"

LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA"
cat > "$LA/com.otomasyon.appium.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.otomasyon.appium</string>
  <key>ProgramArguments</key><array>
    <string>$APPIUM_BIN</string>
    <string>--address</string><string>0.0.0.0</string>
    <string>--port</string><string>$PORT</string>
    <string>--log-timestamp</string>
    <string>--default-capabilities</string><string>$CAPS</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$NODE_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/appium.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/appium.log</string>
</dict></plist>
EOF

cat > "$LA/com.otomasyon.ios-agent.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.otomasyon.ios-agent</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>$DIR/ios-node-agent.py</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>AGENT_TOKEN</key><string>$TOKEN</string>
    <key>AGENT_PORT</key><string>$AGENT_PORT</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/agent.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/agent.log</string>
</dict></plist>
EOF
chmod 600 "$LA/com.otomasyon.ios-agent.plist"   # anahtar içeriyor

step "Servisler başlatılıyor"
for svc in com.otomasyon.appium com.otomasyon.ios-agent; do
  launchctl bootout "gui/$(id -u)/$svc" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LA/$svc.plist"
done
sleep 4
curl -s "http://127.0.0.1:$AGENT_PORT/devices" -H "X-Agent-Token: $TOKEN" || true
echo
curl -s "http://127.0.0.1:$PORT/status" | head -c 200 || true
echo

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<mac-ip>")
cat <<EOF

Kurulum tamam.

Uygulamada: Cihaz Havuzu → Cihaz Sunucuları → Ekle
   Platform: iOS   Adres: $IP   Appium: http://$IP:$PORT
   Ajan portu: $AGENT_PORT   Ajan anahtarı: $TOKEN
   (anahtar: $DIR/agent.token)

Her iPhone için bir kez:
  1. USB ile takın → iPhone'da "Bu Bilgisayara Güven" → Güven
  2. Ayarlar → Gizlilik ve Güvenlik → Geliştirici Modu → Aç (iOS 16+, telefon yeniden başlar)
  3. Ayarlar → Geliştirici → "UI Otomasyonunu Etkinleştir" açık
  4. İlk oturumda WebDriverAgent derlenip telefona yüklenir (birkaç dakika). İmza hatası olursa
     Xcode'da Appium'un WebDriverAgent projesini açıp Signing'de takımı seçin:
        open ~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj

Mac mini sürekli açık kalmalı:
  - Sistem Ayarları → Kullanıcılar → Otomatik giriş (LaunchAgent'lar kullanıcı oturumunda çalışır)
  - Uyku kapalı:  sudo pmset -a sleep 0 disksleep 0
Loglar: $DIR/logs/appium.log  |  $DIR/logs/agent.log
EOF
