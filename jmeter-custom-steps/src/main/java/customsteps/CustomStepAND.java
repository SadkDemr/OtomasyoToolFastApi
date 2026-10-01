package customsteps;

import org.openqa.selenium.By;
import org.openqa.selenium.NoSuchElementException;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * ANDROID — JMeter JSR223 Sampler'lardan cagrilacak custom adimlar (MySteps.java'dan tasindi).
 * WebDriver arayuzu kullanilir (AppiumDriver da bu arayuzu implement eder),
 * boylece io.appium.java_client'a derleme zamaninda bagimlilik gerekmez.
 * Yeni method eklerken imza kuralini koru: ilk parametre WebDriver,
 * geri kalani adimin ihtiyac duydugu deger(ler).
 *
 * MySteps'ten farklar:
 *  - device.findSelector(key) sozluk anahtari yerine dogrudan xpath string'i alinir
 *    (eski xa.substring(9) "By.xpath: " onekini kesiyordu, artik gerek yok).
 *  - Sinif icinde state tutulmaz (KeepResult, variables map). Deger ureten metodlar
 *    String/List dondurur, JMeter tarafinda vars.put(...) ile saklanir.
 *
 * Kullanim (JSR223 - Groovy):
 *   import customsteps.CustomStepAND;
 *   CustomStepAND.andPopupKapat(driver);
 */
public final class CustomStepAND {

    private static final String PKG = "com.vakifkatilim.mobil.test:id/";

    private static final List<By> POPUP_BUTTONS = Arrays.asList(
            By.xpath("//android.widget.FrameLayout[@index='0']/android.widget.LinearLayout[@index='0']/android.widget.FrameLayout[@index='0']/android.widget.FrameLayout[@index='0']/android.widget.LinearLayout[@index='0']/android.view.ViewGroup[@resource-id='" + PKG + "close_button_constraint_layout']"),
            By.xpath("//*[@text='Anladım']"),
            By.xpath("//*[@text='Daha Sonra Hatırlat']"),
            By.xpath("//*[@resource-id='" + PKG + "btnNegative' and @text='Daha Sonra Hatırlat']"),
            By.xpath("//*[@resource-id='dataroid-close-button']"),
            By.xpath("//*[@resource-id='" + PKG + "btnNextnegative']"),
            By.xpath("//*[@text='İlgilenmiyorum']"),
            By.xpath("//*[@resource-id='" + PKG + "btnNext']"),
            By.xpath("//*[@resource-id='" + PKG + "btnOk']"),
            By.xpath("//*[@resource-id='" + PKG + "btnPositive']"),
            By.xpath("//hierarchy[@index='0']/android.widget.FrameLayout[@index='0']/android.widget.FrameLayout[@index='0']/android.widget.LinearLayout[@index='0']/android.widget.FrameLayout[@index='0']/android.widget.FrameLayout[@index='0']/android.widget.LinearLayout[@index='0']/android.view.ViewGroup[@resource-id='" + PKG + "close_button_constraint_layout']")
    );

    private static final List<By> CONFIRM_BUTTONS = Arrays.asList(
            By.xpath("//*[@resource-id='" + PKG + "btnNext']"),
            By.xpath("//*[@resource-id='" + PKG + "btnOk']"),
            By.xpath("//*[@resource-id='" + PKG + "btnPositive']")
    );

    /** Kisa ay adi (liste) -> ay numarasi (popup tarihi). "Mys"/"Agu" eski kodda boyleydi, varyantlar da eklendi. */
    private static final Map<String, String> AYLAR = new HashMap<>();

