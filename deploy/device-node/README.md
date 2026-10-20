# Cihaz Sunucusu (Device Node)

Uygulama bir VM'de (ya da ayrı bir sunucuda) çalışırken telefonlar başka makinelere USB ile
takılı olabilir. Bu makinelere **cihaz sunucusu** denir; uygulama onlara ağ üzerinden bağlanır.

```
[Windows VM — Uygulama]  ──ağ──>  [Ubuntu (KVM ana makine)]  adb sunucusu :5037 + Appium :4723
                                     └─ USB ─ Android telefonlar
```

- Telefon listesi, canlı ekran, kayıt modu (dokun/yaz) → uzaktaki **adb sunucusu** (`adb -H <ip> -P 5037`)
- Oturum / koşum / AI Job → telefonun takılı olduğu makinedeki **Appium** (`http://<ip>:4723`)
- Üretilen script'lerin kendi adb çağrıları → `ADB_SERVER_SOCKET=tcp:<ip>:5037` ile aynı sunucu

Uygulamanın kendi makinesine takılı telefonlar için hiçbir şey gerekmez ("Bu sunucu").

## Ubuntu kurulumu

```bash
sudo ./setup-ubuntu.sh --app-ip <Windows VM IP>
```

Ardından uygulamada **Cihaz Havuzu → Cihaz Sunucuları → Ekle** (Adres = Ubuntu IP) ve
**Bağlantıyı test et**.

## Dikkat

- **Güvenlik:** Ağı dinleyen adb, aynı ağdaki herkesin telefonları kontrol edebilmesi demektir.
  Betik 5037 ve 4723 portlarını yalnızca `--app-ip` adreslerine açar (ufw zaten açıksa ufw
  kuralı, değilse sadece bu iki porta iptables kuralı — ufw'yi kendisi açmaz, çünkü KVM ana
  makinesinde varsayılan politika bridge'deki VM'lerin ağını kesebilir).
  `--no-firewall` kullanırsanız bu kısıtı kendiniz sağlayın.
- **USB passthrough:** Telefonlar daha önce KVM ile VM'e verildiyse VM'den kaldırın — telefonu
  aynı anda yalnızca bir adb sunucusu tutabilir.
- **İlk bağlantı:** Her telefonda bu makine için "USB hata ayıklamaya izin ver" onaylanmalı.
- **Canlı ekran:** Uzak telefonda Appium'un MJPEG akışı kullanılmaz (akış portu o makinenin
  localhost'una açılır); ekran adb ile PNG olarak alınır — yerel telefona göre daha yavaştır.

## iOS — Mac mini kurulumu

iPhone'lar Mac'e takılır; Mac'te Appium (XCUITest) ve küçük bir cihaz listesi ajanı
(`ios-node-agent.py`, port 4724, anahtarlı) çalışır — Appium iPhone listesi vermediği için.

```bash
./setup-macos.sh --team-id <Apple Team ID>            # sudo OLMADAN, Mac'te giriş yapmış kullanıcıyla
```

Ön koşul: Xcode kurulu ve bir kez açılmış, Homebrew, Xcode'da Apple geliştirici hesabı ekli.
Betik sonunda yazdırılan **ajan anahtarını** uygulamada Cihaz Havuzu → Cihaz Sunucuları →
Platform: iOS ile girin. Her iPhone'da bir kez: "Bu Bilgisayara Güven", Geliştirici Modu,
Ayarlar → Geliştirici → UI Otomasyonu. İlk oturumda WebDriverAgent derlenir (birkaç dakika).

- Uygulamada iPhone için **App Package** alanına **Bundle ID** yazılır (ör. `com.sirket.app`).
- Adımlar Android ile aynı yazılır; Android XPath'leri (`@text`, `android.widget.EditText`...)
  koşumda iOS karşılıklarına (`@label/@value/@name`, `XCUIElementType...`) çevrilir.
- iPhone canlı ekranı yalnız açık oturumda (Appium ekran görüntüsü) gösterilir.
- **Kayıt modu iPhone'da da çalışır** (dokun / ✎ yazı / sağ tık doğrulama / kaydır / geri,
  locator dosyası, uygulama haritası). XCUITest sayfa kaynağı alındığı anda Android benzeri
  özniteliklere çevrilir; dokunuşlar Appium'dan gider (adb yok), bu yüzden Android'e göre
  biraz daha yavaştır. Uygulama sürümü iPhone'da okunmaz (haritada sürüm boş kalır).
- **Güvenlik:** Mac'teki Appium (4723) kimlik doğrulaması yapmaz; Mac'i yalnızca uygulama
  VM'inin erişebildiği bir ağ bölümünde tutun (ajan anahtarla korunur).
- Mac mini sürekli açık ve **otomatik girişli** olmalı (LaunchAgent'lar kullanıcı oturumunda çalışır).

### Aynı Mac'e Android telefonlar da takılıysa

```bash
./setup-macos.sh --team-id <Apple Team ID> --android
```

Ek olarak güncel adb (`~/otomasyon-node/android-sdk`), Java 17, UiAutomator2 sürücüsü ve ağı
dinleyen adb servisi (`com.otomasyon.adb`, port 5037) kurulur; Appium hem iPhone hem Android'e
hizmet verir. Uygulamada aynı Mac için **iki kayıt** eklenir: biri Platform **iOS** (ajan
anahtarıyla), biri Platform **Android** (adb portu 5037) — ikisinde de Appium `http://<mac-ip>:4723`.
Bu Mac'te `adb kill-server` demeyin (servisin adb sunucusunu kapatır; servis kendini yeniden başlatır).
