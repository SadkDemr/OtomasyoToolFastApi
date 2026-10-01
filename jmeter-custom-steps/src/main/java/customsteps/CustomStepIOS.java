package customsteps;

import org.openqa.selenium.By;
import org.openqa.selenium.JavascriptExecutor;
import org.openqa.selenium.NoSuchElementException;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Predicate;

/**
 * iOS — JMeter JSR223 Sampler'lardan cagrilacak custom adimlar (iOS MySteps.java'dan tasindi).
 * WebDriver arayuzu kullanilir (IOSDriver da bu arayuzu implement eder),
 * boylece io.appium.java_client'a derleme zamaninda bagimlilik gerekmez.
 * Yeni method eklerken imza kuralini koru: ilk parametre WebDriver,
 * geri kalani adimin ihtiyac duydugu deger(ler).
 *
 * MySteps'ten farklar:
 *  - device.findSelector(key) yerine dogrudan xpath string'i alinir.
 *  - Sinif icinde state tutulmaz (KeepResult, keepResultArray, DegerListesi). Deger ureten
 *    metodlar String/List dondurur, JMeter tarafinda vars.put / vars.putObject ile saklanir.
 *  - iOS'ta element degeri "value" attribute'undan okunur.
 *
 * Kullanim (JSR223 - Groovy):
 *   import customsteps.CustomStepIOS;
 *   CustomStepIOS.iosTemizle(driver, 4);
 */
public final class CustomStepIOS {

    private static final By DELETE_KEY_EN = By.xpath("//XCUIElementTypeKey[@name='delete' or @name='Delete']");
    private static final By DELETE_KEY_TR = By.xpath("//XCUIElementTypeKey[@name='Sil']");

    private static final List<By> KLAVYE_KAPAT_BUTONLARI = Arrays.asList(
            By.xpath("//XCUIElementTypeButton[@name='Bitti']"),
            By.xpath("//XCUIElementTypeButton[@name='Done']"),
            By.xpath("//XCUIElementTypeButton[@name='Kapat']")
    );

    /** Tarih degistir adimindaki DatePicker'in gun tekerlegi. */
    private static final String TARIH_GUN_TEKERLEGI = "//XCUIElementTypeWindow[3]/XCUIElementTypeOther/XCUIElementTypeOther/XCUIElementTypeDatePicker/XCUIElementTypePicker/XCUIElementTypePickerWheel[1]";

    /** Hesap listelerinde iOS'ta her hesap 4 elementte bir tekrar ediyor: 5, 9, 13 ... */
    private static final int HESAP_ILK_INDEX = 5;
    private static final int HESAP_ADIM = 4;
    private static final int HESAP_SON_INDEX = 200;

    /** Kisa ay adi (liste) -> ay numarasi (popup tarihi). */
    private static final Map<String, String> AYLAR = new HashMap<>();

    /** islem yonlendirme: saklanan islem adi -> yonlenilmesi gereken ekran basligi. */
    private static final Map<String, String> ISLEM_BASLIKLARI = new HashMap<>();

    /** Eski getValue3 switch'i: index (0..10) -> eklenen deger. */
    private static final int[] VALUE3_OFFSETS = {5, 8, 13, 18, 23, 28, 33, 38, 43, 48, 53};

    static {
        String[][] aylar = {
                {"Oca", "01"}, {"Şub", "02"}, {"Mar", "03"}, {"Nis", "04"},
                {"Mys", "05"}, {"May", "05"}, {"Haz", "06"}, {"Tem", "07"},
                {"Agu", "08"}, {"Ağu", "08"}, {"Eyl", "09"}, {"Eki", "10"},
                {"Kas", "11"}, {"Ara", "12"}
        };
        for (String[] ay : aylar) {
            AYLAR.put(ay[0], ay[1]);
        }

        ISLEM_BASLIKLARI.put("Hesaplarım Arası Havale", "Hesaplarım Arası Havale");
        ISLEM_BASLIKLARI.put("Kendi VK Hesabıma", "Hesaplarım Arası Havale");
        ISLEM_BASLIKLARI.put("HESABA HAVALE", "EFT / Havale / FAST");
    }

