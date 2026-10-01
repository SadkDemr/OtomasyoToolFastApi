# custom-steps.jar — JMeter Kullanımı

## Kurulum
1. `target/custom-steps.jar` dosyasını JMeter'ın `lib/ext/` klasörüne kopyala.
2. JMeter'ı yeniden başlat.
3. JSR223 Sampler (dil: **groovy**) içinde en üste:
   ```groovy
   import customsteps.CustomStepAND          // Android
   import customsteps.CustomStepANDKartlar   // Android Kartlar
   import customsteps.CustomStepIOS          // iOS
   ```

| Sınıf | Platform | Metodlar |
|---|---|---|
| `CustomStepAND` | Android | MySteps.java'dan taşınanlar (aşağıda) |
| `CustomStepANDKartlar` | Android – Kartlar | Kartlar MySteps'ten taşınanlar (aşağıda) |
| `CustomStepIOS` | iOS | iOS MySteps'ten taşınanlar (aşağıda, `ios` önekli) |

`driver` = sampler'da oluşturulan `AndroidDriver` / `IOSDriver` (Java Generator şablonundaki `driver`).
Tüm metodlarda **ilk parametre `driver`**, xpath parametreleri **tam xpath string'i**dir
(eski sözlük anahtarı / `findSelector` yok). Liste metodlarında xpath **indexsiz** verilir, index'i metod ekler.

## Metodlar

### Klavye / input
| Eski Cucumber adımı | JMeter çağrısı |
|---|---|
| `I am sil with X` | `CustomStepAND.andAlanTemizle(driver, "//*[@resource-id='...:id/etAmount']")` |
| `I verifyInputMaxLength X 11` | `CustomStepAND.andMaxKarakterDogrula(driver, "//*[@resource-id='...:id/etTckn']", 11)` |

### Değer saklama / karşılaştırma
Jar state tutmaz; dönen değeri `vars` ile sakla:
```groovy
// keep variable X  (getAttribute("text"))
vars.put("KeepResult", CustomStepAND.andDegerTut(driver, "//*[@resource-id='...:id/tvTitle']"))

// I save X text as Tutar  (getText())
vars.put("Tutar", CustomStepAND.andMetinKaydet(driver, "//*[@resource-id='...:id/tvAmount']"))

// I compare X to Tutar  (eşit değilse AssertionError -> sampler FAIL)
CustomStepAND.andMetinKarsilastir(driver, "//*[@resource-id='...:id/tvSummaryAmount']", vars.get("Tutar"))
```

### Liste / hesap seçimi
```groovy
// arraylistesi X  -> List<String>
def liste = CustomStepAND.andListeDegerleriniAl(driver, "(//*[@resource-id='...:id/tvAccount'])")
vars.put("HesapListesi", liste.join(";"))

// I hesapbul X Y  /  I hesapbul2 X Y  -> seçilen hesap text'i, bulunamazsa null
def secilen = CustomStepAND.andHesapSec(driver, "(//*[@resource-id='...:id/tvAccount'])", "Cari")
if (secilen == null) throw new AssertionError("Hesap bulunamadı")

// I checkavailablelimit X Y  -> seçilen text, bulunamazsa null
CustomStepAND.andLimitSec(driver, "(//*[@resource-id='...:id/tvLimit'])", "Kredi Kartı")

// I son10transfer  -> başlık listesi (index 2..10)
def transferler = CustomStepAND.andSon10TransferListele(driver)
log.info("Son transfer sayısı: " + transferler.size())
```

### Doğrulamalar
```groovy
// son10transfer tarih kontrol X and Y  -> boolean (kendisi fail etmez)
boolean ok = CustomStepAND.andSon10TransferTarihKontrol(driver,
        "//*[@resource-id='...:id/tvMonth']",
        "//*[@resource-id='...:id/tvPopupDate']")
if (!ok) throw new AssertionError("Liste ayı ile popup tarihi uyuşmuyor")

// islem dogrula  -> önce andDegerTut ile işlem adı saklanmış olmalı
CustomStepAND.andIslemYonlendirmeDogrula(driver, vars.get("KeepResult"))   // yanlış ekransa AssertionError
```

### Popup / izin / banner (yoksa sessizce geçer)
```groovy
CustomStepAND.andPopupKapat(driver)   // boolean: bir butona tıklandı mı
CustomStepAND.andBannerKapat(driver)
CustomStepAND.andIzinVer(driver)
CustomStepAND.andSozlesmeGec(driver)
```

### Akış (Android)
```groovy
// I andKendiIbanYaz -> okunan IBAN'ı döner ve alıcı IBAN alanına yazar
vars.put("KendiIban", CustomStepAND.andKendiIbanYaz(driver))
```

