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
| `CustomStepANDKartlar` | Android – Kartlar | henüz boş |
| `CustomStepIOS` | iOS | `temizle` (XCUIElementTypeKey kullandığı için iOS'a özel) |

`driver` = sampler'da oluşturulan `AndroidDriver` / `IOSDriver` (Java Generator şablonundaki `driver`).
Tüm metodlarda **ilk parametre `driver`**, xpath parametreleri **tam xpath string'i**dir
(eski sözlük anahtarı / `findSelector` yok). Liste metodlarında xpath **indexsiz** verilir, index'i metod ekler.

## Metodlar

### Klavye / input
| Eski Cucumber adımı | JMeter çağrısı |
|---|---|
| `I temizle 4` / `I temizle333 4` | `CustomStepIOS.temizle(driver, 4)` |
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

## Taşınmayanlar
- `@Before beforeScenario`, `@After AfterSteps / afterScenario / afterStep3` — Cucumber hook'ları;
  `Scenario` nesnesine, Cucumber log dosyalarına ve RegresyonSetLog DB yazımına bağlı. JMeter'da
  karşılığı tearDown Thread Group / JDBC Sampler ile ayrıca kurulmalı.
- `trueFalse`, `getValue3` — iç yardımcı, dışarı açılmadı.

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