    private CustomStepIOS() {
    }

    // ------------------------------------------------------------------
    // Klavye / input
    // ------------------------------------------------------------------

    /**
     * "I temizle N" — input alaninda xpath olmadigi durumlarda klavyedeki silme tusuna
     * N kez basar. Cihaz dili EN/TR olabileceginden hangi tusun ekranda oldugu tek
     * seferde tespit edilir (eski kod TR'ye gecince sayaci sifirliyordu).
     */
    public static void iosTemizle(WebDriver driver, int adet) {
        By deleteKey = resolveDeleteKeyLocator(driver);
        for (int i = 0; i < adet; i++) {
            driver.findElement(deleteKey).click();
        }
    }

    /**
     * "klavye kapat" — klavyedeki Bitti / Done / Kapat butonlarindan gorunen ilkine basar.
     *
     * @return bir butona basildiysa true (klavye acik degilse false, hata vermez)
     */
    public static boolean iosKlavyeKapat(WebDriver driver) {
        return clickFirstVisible(driver, KLAVYE_KAPAT_BUTONLARI);
    }

    /** "I am sil with X" — elementin icerigini temizler. */
    public static void iosAlanTemizle(WebDriver driver, String xpath) {
        WebElement element = driver.findElement(By.xpath(xpath));
        System.out.println("silmek istenen nesne: " + element.getAttribute("value"));
        element.clear();
    }

    /**
     * "degeri yaz" — o an odakta olan input'a degeri yazar
     * (eski kod: driver.getKeyboard().releaseKey(KeepResult)). Genelde iosFastLimitAl ile kullanilir.
     */
    public static void iosDegerYaz(WebDriver driver, String deger) {
        System.out.println("Yazılan değer: " + deger);
        driver.switchTo().activeElement().sendKeys(deger);
    }

    /**
     * "tarih X click Y" — input'taki sayiyi okuyup 1 fazlasini yazar (mevcuttan yuksek
     * tutar senaryosu), sonra verilen elemana (klavye butonu vb.) tiklar.
     *
     * @return yazilan yeni deger
     */
    public static String iosMevcuttanYuksekDegerGir(WebDriver driver, String inputXpath, String tiklanacakXpath) {
        WebElement input = driver.findElement(By.xpath(inputXpath));
        int mevcut = Integer.parseInt(input.getAttribute("value").trim());
        String yeni = String.valueOf(mevcut + 1);
        System.out.println("Mevcuttan Yüksek Miktar : " + yeni);
        input.clear();
        input.sendKeys(yeni);
        click(driver, tiklanacakXpath);
        return yeni;
    }

    /** "Tarih degistir" — tarih seciciyi (DatePicker) gun tekerleginde verilen gune getirir, klavyeyi kapatir. */
    public static void iosTarihDegistir(WebDriver driver, String gun) {
        iosTarihDegistir(driver, TARIH_GUN_TEKERLEGI, gun);
    }

    /** Tarih degistir — tekerlek xpath'i farkli ise bu overload kullanilir. */
    public static void iosTarihDegistir(WebDriver driver, String tekerlekXpath, String deger) {
        WebElement tekerlek = driver.findElement(By.xpath(tekerlekXpath));
        tekerlek.sendKeys(deger);
        System.out.println("Tekerlek değeri: " + tekerlek.getAttribute("value"));
        iosKlavyeKapat(driver);
    }

    // ------------------------------------------------------------------
    // Deger saklama / karsilastirma (JMeter tarafinda vars ile saklanir)
    // ------------------------------------------------------------------

    /** "keep variable X" — elementin value'sunu dondurur. */
    public static String iosDegerTut(WebDriver driver, String xpath) {
        String deger = value(driver, xpath);
        System.out.println("Tutulan Deger: " + deger);
        return deger;
    }

