for s in com.otomasyon.appium com.otomasyon.adb com.otomasyon.ios-agent; do
  launchctl bootout "gui/$(id -u)/$s" 2>/dev/null
  rm -f ~/Library/LaunchAgents/$s.plist
done
rm -rf ~/otomasyon-node ~/otomasyon-node-setup
launchctl list | grep otomasyon
Bu adım üç servisi, logları, ajan anahtarını ve bizim indirdiğimiz adb'yi siliyor. Son komut hiçbir şey yazdırmamalı.

2. Diğerleri bizden mi geldi, bak

bash
ls -ldT $(brew --prefix)/Cellar/{node,libimobiledevice,openjdk@17} 2>/dev/null
ls -ldT "$(npm root -g)/appium"
ls -ldT ~/.appium/node_modules/appium-* 2>/dev/null
appium -v
grep -h -E "appium@[0-9]" ~/.npm/_logs/*.log 2>/dev/null | tail -10
Tarihi bugün olan satırlar bizim kurulumdan geliyor, eski tarihliler zaten vardı. Çıktıyı yapıştır; sadece bugün eklenenleri kaldırmak ve Appium'u eski sürümüne döndürmek için kesin komutları vereyim. Yaklaşık şöyle olacak:
bash
brew uninstall openjdk@17
appium driver uninstall uiautomator2
npm install -g appium@<eski sürüm>
Bunları şimdi çalıştırma, yukarıdaki çıktıya göre netleştireceğiz.

3. Mevcut sistemi yeniden başlat

Bizim betik Mac'teki adb'yi kapatmıştı. Mac'te önceden çalışan sistemi (GADS ya da kendi Appium'unuz) yeniden başlatın; adb'yi o araç kendisi açar. Emin olmak için Mac'i yeniden başlatmak da yeterli.

4. Uygulamada

Cihaz Havuzu → Cihaz Sunucuları'na 10.40.9.167 için kayıt eklediysen sil.