    /** andIslemYonlendirmeDogrula: saklanan islem adi -> yonlenilmesi gereken ekran basligi. */
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
        ISLEM_BASLIKLARI.put("HESABA HAVALE", "EFT/Havale/FAST");
    }

    private CustomStepAND() {
    }

    // ------------------------------------------------------------------
    // Klavye / input
    // ------------------------------------------------------------------

    /** "I am sil with X" — elementin icerigini temizler. */
    public static void andAlanTemizle(WebDriver driver, String xpath) {
        WebElement element = driver.findElement(By.xpath(xpath));
        System.out.println("silmek istenen nesne: " + element.getAttribute("text"));
        element.clear();
    }

    /**
     * Input'a 100 karakter yazip onay butonuna basar, alanda kalan metnin
     * uzunlugu expectedLength degilse AssertionError firlatir.
     */
    public static void andMaxKarakterDogrula(WebDriver driver, String xpath, int expectedLength) {
        WebElement inputField = driver.findElement(By.xpath(xpath));
        inputField.sendKeys(String.join("", Collections.nCopies(100, "1")));

        clickFirstVisible(driver, CONFIRM_BUTTONS);

        int actualLength = inputField.getText().length();
        if (actualLength != expectedLength) {
            throw new AssertionError("Beklenen Uzunluk: " + expectedLength + " gelen uzunluk: " + actualLength);
        }
        System.out.println("Uzunluklar eşit: " + actualLength);
    }

    // ------------------------------------------------------------------
    // Deger saklama / karsilastirma (JMeter tarafinda vars ile saklanir)
    // ------------------------------------------------------------------

    /** "keep variable X" — elementin text attribute'unu dondurur. */
    public static String andDegerTut(WebDriver driver, String xpath) {
        String keep = driver.findElement(By.xpath(xpath)).getAttribute("text");
        System.out.println("Tutulan Deger: " + keep);
        return keep;
    }

    /** "I save X text as Y" — elementin getText() degerini dondurur. */
    public static String andMetinKaydet(WebDriver driver, String xpath) {
        String text = driver.findElement(By.xpath(xpath)).getText();
        System.out.println("Saved text: " + text);
        return text;
    }

    /** "I compare X to Y" — elementin metni savedText'e esit degilse AssertionError. */
    public static void andMetinKarsilastir(WebDriver driver, String xpath, String savedText) {
        String currentText = driver.findElement(By.xpath(xpath)).getText();
        if (savedText == null || !savedText.equals(currentText)) {
            throw new AssertionError("Textler eşleşmiyor! Saklanan = [" + savedText
                    + "], XPath text = [" + currentText + "]");
        }
        System.out.println("Compared: " + savedText + " == " + currentText);
    }

    // ------------------------------------------------------------------
    // Liste / hesap secimi
    // ------------------------------------------------------------------

    /**
     * "arraylistesi X" — baseXpath (indexsiz) + [getValue3(1..7)] elemanlarinin
     * text'lerini toplar; "0,00" ve "11.111,00" iceren degerler alinmaz.
     * Ilk bulunamayan elemanda durur (eski koddaki try/catch davranisi).
     */
    public static List<String> andListeDegerleriniAl(WebDriver driver, String baseXpath) {
        List<String> result = new ArrayList<>();
        try {
            for (int say = 1; say <= 7; say++) {
                String baslik = driver.findElement(By.xpath(baseXpath + "[" + getValue3(say) + "]")).getAttribute("text");
                System.out.println("Gelen Baslik: " + baslik);
                if (!isExcludedAmount(baslik)) {
                    result.add(baslik);
                    System.out.println("Listeye Eklendi " + baslik);
                } else {
                    System.out.println("Liste Koşulu Sağlanmadı: " + baslik);
                }
            }
        } catch (NoSuchElementException e) {
            System.out.println("Liste sonu, nesne kalmadı.");
        }
        System.out.println("Arraydeki listeler: " + result);
        return result;
    }

    /**
     * "I hesapbul X Y" / "I hesapbul2 X Y" — baseXpath[1,3,5,7,9] arasinda hesapTuru'nu
     * iceren, bakiyesi "0,00"/"11.111,00" olmayan ilk hesaba tiklar.
     * Eski kodda for'un say++'ina ek olarak govdede de say++ vardi, yani tek indexler
     * geziliyordu; davranis korundu. Iki metodun filtresi fiilen ayniydi, birlestirildi.
     *
     * @return secilen hesabin text'i, bulunamazsa null
     */
    public static String andHesapSec(WebDriver driver, String baseXpath, String hesapTuru) {
        try {
            for (int say = 1; say <= 10; say += 2) {
                By locator = By.xpath(baseXpath + "[" + say + "]");
                String baslik = driver.findElement(locator).getAttribute("text");
                System.out.println("Gelen Baslik: " + baslik);
                if (baslik.contains(hesapTuru) && !isExcludedAmount(baslik)) {
                    driver.findElement(locator).click();
                    String secilen = driver.findElement(locator).getAttribute("text");
                    System.out.println("Seçilen Hesap " + secilen);
                    return secilen;
                }
                System.out.println("Liste Koşulu Sağlanmadı");
            }
        } catch (NoSuchElementException e) {
            System.out.println("Liste sonu, nesne kalmadı.");
        }
        System.out.println("Uygun hesap bulunamadı: " + hesapTuru);
        return null;
    }

    /**
     * "I checkavailablelimit X Y" — baseXpath[1..10] icinde hesapTuru'nu iceren
     * ilk elemana tiklar. Bulunamayan index atlanir, aramaya devam edilir.
     *
     * @return secilen elemanin text'i, bulunamazsa null
     */
    public static String andLimitSec(WebDriver driver, String baseXpath, String hesapTuru) {
        for (int say = 1; say <= 10; say++) {
            By locator = By.xpath(baseXpath + "[" + say + "]");
            try {
                String baslik = driver.findElement(locator).getAttribute("text");
                System.out.println("Gelen Baslik: " + baslik);
                if (baslik.contains(hesapTuru)) {
                    driver.findElement(locator).click();
                    String secilen = driver.findElement(locator).getAttribute("text");
                    System.out.println("Seçilen Hesap " + secilen);
                    return secilen;
                }
                System.out.println("Liste Koşulu Sağlanmadı");
            } catch (NoSuchElementException e) {
                System.out.println(baseXpath + "[" + say + "] xpath bulunamadı.");
            }
        }
        return null;
    }

    /**
     * "I son10transfer" — Son 10 Transfer listesindeki basliklari (index 2..10)
     * okur, ilk bulunamayan elemanda durur.
     */
    public static List<String> andSon10TransferListele(WebDriver driver) {
        String baseXpath = "(//*[@resource-id='" + PKG + "tvTitle' and @index='0'])";
        List<String> basliklar = new ArrayList<>();
        try {
            for (int count = 2; count <= 10; count++) {
                String baslik = driver.findElement(By.xpath(baseXpath + "[" + count + "]")).getAttribute("text");
                System.out.println("Gelen Baslik: " + baslik);
                basliklar.add(baslik);
            }
        } catch (NoSuchElementException e) {
            System.out.println("Nesne Kalmadı!");
        }
        System.out.println("Gelen Değer Sayısı: " + basliklar.size());
        return basliklar;
    }

    // ------------------------------------------------------------------
    // Dogrulamalar
    // ------------------------------------------------------------------

    /**
     * "son10transfer tarih kontrol X and Y" — listedeki kisa ay adi (Oca, Şub...)
     * ile popupdaki tarihin (gg.aa.yyyy) ay kismini karsilastirir.
     *
     * @return aylar ayni ise true. Eski kod gibi hata firlatmaz; JMeter'da sonuca gore assert edin.
     */
    public static boolean andSon10TransferTarihKontrol(WebDriver driver, String listeTarihXpath, String popupTarihXpath) {
        String listeAy = driver.findElement(By.xpath(listeTarihXpath)).getAttribute("text");
        String popupTarih = driver.findElement(By.xpath(popupTarihXpath)).getAttribute("text");
        String popupAy = popupTarih.replaceAll("\\.", "").substring(2, 4);
        System.out.println("Liste ay: " + listeAy + " | Popup ay: " + popupAy);

        boolean ayni = popupAy.equals(AYLAR.get(listeAy));
        System.out.println(ayni
                ? "Listedeki değerle Popupdaki Tarih Değeri Aynı"
                : "Listedeki değerle Popupdaki Tarih Değeri Aynı Değil");
        return ayni;
    }

    /**
     * "islem dogrula" — keepResult (onceden andDegerTut ile saklanan islem adi)
     * icin dogru ekrana yonlenildigini kontrol eder, yanlissa AssertionError.
     * Eski koddaki xpath'lerde '' (cift tek tirnak) hatasi ve switch fall-through vardi, duzeltildi.
     */
    public static void andIslemYonlendirmeDogrula(WebDriver driver, String keepResult) {
        String beklenenBaslik = ISLEM_BASLIKLARI.get(keepResult);
        if (beklenenBaslik == null) {
            System.out.println("andIslemYonlendirmeDogrula: tanımsız işlem, kontrol atlandı: " + keepResult);
            return;
        }
        By baslik = By.xpath("//*[@resource-id='" + PKG + "tvTitle' and @text='" + beklenenBaslik + "']");
        List<WebElement> elements = driver.findElements(baslik);
        if (elements.isEmpty() || !elements.get(0).isDisplayed()) {
            throw new AssertionError("Yanlış yönlendirme! '" + keepResult + "' için beklenen başlık: " + beklenenBaslik);
        }
        System.out.println("Doğru Yönlendirme: " + beklenenBaslik);
    }

    // ------------------------------------------------------------------
    // Popup / izin / banner kapatma (bulunamazsa sessizce gecer)
    // ------------------------------------------------------------------

    /** "popupkontrolleri" — bilinen popup butonlarindan gorunen ilkine tiklar. */
    public static boolean andPopupKapat(WebDriver driver) {
        return clickFirstVisible(driver, POPUP_BUTTONS);
    }

    /** "I bannerkapat" — banner kapat butonuna 4 kez kadar tiklar. */
    public static void andBannerKapat(WebDriver driver) {
        By close = By.xpath("//*[@resource-id='" + PKG + "ivClose']");
        for (int i = 0; i < 4; i++) {
            try {
                driver.findElement(close).click();
                System.out.println("banner kapat tıklandı.");
            } catch (Exception e) {
                System.out.println("banner yok");
            }
        }
    }

    /** "I andIzinVer" — Android izin popup'inda "Izin ver"e basar. */
    public static void andIzinVer(WebDriver driver) {
        try {
            driver.findElement(By.xpath("//*[@resource-id='com.android.permissioncontroller:id/permission_allow_button']")).click();
        } catch (Exception ignored) {
            // izin popup'i yoksa devam
        }
    }

    /** "I sozlesmekontrol" — sozlesme popup'inda "Daha Sonra Hatirlat"a basar. */
    public static void andSozlesmeGec(WebDriver driver) {
        try {
            driver.findElement(By.xpath("//*[@resource-id='" + PKG + "btnNegative' and @text='Daha Sonra Hatırlat']")).click();
            System.out.println("Sözleşme geçti.");
        } catch (Exception e) {
            System.out.println("sözlesme gelmedi.");
        }
    }

    // ------------------------------------------------------------------
    // Akis
    // ------------------------------------------------------------------

    /**
     * "I andKendiIbanYaz" (Android) — musterinin kendi IBAN'ini hesap
     * detayindan okuyup havale ekranindaki alici IBAN alanina yazar.
     * Eski koddaki Thread.sleep(7)/sleep(5) milisaniye oldugu icin etkisizdi, kaldirildi.
     *
     * @return okunan IBAN
     */
    public static String andKendiIbanYaz(WebDriver driver) {
        String root = "/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.view.ViewGroup/android.view.ViewGroup/android.widget.FrameLayout[1]/android.widget.RelativeLayout/android.widget.FrameLayout[2]";

        click(driver, root + "/android.view.ViewGroup/android.widget.FrameLayout[2]/android.widget.HorizontalScrollView/android.widget.LinearLayout/android.widget.LinearLayout[2]");
        click(driver, root + "/android.view.ViewGroup/android.widget.FrameLayout[1]/android.view.ViewGroup/android.widget.ScrollView/android.widget.LinearLayout/android.widget.FrameLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[1]/android.widget.TextView");
        click(driver, root + "/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.ScrollView/android.widget.LinearLayout/androidx.recyclerview.widget.RecyclerView/android.widget.FrameLayout[1]/android.widget.FrameLayout/android.view.ViewGroup");

        String iban = driver.findElement(By.xpath(root + "/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.ScrollView/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.TextView")).getAttribute("text");
        System.out.println("Okunan IBAN: " + iban);

        click(driver, "//android.widget.ImageButton[@content-desc='Yukarı git']");
        click(driver, "//android.widget.ImageButton[@content-desc='Yukarı git']");
        click(driver, root + "/android.view.ViewGroup/android.widget.FrameLayout[2]/android.widget.HorizontalScrollView/android.widget.LinearLayout/android.widget.LinearLayout[3]/android.widget.LinearLayout");
        click(driver, root + "/android.view.ViewGroup/android.widget.FrameLayout[1]/android.view.ViewGroup/android.widget.ScrollView/android.widget.LinearLayout/android.widget.FrameLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[1]/android.widget.TextView");
        click(driver, root + "/android.view.ViewGroup/android.widget.ScrollView/android.widget.LinearLayout/android.widget.FrameLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[3]/android.widget.TextView");

        driver.findElement(By.xpath("(//*[@resource-id='" + PKG + "etReceiverIBAN'])[1]")).sendKeys(iban);
        click(driver, "(//*[@resource-id='" + PKG + "etReceiverName' and @text='Giriniz'])[1]");
        return iban;
    }

    // ------------------------------------------------------------------
    // Yardimcilar
    // ------------------------------------------------------------------

    private static void click(WebDriver driver, String xpath) {
        driver.findElement(By.xpath(xpath)).click();
    }

    private static boolean clickFirstVisible(WebDriver driver, List<By> locators) {
        for (By locator : locators) {
            List<WebElement> elements = driver.findElements(locator);
            if (!elements.isEmpty() && elements.get(0).isDisplayed()) {
                elements.get(0).click();
                System.out.println("Tıklanan buton: " + locator);
                return true;
            }
        }
        System.out.println("Hiçbir buton bulunamadı.");
        return false;
    }

    /**
     * Eski kosulun operator onceligi nedeniyle fiilen yaptigi filtre:
     * "0,00" veya "11.111,00" iceren degerler disarida. ("Merkez Şube"/"Cari Hesap"
     * kontrolu yazilmis ama hicbir zaman etkili olmuyordu.)
     */
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