    /**
     * "Valide Et X" / "I talimatlarim kontrol X" — elementin value'su beklenen degere
     * esit degilse AssertionError (eski kod sadece log basiyordu).
     */
    public static void iosDegerDogrula(WebDriver driver, String xpath, String beklenen) {
        String gelen = value(driver, xpath);
        if (beklenen == null || !beklenen.equals(gelen)) {
            throw new AssertionError("Değerler Eşleşmedi! Ekrandaki = [" + gelen + "], beklenen = [" + beklenen + "]");
        }
        System.out.println("Değerler Eşleşti = " + gelen);
    }

    /**
     * "I fastlimitor X" — FAST limit metninden (ilk 20 karakterden sonrasi) tutari
     * kurussuz ve ayracsiz sayi olarak cikarir. Ornek: "... 20.000,00 TL" -> "20000".
     */
    public static String iosFastLimitAl(WebDriver driver, String xpath) {
        String metin = value(driver, xpath);
        if (metin == null || metin.length() <= 20) {
            throw new AssertionError("FAST limit metni beklenenden kısa: [" + metin + "]");
        }
        String rakamlar = metin.substring(20).replaceAll("[^\\d]", "");
        String limit = rakamlar.substring(0, rakamlar.length() - 2);
        System.out.println("FAST limit: " + limit);
        return limit;
    }

    // ------------------------------------------------------------------
    // Liste islemleri
    // ------------------------------------------------------------------

    /**
     * "arraylistesi X" — indexsiz xpath + [getValue3(1..7)] elemanlarinin value'larini
     * toplar; "0,00" ve "11.111,00" iceren degerler alinmaz. Ilk bulunamayan elemanda durur.
     */
    public static List<String> iosListeDegerleriniAl(WebDriver driver, String baseXpath) {
        List<String> sonuc = new ArrayList<>();
        try {
            for (int say = 1; say <= 7; say++) {
                String deger = value(driver, baseXpath + "[" + getValue3(say) + "]");
                System.out.println("Gelen Baslik: " + deger);
                if (!isExcludedAmount(deger)) {
                    sonuc.add(deger);
                }
            }
        } catch (NoSuchElementException e) {
            System.out.println("Liste sonu, nesne kalmadı.");
        }
        System.out.println("Arraydeki listeler: " + sonuc);
        return sonuc;
    }

    /**
     * "deneme X" — ikinci listedeki (index 5, 9, 13 ... 53) value'lari toplayip daha once
     * iosListeDegerleriniAl ile alinan listeyle karsilastirir. "0,00 TL" ve "11.111,00" alinmaz.
     *
     * @return iki liste esitse true (kendisi fail etmez)
     */
    public static boolean iosListeKarsilastir(WebDriver driver, String baseXpath, List<String> oncekiListe) {
        List<String> yeniListe = new ArrayList<>();
        try {
            for (int say = 5; say <= 55; say += 4) {
                String deger = value(driver, baseXpath + "[" + say + "]");
                if (!deger.contains("0,00 TL") && !deger.contains("11.111,00")) {
                    yeniListe.add(deger);
                }
            }
        } catch (NoSuchElementException e) {
            System.out.println("Liste sonu, nesne kalmadı.");
        }
        boolean esit = yeniListe.equals(oncekiListe);
        System.out.println(esit ? "İki Array Değerleri Eşit.." : "İki Array Değerleri Eşit Değil: " + yeniListe + " <> " + oncekiListe);
        return esit;
    }

    /**
     * "listeyi kontrol et X" — listede (index 1..30) aranan degerle birebir esit bir
     * eleman var mi bakar.
     *
     * @return bulunduysa true
     */
    public static boolean iosListedeDegerBul(WebDriver driver, String baseXpath, String aranan) {
        for (int say = 1; say <= 30; say++) {
            List<WebElement> els = driver.findElements(By.xpath(baseXpath + "[" + say + "]"));
            if (els.isEmpty()) {
                break;
            }
            String deger = els.get(0).getAttribute("value");
            System.out.println("Okunan Değer : " + deger);
            if (aranan != null && aranan.equals(deger)) {
                System.out.println("Değerler Eşleşti: " + deger);
                return true;
            }
        }
        System.out.println("Listede bulunamadı: " + aranan);
        return false;
    }

