# Offline Sunucu Kurulumu

Bu klasördeki scriptler, internete **hiçbir şekilde** çıkamayan bir Windows x64
sunucuya OtomasyoTool'u kurmak için kullanılır.

## 1. Build makinesinde (internetli) bundle oluştur

```
cd backend
powershell -File deploy\build_offline_bundle.ps1 -OutputDir .\OtomasyoTool-Offline-Bundle -ChromeMajorVersion 136
```

`-ChromeMajorVersion` parametresini sunucuda kurulu Chrome'un ana sürümüyle
eşleştirin (sunucuda `chrome://version` sayfasından kontrol edilebilir).

Çıktı: `OtomasyoTool-Offline-Bundle\` klasörü (birkaç GB, wheels + Node + JDK +
ADB + chromedriver + Python installer + kaynak kod içerir).

## 2. USB/harici disk ile sunucuya taşı

`OtomasyoTool-Offline-Bundle` klasörünü olduğu gibi sunucuya kopyalayın.

## 3. Sunucuda kur (internet YOK, gerekmez)

```
cd OtomasyoTool-Offline-Bundle
install_offline.bat C:\OtomasyoTool
```

Script başarısız olursa (`HATA: ...`), ilgili adımı (Python kurulumu / pip
install / dosya kopyalama) yeniden çalıştırın; script internete çıkmaz, tüm
hata nedenleri yerel dosya eksikliği veya izin sorunudur.

## 4. Admin kullanıcı oluştur ve başlat

```
cd C:\OtomasyoTool\backend
venv\Scripts\python.exe make_admin.py
run_offline.bat
```

## 5. Doğrulama Kontrol Listesi

- [ ] `http://localhost:8000/docs` (Swagger) tarayıcıdan açılıyor.
- [ ] `http://localhost:8000/ui` web arayüzü açılıyor, admin ile giriş yapılabiliyor.
- [ ] `platform-tools\adb.exe devices` bağlı fiziksel Android cihazı listeliyor.
- [ ] Örnek bir Web (Chrome/Selenium) senaryosu uçtan uca çalışıyor — `chromedriver`
      internetten indirilmeye çalışılmıyor (loglarda `Yerel ChromeDriver
      kullaniliyor (offline mod)` satırı görünmeli).
- [ ] Örnek bir Mobil (Appium) senaryosu fiziksel cihazda çalışıyor —
      `appium-global\appium.cmd driver list --installed` çıktısında
      `uiautomator2` görünüyor. Görünmüyorsa: internete çıkmadan
      `appium-global\appium.cmd driver install --source=local <appium-global
      icindeki appium-uiautomator2-driver klasor yolu>` ile yeniden kaydedin.
- [ ] Bir Desktop otomasyon senaryosu (pywinauto) çalışıyor.
- [ ] Kurulum ve çalışma sırasında Kaynak Monitörü / `netstat -ano` ile dışa
      giden bağlantı denemesi olmadığı teyit edildi.

## 6. Gelecekte güncelleme

Kod veya bağımlılık değiştiğinde: build makinesinde bundle'ı yeniden üretin
(`build_offline_bundle.ps1`), USB ile taşıyın, sunucuda `install_offline.bat`'ı
tekrar çalıştırın (mevcut `venv`/klasörlerin üzerine güvenle yazar). Sunucu bu
süreçte de hiçbir zaman `git pull` veya internetten indirme yapmaz.