## CustomStepANDKartlar (Android – Kartlar)
| Eski adım | JMeter çağrısı | Döner |
|---|---|---|
| `gerigel` | `CustomStepANDKartlar.andGeriGel(driver)` | — |
| `popupkontrolleri` | `CustomStepANDKartlar.andPopupKapat(driver)` | boolean |
| `popupkontrolleri2` | `CustomStepANDKartlar.andTumPopuplariKapat(driver)` | int |
| `I loginpopupkontrol` | `CustomStepANDKartlar.andLoginPopupGec(driver)` | — |
| `I bannerkapat` (6 kez) | `CustomStepANDKartlar.andBannerKapat(driver)` | — |
| `I izinVerKontrol` | `CustomStepANDKartlar.andIzinVer(driver)` | — |
| `I sozlesmekontrol` | `CustomStepANDKartlar.andSozlesmeGec(driver)` | — |
| `I am sil with X` | `CustomStepANDKartlar.andAlanTemizle(driver, "//xpath")` | — |
| `I verifyInputMaxLength X N` (30 karakter) | `CustomStepANDKartlar.andMaxKarakterDogrula(driver, "//xpath", 8)` | — (FAIL) |
| `keep variable X` | `vars.put("KeepResult", CustomStepANDKartlar.andDegerTut(driver, "//xpath"))` | String |
| `I save X text as Y` | `vars.put("Y", CustomStepANDKartlar.andMetinKaydet(driver, "//xpath"))` | String |
| `I compare X to Y` | `CustomStepANDKartlar.andMetinKarsilastir(driver, "//xpath", vars.get("Y"))` | — (FAIL) |
| `I favori hesap X kontrol et Y` | `CustomStepANDKartlar.andFavoriHesapKontrol(driver, "(//hesapListesi)", "//dashboard")` | boolean |
| `I favori kredikart X kontrol et Y` | `CustomStepANDKartlar.andFavoriKrediKartKontrol(driver, "//kart", "//dashboard")` | boolean |
| `I favori finans X kontrol et Y` | `CustomStepANDKartlar.andFavoriFinansmanKontrol(driver, "(//finansmanListesi)", "//dashboard")` | boolean |
| `gizli kart kontrol X same value Y` | `CustomStepANDKartlar.andGizliKartKontrol(driver, "//kartNo", "//dashboardKartNo")` | — (FAIL) |
| `I kontrolEt X or Y` | `CustomStepANDKartlar.andHangisiGorunuyor(driver, "//xpath1", "//xpath2")` | int (1/2) |
| `I popup kontrol et` | `CustomStepANDKartlar.andIslemDetayPopupKontrol(driver)` | "Taksitsiz"/"Taksitli" |
| `I taksit ayarla X or Y` | `CustomStepANDKartlar.andTaksitAyarla(driver, "//normalPopup", "//ekKartPopup")` | String |
| `I limit guncelle X and Y and Z` | `CustomStepANDKartlar.andLimitGuncelleKontrol(driver, "//metin", "//tamam", "//dogrula")` | boolean |
| `I maskeli para X` | `CustomStepANDKartlar.andMaskeliTutarKontrol(driver, "(//tutarlar)")` | — (FAIL) |
| `I hesapara X Y` | `CustomStepANDKartlar.andHesapParaBirimiKontrol(driver, "(//indexsiz)", "TL")` | — (FAIL) |
| `I basarilibasarisizkontrol X and Y` | `CustomStepANDKartlar.andBasariliBasarisizGirisKontrol(driver, "//basarili", "//basarisiz")` | — (FAIL) |
| `I kisayol X` | `CustomStepANDKartlar.andKisayolMenuDuzenle(driver, "(//tvMenu)[1]")` | — (FAIL) |
| `I agreementcontrol X` | `CustomStepANDKartlar.andSozlesmeOnayKontrol(driver, "//sozlesmeAdi")` | boolean |

## CustomStepIOS (iOS)
iOS'ta değerler `value` attribute'undan okunur. Hesap listeleri iOS'ta 5, 9, 13 … index'lerinde gezilir.