    /**
     * "I son10transfer X" — Son 10 Transfer listesindeki basliklari (index 5, 10 ... 55)
     * okur. Liste bossa "Herhangi bir işleminiz bulunmamaktadır." mesajini kontrol edip loglar.
     */
    public static List<String> iosSon10TransferListele(WebDriver driver, String baseXpath) {
        List<String> basliklar = new ArrayList<>();
        try {
            for (int count = 5; count <= 55; count += 5) {
                String baslik = value(driver, baseXpath + "[" + count + "]");
                System.out.println("Gelen Baslik: " + baslik);
                basliklar.add(baslik);
            }
        } catch (NoSuchElementException e) {
            System.out.println("Nesne Kalmadı!");
        }
        if (basliklar.isEmpty()) {
            boolean bosMesaj = !driver.findElements(By.xpath("//XCUIElementTypeStaticText[@name='Herhangi bir işleminiz bulunmamaktadır.']")).isEmpty();
            System.out.println("Boş Liste mesajı görünüyor: " + bosMesaj);
        }
        System.out.println("Gelen Değer Sayısı: " + basliklar.size());
        return basliklar;
    }

    /**
     * "Degerleri Tut X Y Z" — ekrandaki gorunur StaticText'lerin (index 3..19) value'larini toplar.
     * Sonuc iosBildirimIcerikKontrol'e verilir.
     */
    public static List<String> iosGorunenMetinleriTopla(WebDriver driver) {
        List<String> degerler = new ArrayList<>();
        try {
            for (int i = 3; i <= 19; i++) {
                String deger = value(driver, "(//XCUIElementTypeStaticText[@visible='true'])[" + i + "]");
                System.out.println("Eklendi " + deger);
                degerler.add(deger);
            }
        } catch (NoSuchElementException e) {
            System.out.println("Görünür metin kalmadı.");
        }
        return degerler;
    }

    /**
     * "Degerleri Kontrol Et X" — bildirim metninin, listedeki verilen index'lerdeki
     * (varsayilan 4 ve 12) degerleri icerip icermedigini kontrol eder.
     * Eski kod index'teki deger yerine tum listeyi ariyordu; index'teki deger aranacak sekilde duzeltildi.
     *
     * @return tum index'lerdeki degerler bildirimde varsa true (kendisi fail etmez)
     */
    public static boolean iosBildirimIcerikKontrol(WebDriver driver, String bildirimXpath, List<String> degerler, int... indexler) {
        if (indexler == null || indexler.length == 0) {
            indexler = new int[]{4, 12};
        }
        String bildirim = value(driver, bildirimXpath);
        System.out.println("Bildirim Değeri: " + bildirim);
        boolean hepsi = true;
        for (int index : indexler) {
            if (index < 0 || index >= degerler.size()) {
                System.out.println("Geçersiz index: " + index);
                hepsi = false;
                continue;
            }
            String paragraf = degerler.get(index);
            boolean iceriyor = bildirim != null && bildirim.contains(paragraf);
            System.out.println("Index " + index + (iceriyor ? " içeriyor: " : " içermiyor: ") + paragraf);
            hepsi &= iceriyor;
        }
        return hepsi;
    }

    // ------------------------------------------------------------------
    // Hesap secimi (iOS hesap listesi: index 5, 9, 13 ... 200)
    // ------------------------------------------------------------------

    /**
     * "I hesapbul X Y" — aranan metni (doviz turu vb.) iceren ilk hesaba tiklar.
     * Bulunamazsa AssertionError (eski kod da senaryoyu bilerek durduruyordu).
     *
     * @return secilen hesabin value'su
     */
    public static String iosHesapBul(WebDriver driver, String baseXpath, String hesapTuru) {
        String secilen = listedeIlkUygunaTikla(driver, baseXpath, d -> d.contains(hesapTuru));
        if (secilen == null) {
            throw new AssertionError("Hesap bulunamadı: " + hesapTuru);
        }
        return secilen;
    }

    /**
     * "I hesapsec X Y" — aranan turu iceren, bakiyesi "0,00"/"11.111,00" olmayan ilk hesaba tiklar.
     * (Eski kod "0,00"i equals ile kontrol ediyordu, fiilen 0 bakiyeli hesabi da seciyordu; contains yapildi.)
     *
     * @return secilen hesabin value'su, bulunamazsa null
     */
    public static String iosBakiyeliHesapSec(WebDriver driver, String baseXpath, String hesapTuru) {
        return listedeIlkUygunaTikla(driver, baseXpath, d -> d.contains(hesapTuru) && !isExcludedAmount(d));
    }

    /**
     * "I sifir Hesap Sec X Y" — aranan turu iceren ve bakiyesi "0,00" olan ilk hesaba tiklar.
     *
     * @return secilen hesabin value'su, bulunamazsa null
     */
    public static String iosSifirBakiyeliHesapSec(WebDriver driver, String baseXpath, String hesapTuru) {
        return listedeIlkUygunaTikla(driver, baseXpath,
                d -> d.contains(hesapTuru) && d.contains("0,00") && !d.contains("11.111,00"));
    }

    /**
     * "I bakiyesiz hesap sec X" — tur fark etmeksizin bakiyesi "0,00" olan ilk hesaba tiklar.
     *
     * @return secilen hesabin value'su, bulunamazsa null
     */
    public static String iosBakiyesizHesapSec(WebDriver driver, String baseXpath) {
        return listedeIlkUygunaTikla(driver, baseXpath, d -> d.contains("0,00"));
    }

    /**
     * "I hesapara X Y" — hesap SECMEZ. Listede verilen para birimi disinda (bakiyeli) bir
     * hesap varsa AssertionError. Ornek: "TL" verilip listede USD hesap gorulurse fail.
     */
    public static void iosHesapParaBirimiKontrol(WebDriver driver, String baseXpath, String paraBirimi) {
        for (int say = HESAP_ILK_INDEX; say <= HESAP_SON_INDEX; say += HESAP_ADIM) {
            List<WebElement> els = driver.findElements(By.xpath(baseXpath + "[" + say + "]"));
            if (els.isEmpty()) {
                break;
            }
            String deger = els.get(0).getAttribute("value");
            System.out.println("Gelen Baslik: " + deger);
            if (!deger.contains(paraBirimi) && !isExcludedAmount(deger)) {
                throw new AssertionError(paraBirimi + " haricinde hesap bulundu: " + deger);
            }
        }
        System.out.println("Sadece " + paraBirimi + " hesaplar listeleniyor.");
    }

    // ------------------------------------------------------------------
    // Dogrulamalar
    // ------------------------------------------------------------------

    /**
     * "son10transfer tarih kontrol X and Y" — listedeki kisa ay adi (Oca, Şub...)
     * ile popupdaki tarihin (gg.aa.yyyy) ay kismini karsilastirir.
     *
     * @return aylar ayni ise true (kendisi fail etmez)
     */
    public static boolean iosSon10TransferTarihKontrol(WebDriver driver, String listeAyXpath, String popupTarihXpath) {
        String listeAy = value(driver, listeAyXpath);
        String popupAy = value(driver, popupTarihXpath).replaceAll("\\.", "").substring(2, 4);
        boolean ayni = popupAy.equals(AYLAR.get(listeAy));
        System.out.println("Liste ay: " + listeAy + " | Popup ay: " + popupAy + (ayni ? " -> Aynı" : " -> Aynı Değil"));
        return ayni;
    }