| Eski adım | JMeter çağrısı | Döner |
|---|---|---|
| `I temizle N` | `CustomStepIOS.iosTemizle(driver, 4)` | — |
| `klavye kapat` | `CustomStepIOS.iosKlavyeKapat(driver)` | boolean |
| `I am sil with X` | `CustomStepIOS.iosAlanTemizle(driver, "//xpath")` | — |
| `degeri yaz` | `CustomStepIOS.iosDegerYaz(driver, vars.get("FastLimit"))` | — |
| `tarih X click Y` | `CustomStepIOS.iosMevcuttanYuksekDegerGir(driver, "//input", "//BittiButonu")` | String |
| `Tarih degistir` | `CustomStepIOS.iosTarihDegistir(driver, "29")` | — |
| `keep variable X` | `vars.put("KeepResult", CustomStepIOS.iosDegerTut(driver, "//xpath"))` | String |
| `Valide Et X` / `I talimatlarim kontrol X` | `CustomStepIOS.iosDegerDogrula(driver, "//xpath", vars.get("KeepResult"))` | — (FAIL) |
| `I fastlimitor X` | `vars.put("FastLimit", CustomStepIOS.iosFastLimitAl(driver, "//xpath"))` | String |
| `arraylistesi X` | `vars.putObject("Liste1", CustomStepIOS.iosListeDegerleriniAl(driver, "(//indexsiz)"))` | List |
| `deneme X` | `CustomStepIOS.iosListeKarsilastir(driver, "(//indexsiz)", vars.getObject("Liste1"))` | boolean |
| `listeyi kontrol et X` | `CustomStepIOS.iosListedeDegerBul(driver, "(//indexsiz)", vars.get("KeepResult"))` | boolean |
| `I son10transfer X` | `CustomStepIOS.iosSon10TransferListele(driver, "(//indexsiz)")` | List |
| `Degerleri Tut X Y Z` | `vars.putObject("Metinler", CustomStepIOS.iosGorunenMetinleriTopla(driver))` | List |
| `Degerleri Kontrol Et X` | `CustomStepIOS.iosBildirimIcerikKontrol(driver, "//bildirim", vars.getObject("Metinler"))` | boolean |
| `I hesapbul X Y` | `CustomStepIOS.iosHesapBul(driver, "(//indexsiz)", "USD")` | String (yoksa FAIL) |
| `I hesapsec X Y` | `CustomStepIOS.iosBakiyeliHesapSec(driver, "(//indexsiz)", "TL")` | String / null |
| `I sifir Hesap Sec X Y` | `CustomStepIOS.iosSifirBakiyeliHesapSec(driver, "(//indexsiz)", "TL")` | String / null |
| `I bakiyesiz hesap sec X` | `CustomStepIOS.iosBakiyesizHesapSec(driver, "(//indexsiz)")` | String / null |
| `I hesapara X Y` | `CustomStepIOS.iosHesapParaBirimiKontrol(driver, "(//indexsiz)", "TL")` | — (FAIL) |
| `son10transfer tarih kontrol X and Y` | `CustomStepIOS.iosSon10TransferTarihKontrol(driver, "//ay", "//popupTarih")` | boolean |
| `islem dogrula` | `CustomStepIOS.iosIslemYonlendirmeDogrula(driver, vars.get("KeepResult"))` | — (FAIL) |
| `I basarisizgiris X and Y` | `CustomStepIOS.iosBasariliBasarisizGirisKontrol(driver, "//basarili", "//basarisiz")` | — (FAIL) |
| `popup gec X` | `CustomStepIOS.iosPopupGec(driver, "//VazgecButonu")` | boolean |
| `Hata Gec X` | `CustomStepIOS.iosHataGec(driver, "//tekrarTiklanacak")` | boolean |
| `test X` | `CustomStepIOS.iosKisayolMenuSifirla(driver, "//ilkKisayol")` | — |
| `SetUp` | `CustomStepIOS.iosSqlApiCalistir("http://api/...", "UPDATE ...", "Prep")` | String |
| `I see oto X` | `CustomStepIOS.iosOtoGorulurYaz("C:/temp/output.txt", "Hesaplar")` | — |
| `I clickoto X` | `CustomStepIOS.iosOtoTiklanirYaz("C:/temp/output.txt", "Hesaplar")` | — |

Ayrıntılı açıklama ve örnekler: Java Generator sayfası → **📘 Custom Step Rehberi**.

## Taşınmayanlar
- `@Before beforeScenario`, `@After AfterSteps / afterScenario / afterStep3` — Cucumber hook'ları;
  `Scenario` nesnesine, Cucumber log dosyalarına ve RegresyonSetLog DB yazımına bağlı. JMeter'da
  karşılığı tearDown Thread Group / JDBC Sampler ile ayrıca kurulmalı.
- `trueFalse`, `getValue3` — iç yardımcı, dışarı açılmadı.
- Kartlar: `seen element` (iOS xpath'li, değeri hiç kullanılmıyordu) ve içi boş `son hareketler` taşınmadı.
- iOS: `yukari`, `test2`, `engin` — içleri boştu. `temizle333`, `hesapSec2` (AND) birleştirildi.
- iOS `son hareketler` Android resource-id'leri kullandığı için `CustomStepAND.andSonHareketleriListele(driver, 3)` olarak AND'e taşındı.

## Derleme
```bash
mvn package            # -> target/custom-steps.jar
```
Maven yoksa:
```bash
javac -encoding UTF-8 --release 17 -cp ~/.m2/repository/org/seleniumhq/selenium/selenium-api/4.13.0/selenium-api-4.13.0.jar \
      -d target/classes src/main/java/customsteps/*.java
jar cf target/custom-steps.jar -C target/classes customsteps
```
`selenium-api` jar'a gömülmez (provided) — JMeter'daki selenium ile çakışıyordu.