    /**
     * "islem dogrula" — saklanan islem adina gore dogru ekrana gidildigini dogrular.
     * Yanlis ekransa AssertionError; tanimsiz islem adinda kontrol atlanir.
     * (Eski koddaki switch fall-through duzeltildi.)
     */
    public static void iosIslemYonlendirmeDogrula(WebDriver driver, String islemAdi) {
        String beklenenBaslik = ISLEM_BASLIKLARI.get(islemAdi);
        if (beklenenBaslik == null) {
            System.out.println("Tanımsız işlem, kontrol atlandı: " + islemAdi);
            return;
        }
        if (!isDisplayed(driver, "(//XCUIElementTypeStaticText[@name='" + beklenenBaslik + "'])[1]")) {
            throw new AssertionError("Yanlış yönlendirme! '" + islemAdi + "' için beklenen başlık: " + beklenenBaslik);
        }
        System.out.println("Doğru Yönlendirme: " + beklenenBaslik);
    }

    /**
     * "I basarisizgiris X and Y" — ekrandaki son basarili / basarisiz giris tarihlerini okur,
     * Kullanici ayarlari > Guvenlik Ayarlari > Basarili/Basarisiz Girisler ekranindaki
     * tarihlerle karsilastirir. Eslesmezse AssertionError.
     * 18 karakterlik tarihlerin basina 0 eklenir (9:00 -> 09:00 farki).
     */
    public static void iosBasariliBasarisizGirisKontrol(WebDriver driver, String basariliXpath, String basarisizXpath) {
        String basarili = value(driver, basariliXpath);
        String basarisiz = value(driver, basarisizXpath);
        System.out.println("Başarılı giriş: " + basarili + " | Başarısız giriş: " + basarisiz);

        bekle(2000);
        click(driver, "(//XCUIElementTypeButton[@name='Kullanıcı ayarları'])[1]");
        bekle(1000);
        click(driver, "//XCUIElementTypeStaticText[@name='Güvenlik Ayarları']");
        bekle(1000);
        click(driver, "//XCUIElementTypeStaticText[@name='Başarılı/Başarısız Girişler']");
        bekle(2000);
        girisTarihiDogrula(driver, basarili, "Başarılı");

        bekle(2000);
        click(driver, "//XCUIElementTypeStaticText[@name='Başarısız Girişler']");
        bekle(2000);
        girisTarihiDogrula(driver, basarisiz, "Başarısız");
    }

    // ------------------------------------------------------------------
    // Popup / hata gecme
    // ------------------------------------------------------------------

    /**
     * "popup gec X" — verilen buton "Vazgeç" ise tiklar (e-posta dogrulama popup'ini gecer).
     * Buton yoksa sessizce gecer.
     *
     * @return tiklandiysa true
     */
    public static boolean iosPopupGec(WebDriver driver, String butonXpath) {
        List<WebElement> els = driver.findElements(By.xpath(butonXpath));
        if (els.isEmpty()) {
            return false;
        }
        String ad = els.get(0).getAttribute("name");
        System.out.println("Popup butonu: " + ad);
        if ("Vazgeç".equals(ad)) {
            els.get(0).click();
            return true;
        }
        return false;
    }

    /**
     * "Hata Gec X" — hata popup'i ("Tamam") cikarsa kapatir, geri doner ve verilen
     * elemana tekrar tiklar. Popup yoksa sessizce gecer.
     *
     * @return hata popup'i cikip gecildiyse true
     */
    public static boolean iosHataGec(WebDriver driver, String tekrarTiklanacakXpath) {
        String tamam = "//XCUIElementTypeStaticText[@name='Tamam']";
        if (!isDisplayed(driver, tamam)) {
            System.out.println("Hata Yok Devam Ke");
            return false;
        }
        click(driver, tamam);
        bekle(4000);
        click(driver, "//XCUIElementTypeButton[@name='back']");
        click(driver, tekrarTiklanacakXpath);
        return true;
    }

    // ------------------------------------------------------------------
    // Akislar
    // ------------------------------------------------------------------

    /**
     * "test X" — ilk kisayol "Hesaplar" degilse Acilis Ekrani Ayarlari > Kisayol Menuleri'nden
     * secili 3 kisayolu kaldirip ilk 3 secilmemis kisayolu secer, Uygula ile kaydeder.
     * (Eski kod String'i == ile karsilastirdigi icin her seferinde sifirliyordu; equals yapildi.)
     */
    public static void iosKisayolMenuSifirla(WebDriver driver, String ilkKisayolXpath) {
        List<WebElement> ilk = driver.findElements(By.xpath(ilkKisayolXpath));
        if (!ilk.isEmpty() && "Hesaplar".equals(ilk.get(0).getAttribute("value"))) {
            System.out.println("Kısayollar zaten doğru, işlem yapılmadı.");
            return;
        }
        bekle(3000);
        scroll(driver, "down");
        scroll(driver, "down");
        bekle(3000);
        click(driver, "//XCUIElementTypeButton[@name='Açılış Ekranı Ayarları']");
        bekle(3000);
        click(driver, "//XCUIElementTypeStaticText[@name='Kısayol Menüleri']");
        bekle(3000);

        String tikli = "(//XCUIElementTypeButton[@name='selectionChecked'])[1]";
        for (int i = 0; i < 3; i++) {
            if (isDisplayed(driver, tikli)) {
                click(driver, tikli);
            } else {
                scroll(driver, "down");
                bekle(1000);
                click(driver, tikli);
                scroll(driver, "up");
            }
        }
        String tiksiz = "(//XCUIElementTypeButton[@name='circleUnCheck'])[1]";
        for (int i = 0; i < 3; i++) {
            click(driver, tiksiz);
            bekle(1300);
        }
        click(driver, "//XCUIElementTypeButton[@name='Uygula']");
        bekle(3000);
        click(driver, "//XCUIElementTypeButton[@name='back']");
    }

    // ------------------------------------------------------------------
    // Driver gerektirmeyen yardimci adimlar
    // ------------------------------------------------------------------

    /**
     * "SetUp" — test verisi hazirlamak icin SQL calistiran API'ye POST atar.
     * Body: {"query": "...", "databaseType": "..."}
     *
     * @return API yanit govdesi (HTTP 200 degilse de dondurulur, kod loglanir)
     */
    public static String iosSqlApiCalistir(String apiUrl, String query, String databaseType) throws IOException {
        HttpURLConnection con = (HttpURLConnection) new URL(apiUrl).openConnection();
        con.setRequestMethod("POST");
        con.setRequestProperty("Content-Type", "application/json");
        con.setDoOutput(true);
        String body = "{\"query\": \"" + jsonEscape(query) + "\", \"databaseType\": \"" + jsonEscape(databaseType) + "\"}";
        try (OutputStream os = con.getOutputStream()) {
            os.write(body.getBytes(StandardCharsets.UTF_8));
        }
        int kod = con.getResponseCode();
        InputStream is = kod < 400 ? con.getInputStream() : con.getErrorStream();
        String yanit = is == null ? "" : new String(is.readAllBytes(), StandardCharsets.UTF_8);
        System.out.println("API yanıt kodu: " + kod + " | yanıt: " + yanit);
        return yanit;
    }

    /** "I see oto X" — dosyaya '"X" geldiği görülür' satiri ekler (senaryo taslagi uretmek icin). */
    public static void iosOtoGorulurYaz(String dosyaYolu, String hedef) throws IOException {
        satirEkle(dosyaYolu, "\"" + hedef + "\" geldiği görülür");
    }

    /** "I clickoto X" — dosyaya '"X" Tıklanır' satiri ekler (senaryo taslagi uretmek icin). */
    public static void iosOtoTiklanirYaz(String dosyaYolu, String hedef) throws IOException {
        satirEkle(dosyaYolu, "\"" + hedef + "\" Tıklanır");
    }

    // ------------------------------------------------------------------
    // Yardimcilar
    // ------------------------------------------------------------------

    private static By resolveDeleteKeyLocator(WebDriver driver) {
        try {
            driver.findElement(DELETE_KEY_TR);
            return DELETE_KEY_TR;
        } catch (NoSuchElementException e) {
            return DELETE_KEY_EN;
        }
    }

    private static String value(WebDriver driver, String xpath) {
        return driver.findElement(By.xpath(xpath)).getAttribute("value");
    }

    private static void click(WebDriver driver, String xpath) {
        driver.findElement(By.xpath(xpath)).click();
    }

    private static boolean isDisplayed(WebDriver driver, String xpath) {
        List<WebElement> els = driver.findElements(By.xpath(xpath));
        return !els.isEmpty() && els.get(0).isDisplayed();
    }

    private static boolean clickFirstVisible(WebDriver driver, List<By> locators) {
        for (By locator : locators) {
            List<WebElement> els = driver.findElements(locator);
            if (!els.isEmpty() && els.get(0).isDisplayed()) {
                els.get(0).click();
                System.out.println("Tıklanan buton: " + locator);
                return true;
            }
        }
        System.out.println("Hiçbir buton bulunamadı.");
        return false;
    }

    /** Hesap listesini (5, 9, 13 ... 200) gezip kosulu saglayan ilk elemana tiklar; liste bitince null. */
    private static String listedeIlkUygunaTikla(WebDriver driver, String baseXpath, Predicate<String> kosul) {
        for (int say = HESAP_ILK_INDEX; say <= HESAP_SON_INDEX; say += HESAP_ADIM) {
            List<WebElement> els = driver.findElements(By.xpath(baseXpath + "[" + say + "]"));
            if (els.isEmpty()) {
                break;
            }
            String deger = els.get(0).getAttribute("value");
            System.out.println("Gelen Baslik: " + deger);
            if (deger != null && kosul.test(deger)) {
                els.get(0).click();
                System.out.println("Seçilen Hesap " + deger);
                return deger;
            }
        }
        System.out.println("Liste Koşulu Sağlanmadı, uygun hesap yok.");
        return null;
    }

    private static void girisTarihiDogrula(WebDriver driver, String beklenen, String tur) {
        String ekrandaki = value(driver, "(//XCUIElementTypeStaticText[@enabled='true'])[5]");
        String normal = beklenen != null && beklenen.length() == 18 ? "0" + beklenen : beklenen;
        if (normal == null || !normal.equals(ekrandaki)) {
            throw new AssertionError(tur + " giriş tarihi eşleşmedi. Beklenen = [" + normal + "], ekrandaki = [" + ekrandaki + "]");
        }
        System.out.println(tur + " giriş doğrulaması OK: " + ekrandaki);
    }

    private static void scroll(WebDriver driver, String yon) {
        Map<String, Object> args = new HashMap<>();
        args.put("direction", yon);
        ((JavascriptExecutor) driver).executeScript("mobile: scroll", args);
    }

    private static void bekle(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static void satirEkle(String dosyaYolu, String satir) throws IOException {
        Files.write(Paths.get(dosyaYolu), (satir + System.lineSeparator()).getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        System.out.println("Dosyaya yazıldı: " + satir);
    }

    private static String jsonEscape(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
    }

    /** "0,00" veya "11.111,00" iceren degerler (eski kosulun fiilen yaptigi filtre). */
    private static boolean isExcludedAmount(String text) {
        return text.contains("0,00") || text.contains("11.111,00");
    }

    /** Eski getValue3: count 0..10 icin count + (5, 8, 13, ... 53), aralik disinda count. */
    private static int getValue3(int count) {
        if (count >= 0 && count < VALUE3_OFFSETS.length) {
            return count + VALUE3_OFFSETS[count];
        }
        return count;
    }
}
