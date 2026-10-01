package customsteps;

import org.openqa.selenium.By;
import org.openqa.selenium.Dimension;
import org.openqa.selenium.NoSuchElementException;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.interactions.Interactive;
import org.openqa.selenium.interactions.PointerInput;
import org.openqa.selenium.interactions.Sequence;

import java.time.Duration;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * ANDROID KARTLAR — JMeter JSR223 Sampler'lardan cagrilacak kart/dashboard adimlari
 * (Kartlar projesinin MySteps.java'sindan tasindi).
 * Imza kurali: public static, ilk parametre WebDriver (AndroidDriver bu arayuzu
 * implement eder), geri kalani adimin ihtiyac duydugu deger(ler).
 *
 * CustomStepAND ile birebir ayni olan adimlar (deger tut, alan temizle, izin ver,
 * sozlesme gec, metin kaydet/karsilastir) oraya yonlendirilir; davranisi farkli olanlar
 * (popup listesi, banner sayisi, max uzunluk) burada ayrica yazildi.
 *
 * Kullanim (JSR223 - Groovy):
 *   import customsteps.CustomStepANDKartlar;
 *   CustomStepANDKartlar.andPopupKapat(driver);
 */
public final class CustomStepANDKartlar {

    private static final String PKG = "com.vakifkatilim.mobil.test:id/";
    private static final String YUKARI_GIT = "//android.widget.ImageButton[@content-desc='Yukarı git']";

    private static final List<By> POPUP_BUTTONS = Arrays.asList(
            By.xpath("//*[@resource-id='" + PKG + "btnNegative' and @text='Daha Sonra Hatırlat']"),
            By.xpath("//*[@resource-id='dataroid-close-button']"),
            By.xpath("//*[@resource-id='" + PKG + "btnNextnegative']"),
            By.xpath("//*[@text='İlgilenmiyorum']"),
            By.xpath("//*[@resource-id='" + PKG + "btnNext']"),
            By.xpath("//*[@resource-id='" + PKG + "btnOk']"),
            By.xpath("//*[@resource-id='" + PKG + "btnPositive']"),
            By.xpath("//*[@text='Anladım']"),
            By.xpath("//*[@text='Tamam']")
    );

    /** popupkontrolleri2: ilk uygunda durmaz, sirayla hepsini dener. */
    private static final List<By> POPUP_BUTTONS_SIRALI = Arrays.asList(
            By.xpath("//*[@resource-id='" + PKG + "btnNegative' and @text='Daha Sonra Hatırlat']"),
            By.xpath("//*[@resource-id='dataroid-close-button']"),
            By.xpath("//*[@resource-id='" + PKG + "btnNextnegative']"),
            By.xpath("//*[@text='İlgilenmiyorum']"),
            By.xpath("//*[@resource-id='" + PKG + "btnNext']"),
            By.xpath("//*[@resource-id='" + PKG + "btnOk']")
    );

    private static final List<String> HEDEF_KISAYOLLAR = Arrays.asList("Hesaplar", "Kartlar", "Finansman");

    private CustomStepANDKartlar() {
    }

    // ------------------------------------------------------------------
    // CustomStepAND ile ayni olan adimlar (oraya yonlendirilir)
    // ------------------------------------------------------------------

    /** "keep variable X" — elementin text'ini dondurur. */
    public static String andDegerTut(WebDriver driver, String xpath) {
        return CustomStepAND.andDegerTut(driver, xpath);
    }

    /** "I am sil with X" — elementin icerigini temizler. */
    public static void andAlanTemizle(WebDriver driver, String xpath) {
        CustomStepAND.andAlanTemizle(driver, xpath);
    }

    /** "I izinVerKontrol" — Android izin popup'inda "Izin ver"e basar, yoksa gecer. */
    public static void andIzinVer(WebDriver driver) {
        CustomStepAND.andIzinVer(driver);
    }

    /** "I sozlesmekontrol" — sozlesme popup'inda "Daha Sonra Hatirlat"a basar, yoksa gecer. */
    public static void andSozlesmeGec(WebDriver driver) {
        CustomStepAND.andSozlesmeGec(driver);
    }

    /** "I save X text as Y" — elementin getText() degerini dondurur. */
    public static String andMetinKaydet(WebDriver driver, String xpath) {
        return CustomStepAND.andMetinKaydet(driver, xpath);
    }

    /** "I compare X to Y" — metin saklanan degere esit degilse AssertionError. */
    public static void andMetinKarsilastir(WebDriver driver, String xpath, String saklananDeger) {
        CustomStepAND.andMetinKarsilastir(driver, xpath, saklananDeger);
    }

    // ------------------------------------------------------------------
    // Navigasyon / popup / banner
    // ------------------------------------------------------------------

    /** "gerigel" — ust bardaki "Yukari git" (geri) butonuna basar; buton yoksa sessizce gecer. */
    public static void andGeriGel(WebDriver driver) {
        try {
            click(driver, YUKARI_GIT);
        } catch (NoSuchElementException ignored) {
            // geri butonu yoksa devam
        }
    }

    /**
     * "popupkontrolleri" — bilinen popup butonlarindan (Daha Sonra Hatirlat, Ilgilenmiyorum,
     * Tamam, Anladim, Ileri ...) gorunen ilkine tiklar. Hicbiri yoksa sessizce gecer.
     *
     * @return bir butona tiklandiysa true
     */
    public static boolean andPopupKapat(WebDriver driver) {
        for (By locator : POPUP_BUTTONS) {
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

    /**
     * "popupkontrolleri2" — popup butonlarini sirayla dener ve bulunan HER birine tiklar
     * (andPopupKapat ilk bulunanda durur, bu durmaz).
     *
     * @return tiklanan buton sayisi
     */
    public static int andTumPopuplariKapat(WebDriver driver) {
        int sayac = 0;
        for (By locator : POPUP_BUTTONS_SIRALI) {
            List<WebElement> els = driver.findElements(locator);
            if (!els.isEmpty()) {
                els.get(0).click();
                System.out.println("Tıklanan buton: " + locator);
                sayac++;
            }
        }
        return sayac;
    }

    /** "I loginpopupkontrol" — login sonrasi cikan popup'taki ilk butona basar; popup yoksa gecer. */
    public static void andLoginPopupGec(WebDriver driver) {
        List<WebElement> butonlar = driver.findElements(By.xpath("//*[@class='android.widget.Button']"));
        if (butonlar.isEmpty()) {
            System.out.println("Pop-up yok.");
            return;
        }
        butonlar.get(0).click();
        System.out.println("pop-up geçti.");
    }

    /** "I bannerkapat" — banner kapat butonuna 6 kez kadar tiklar (Kartlar'da 6, AND'de 4). */
    public static void andBannerKapat(WebDriver driver) {
        By close = By.xpath("//*[@resource-id='" + PKG + "ivClose']");
        for (int i = 0; i < 6; i++) {
            try {
                driver.findElement(close).click();
                System.out.println("banner kapat tıklandı.");
            } catch (NoSuchElementException e) {
                System.out.println("banner yok");
            }
        }
    }

    // ------------------------------------------------------------------
    // Input
    // ------------------------------------------------------------------

    /**
     * "I verifyInputMaxLength X N" — alana 30 kez "1" yazar, alandaki metnin uzunlugu
     * beklenenden farkliysa AssertionError. (AND'deki versiyondan farki: 30 karakter, onay butonu yok.)
     */
    public static void andMaxKarakterDogrula(WebDriver driver, String xpath, int beklenenUzunluk) {
        WebElement input = driver.findElement(By.xpath(xpath));
        input.sendKeys(String.join("", Collections.nCopies(30, "1")));
        int gelen = input.getText().length();
        if (gelen != beklenenUzunluk) {
            throw new AssertionError("Beklenen Uzunluk: " + beklenenUzunluk + " gelen uzunluk: " + gelen);
        }
        System.out.println("Uzunluklar eşit: " + gelen);
    }

    // ------------------------------------------------------------------
    // Favori (dashboard) kontrolleri — kendileri fail etmez, boolean doner
    // ------------------------------------------------------------------

    /**
     * "I favori hesap X kontrol et Y" — listedeki 1. hesabi favori yapip dashboard'da
     * gorundugunu, sonra Ayarlar > Favori Hesabim'dan 2. hesabi secip yine dashboard'da
     * gorundugunu kontrol eder. Hesap metinlerinin bosluklari silinerek karsilastirilir.
     *
     * @return iki kontrol de tuttuysa true
     */
    public static boolean andFavoriHesapKontrol(WebDriver driver, String hesapListesiXpath, String dashboardXpath) {
        // 1) listedeki ilk hesap
        bekle(3000);
        String hesap1 = bosluksuz(text(driver, hesapListesiXpath + "[1]"));
        click(driver, hesapListesiXpath + "[1]");
        andGeriGel(driver);
        kaydir(driver, "down");
        kaydir(driver, "down");
        bekle(5000);
        boolean ilk = text(driver, dashboardXpath).contains(hesap1);
        System.out.println("Favori hesap 1 [" + hesap1 + "] dashboard'da: " + ilk);

        // 2) Ayarlar > Favori Hesabim > ikinci hesap
        kaydir(driver, "down");
        kaydir(driver, "down");
        kaydir(driver, "down");
        bekle(4000);
        click(driver, "(//*[@resource-id='" + PKG + "tvSettings'])");
        bekle(2000);
        click(driver, "//*[@resource-id='" + PKG + "tvTitle' and @text='Favori Hesabım']");
        bekle(2000);
        String hesap2 = bosluksuz(text(driver, hesapListesiXpath + "[2]"));
        click(driver, hesapListesiXpath + "[2]");
        andGeriGel(driver);
        bekle(3000);
        boolean ikinci = hesap2.contains(text(driver, dashboardXpath));
        System.out.println("Favori hesap 2 [" + hesap2 + "] dashboard'da: " + ikinci);
        return ilk && ikinci;
    }

    /**
     * "I favori kredikart X kontrol et Y" — kart metninin ilk 8 karakterinden (kart adi)
     * sonraki kismini (kart no) alir, geri donup yukari kaydirir ve dashboard'daki kart
     * metninin bu numarayi icerdigini kontrol eder.
     *
     * @return dashboard kart numarasini iceriyorsa true
     */
    public static boolean andFavoriKrediKartKontrol(WebDriver driver, String kartXpath, String dashboardXpath) {
        String kartNo = text(driver, kartXpath).substring(8);
        System.out.println("Kart no: " + kartNo);
        andGeriGel(driver);
        kaydir(driver, "up");
        bekle(5000);
        boolean sonuc = text(driver, dashboardXpath).contains(kartNo);
        System.out.println("Favori kart dashboard'da: " + sonuc);
        return sonuc;
    }

    /**
     * "I favori finans X kontrol et Y" — listedeki 3. finansmani favori yapip dashboard'da
     * (veya ilk/ucuncu baslikta) gorundugunu, sonra Ayarlar > Favori Finansmanim'dan
     * 4. finansmani secip Ana Sayfa'da gorundugunu kontrol eder.
     * Finansman adi metindeki "-" isaretinden sonraki kisimdan alinir.
     *
     * @return iki kontrol de tuttuysa true
     */
    public static boolean andFavoriFinansmanKontrol(WebDriver driver, String finansmanListesiXpath, String dashboardXpath) {
        // 1) listedeki 3. finansman
        bekle(3000);
        String finans1 = finansmanAdi(text(driver, finansmanListesiXpath + "[3]"));
        click(driver, finansmanListesiXpath + "[3]");
        andGeriGel(driver);
        andGeriGel(driver);
        bekle(5000);
        kaydir(driver, "up");
        bekle(3000);
        String dashboard = text(driver, dashboardXpath);
        String ust = text(driver, "(//*[@resource-id='" + PKG + "tvTitle'])[1]");
        String alt = text(driver, "(//*[@resource-id='" + PKG + "tvTitle'])[3]");
        boolean ilk = finans1.equals(dashboard) || finans1.equals(ust) || finans1.equals(alt);
        System.out.println("Favori finansman 1 [" + finans1 + "] dashboard'da: " + ilk);

        // 2) Ayarlar > Favori Finansmanim > 4. finansman
        kaydir(driver, "down");
        kaydir(driver, "down");
        kaydir(driver, "down");
        bekle(4000);
        click(driver, "(//*[@resource-id='" + PKG + "tvSettings'])");
        bekle(5000);
        click(driver, "//*[@resource-id='" + PKG + "tvTitle' and @text='Favori Finansmanım']");
        bekle(2000);
        String finans2 = finansmanAdi(text(driver, finansmanListesiXpath + "[4]"));
        click(driver, finansmanListesiXpath + "[4]");
        andGeriGel(driver);
        bekle(3000);
        click(driver, YUKARI_GIT);
        bekle(2000);
        click(driver, "(//*[@resource-id='" + PKG + "tvTitle' and @text='Ana Sayfa'])");
        bekle(5000);
        boolean ikinci = finans2.equals(text(driver, dashboardXpath));
        System.out.println("Favori finansman 2 [" + finans2 + "] dashboard'da: " + ikinci);
        return ilk && ikinci;
    }

    // ------------------------------------------------------------------
    // Kart ekrani kontrolleri
    // ------------------------------------------------------------------

    /**
     * "gizli kart kontrol X same value Y" — kart detayindaki maskeli kart numarasini
     * (ilk 7 karakterden sonrasi) alir, geri donup yukari kaydirir; dashboard'daki kart
     * metni bu numarada yoksa AssertionError.
     * (Eski koddaki iOS xpath'li ust/alt alternatifleri Android'de hic bulunamayacagi icin cikarildi.)
     */
    public static void andGizliKartKontrol(WebDriver driver, String kartNoXpath, String dashboardKartXpath) {
        bekle(5000);
        String kartNo = text(driver, kartNoXpath).substring(7);
        System.out.println("Tutulan Değer = " + kartNo);
        andGeriGel(driver);
        bekle(5000);
        kaydir(driver, "up");
        kaydir(driver, "up");
        bekle(3000);
        String dashboard = text(driver, dashboardKartXpath);
        if (!kartNo.contains(dashboard)) {
            throw new AssertionError("Kart Değerleri Aynı Değil: detay = [" + kartNo + "], dashboard = [" + dashboard + "]");
        }
        System.out.println("Kart Değerleri Aynı: " + kartNo + " / " + dashboard);
    }

    /**
     * "I kontrolEt X or Y" — iki elemandan hangisinin gorundugunu dondurur
     * (ornek: kart listesi mi, bos liste mesaji mi). Ikisi de yoksa AssertionError.
     *
     * @return 1 (ilk eleman gorunuyor) veya 2 (ikinci eleman gorunuyor)
     */
    public static int andHangisiGorunuyor(WebDriver driver, String xpath1, String xpath2) {
        if (isDisplayed(driver, xpath1)) {
            System.out.println("Görünen: " + xpath1);
            return 1;
        }
        if (isDisplayed(driver, xpath2)) {
            System.out.println("Görünen: " + xpath2);
            return 2;
        }
        throw new AssertionError("İki eleman da görünmüyor: " + xpath1 + " / " + xpath2);
    }

    /**
     * "I popup kontrol et" — islem detay popup'inin alanlarini dogrular.
     * Taksitsiz: Islem Tutari + Islem Zamani. Taksitli: Taksit Sayisi + Taksit Tutari +
     * Islem Zamani + Kar Payi Orani. Ikisi de degilse AssertionError.
     *
     * @return "Taksitsiz" veya "Taksitli"
     */
    public static String andIslemDetayPopupKontrol(WebDriver driver) {
        bekle(1000);
        if (basliklarVeAciklamalarGorunuyor(driver, "İşlem Tutarı", "İşlem Zamanı")) {
            System.out.println("Taksitsiz Popup Kontrol = True");
            return "Taksitsiz";
        }
        if (basliklarVeAciklamalarGorunuyor(driver, "Taksit Sayısı", "Taksit Tutarı", "İşlem Zamanı", "Kar Payı Oranı")) {
            System.out.println("Taksitli Popup Kontrol = True");
            return "Taksitli";
        }
        throw new AssertionError("İşlem detay popup'ı beklenen alanları içermiyor (taksitli/taksitsiz).");
    }

    /**
     * "I taksit ayarla X or Y" — ek kart toggle'i varsa acar, Guncelle'ye basar; sonra
     * normal karta veya ek karta ait popup'tan hangisi geldiyse onun metnini dondurur.
     * Ikisi de gelmezse AssertionError.
     */
    public static String andTaksitAyarla(WebDriver driver, String normalPopupXpath, String ekKartPopupXpath) {
        String toggle = "(//*[@resource-id='" + PKG + "tButton'])[1]";
        if (isDisplayed(driver, toggle)) {
            click(driver, toggle);
        } else {
            System.out.println("Ek kart kısmı yok");
        }
        click(driver, "//*[@resource-id='" + PKG + "btnUpdate']");
        bekle(3000);

        for (String xpath : new String[]{normalPopupXpath, ekKartPopupXpath}) {
            List<WebElement> els = driver.findElements(By.xpath(xpath));
            if (!els.isEmpty() && els.get(0).isDisplayed()) {
                String gelen = els.get(0).getAttribute("text");
                System.out.println("Gelen: " + gelen);
                return gelen;
            }
        }
        throw new AssertionError("Taksit popup'ı gelmedi (normal / ek kart).");
    }

    /**
     * "I limit guncelle X and Y and Z" — limit metninin 47-55. karakterlerindeki tutari
     * alir, Tamam'a basar ve dogrulama elemanindaki degerin bu tutarin icinde oldugunu kontrol eder.
     *
     * @return eslestiyse true (kendisi fail etmez)
     */
    public static boolean andLimitGuncelleKontrol(WebDriver driver, String limitMetniXpath, String tamamXpath, String dogrulaXpath) {
        String tutar = text(driver, limitMetniXpath).substring(47, 55);
        System.out.println("Tutulan Değer: " + tutar);
        click(driver, tamamXpath);
        String dogrula = text(driver, dogrulaXpath);
        boolean eslesti = tutar.contains(dogrula);
        System.out.println(eslesti ? "Değerler Eşleşti..." : "Değerler Aynı Değil! Gelen deger = " + dogrula);
        return eslesti;
    }

    /**
     * "I maskeli para X" — Son Hareketler'in ilk 3 satirindaki tutarlarin maskeli ("*" iceren)
     * oldugunu dogrular; maskesiz tutar varsa AssertionError.
     */
    public static void andMaskeliTutarKontrol(WebDriver driver, String tutarListesiXpath) {
        for (int i = 1; i <= 3; i++) {
            String tutar = text(driver, tutarListesiXpath + "[" + i + "]");
            System.out.println(idText(driver, "tvDay", i) + " " + idText(driver, "tvMonth", i)
                    + " | " + idText(driver, "tvTransactionTitle", i) + " | " + tutar);
            if (!tutar.contains("*")) {
                throw new AssertionError("Tutar maskeli değil (satır " + i + "): " + tutar);
            }
        }
        System.out.println("İlk 3 hareketin tutarı maskeli.");
    }

    /**
     * "I hesapara X Y" — listede (index 1, 5, 9 ...) verilen para birimi disinda hesap varsa
     * AssertionError. (Eski kod Android'de "value" okuyup liste sonunda da hata veriyordu;
     * "text" okunacak ve liste bitince duracak sekilde duzeltildi.)
     */
    public static void andHesapParaBirimiKontrol(WebDriver driver, String baseXpath, String paraBirimi) {
        for (int say = 1; say <= 200; say += 4) {
            List<WebElement> els = driver.findElements(By.xpath(baseXpath + "[" + say + "]"));
            if (els.isEmpty()) {
                break;
            }
            String deger = els.get(0).getAttribute("text");
            System.out.println("Gelen Baslik: " + deger);
            if (deger == null || !deger.contains(paraBirimi)) {
                throw new AssertionError(paraBirimi + " haricinde hesap bulundu: " + deger);
            }
        }
        System.out.println("Sadece " + paraBirimi + " hesaplar listeleniyor.");
    }

    // ------------------------------------------------------------------
    // Akislar
    // ------------------------------------------------------------------

    /**
     * "I basarilibasarisizkontrol X and Y" — ekrandaki son basarili (metnin 20. karakterinden
     * sonrasi) ve basarisiz (18. karakterden sonrasi) giris tarihlerini okur; menu > Guvenlik
     * Ayarlari > Basarili/Basarisiz Girisler ekranindaki ilk kayitlarla karsilastirir.
     * Eslesmezse AssertionError. 18 karakterlik tarihlerin basina 0 eklenir.
     */
    public static void andBasariliBasarisizGirisKontrol(WebDriver driver, String basariliXpath, String basarisizXpath) {
        String basarili = text(driver, basariliXpath).substring(20);
        String basarisiz = text(driver, basarisizXpath).substring(18);
        System.out.println("Başarılı: " + basarili + " | Başarısız: " + basarisiz);

        bekle(2000);
        click(driver, YUKARI_GIT);
        bekle(1000);
        click(driver, "//*[@resource-id='" + PKG + "tvTitle' and @text='Güvenlik Ayarları']");
        bekle(1000);
        click(driver, "//*[@resource-id='" + PKG + "tvTitle' and @text='Başarılı/Başarısız Girişler']");
        bekle(2000);
        girisTarihiDogrula(driver, basarili, "Başarılı");

        bekle(2000);
        click(driver, "//*[@resource-id='" + PKG + "tab_title' and @text='Başarısız Girişler']");
        girisTarihiDogrula(driver, basarisiz, "Başarısız");
    }

    /**
     * "I kisayol X" — dashboard kisayol menuleri Hesaplar / Kartlar / Finansman degilse
     * Acilis Ekrani Ayarlari > Kisayol Menuleri'nden mevcut uc kisayolu kaldirip bu ucunu
     * secer, Uygula ile kaydeder ve dashboard'da gorundugunu dogrular (gorunmezse AssertionError).
     */
    public static void andKisayolMenuDuzenle(WebDriver driver, String ilkMenuXpath) {
        String m1 = text(driver, ilkMenuXpath);
        String m2 = text(driver, "(//*[@resource-id='" + PKG + "tvMenu'])[2]");
        String m3 = text(driver, "(//*[@resource-id='" + PKG + "tvMenu'])[3]");
        List<String> mevcut = Arrays.asList(m1, m2, m3);
        System.out.println("Mevcut kısayollar: " + mevcut);
        if (mevcut.equals(HEDEF_KISAYOLLAR)) {
            System.out.println("Menüler Doğru!");
            return;
        }

        kaydir(driver, "down");
        kaydir(driver, "down");
        click(driver, "//*[@resource-id='" + PKG + "tvSettings' and @text='Açılış Ekranı Ayarları']");
        bekle(3000);
        click(driver, "//*[@resource-id='" + PKG + "tvTitle' and @text='Kısayol Menüleri']");
        bekle(2000);

        // mevcut uc kisayolun secimini kaldir (liste ekrana sigmazsa asagi kaydirip devam et)
        Set<String> kaldirilan = new HashSet<>();
        if (!secimleriKaldir(driver, mevcut, kaldirilan, 15)) {
            kaydir(driver, "down");
            secimleriKaldir(driver, mevcut, kaldirilan, 11);
        }
        kaydir(driver, "up");

        for (String hedef : HEDEF_KISAYOLLAR) {
            click(driver, "//*[@resource-id='" + PKG + "tvText' and @text='" + hedef + "']");
        }
        bekle(2000);
        click(driver, "//*[@resource-id='" + PKG + "btnApply']");
        bekle(1000);
        click(driver, YUKARI_GIT);
        bekle(5000);
        for (String hedef : HEDEF_KISAYOLLAR) {
            if (!isDisplayed(driver, "//*[@resource-id='" + PKG + "tvMenu' and @text='" + hedef + "']")) {
                throw new AssertionError("Kısayol dashboard'da görünmüyor: " + hedef);
            }
        }
        System.out.println("Kısayollar Hesaplar / Kartlar / Finansman olarak ayarlandı.");
    }

    /**
     * "I agreementcontrol X" — sozlesme adini okur, 2. sozlesmeyi acip onaylar,
     * "Onaylanan" sekmesinde (ilk 10 kayit) bu sozlesmenin listelendigini kontrol eder.
     * Ekran gecislerinde 20'ser saniye bekler (eski koddaki gibi).
     *
     * @return sozlesme Onaylanan listesinde bulunduysa true
     */
    public static boolean andSozlesmeOnayKontrol(WebDriver driver, String sozlesmeAdiXpath) {
        String sozlesmeAdi = text(driver, sozlesmeAdiXpath);
        System.out.println("Sözleşme: " + sozlesmeAdi);
        click(driver, "(//*[@resource-id='" + PKG + "tvAgreementTitle'])[2]");
        bekle(20000);
        driver.findElement(By.xpath("//*[@text='Sözleşme Onay']"));
        click(driver, "//*[@resource-id='" + PKG + "btnApprove']");
        bekle(20000);
        click(driver, "//android.widget.LinearLayout[@content-desc='Onaylanan']/android.widget.TextView");
        bekle(20000);

        String base = "(//*[@resource-id='" + PKG + "tvAgreementTitle'])";
        for (int i = 1; i <= 10; i++) {
            List<WebElement> els = driver.findElements(By.xpath(base + "[" + i + "]"));
            if (els.isEmpty()) {
                break;
            }
            if (sozlesmeAdi.equals(els.get(0).getAttribute("text"))) {
                System.out.println("find agreement!");
                return true;
            }
        }
        System.out.println("not find!");
        return false;
    }

    // ------------------------------------------------------------------
    // Yardimcilar
    // ------------------------------------------------------------------

    private static String text(WebDriver driver, String xpath) {
        return driver.findElement(By.xpath(xpath)).getAttribute("text");
    }

    private static String idText(WebDriver driver, String resourceId, int index) {
        List<WebElement> els = driver.findElements(By.xpath("(//*[@resource-id='" + PKG + resourceId + "'])[" + index + "]"));
        return els.isEmpty() ? "" : els.get(0).getAttribute("text");
    }

    private static void click(WebDriver driver, String xpath) {
        driver.findElement(By.xpath(xpath)).click();
    }

    private static boolean isDisplayed(WebDriver driver, String xpath) {
        List<WebElement> els = driver.findElements(By.xpath(xpath));
        return !els.isEmpty() && els.get(0).isDisplayed();
    }

    private static boolean basliklarVeAciklamalarGorunuyor(WebDriver driver, String... basliklar) {
        for (int i = 0; i < basliklar.length; i++) {
            if (!isDisplayed(driver, "//*[@resource-id='" + PKG + "tvTitle' and @text='" + basliklar[i] + "']")
                    || !isDisplayed(driver, "(//*[@resource-id='" + PKG + "tvDescription'])[" + (i + 1) + "]")) {
                return false;
            }
        }
        return true;
    }

    /** Kisayol listesinde (tvText 1..adet) mevcut kisayollara tiklayip secimini kaldirir; liste bitmeden tamamlandiysa true. */
    private static boolean secimleriKaldir(WebDriver driver, List<String> mevcut, Set<String> kaldirilan, int adet) {
        for (int i = 1; i <= adet; i++) {
            List<WebElement> els = driver.findElements(By.xpath("(//*[@resource-id='" + PKG + "tvText'])[" + i + "]"));
            if (els.isEmpty()) {
                return false;
            }
            String ad = els.get(0).getAttribute("text");
            if (mevcut.contains(ad) && kaldirilan.add(ad)) {
                els.get(0).click();
            }
        }
        return true;
    }

    private static void girisTarihiDogrula(WebDriver driver, String beklenen, String tur) {
        String ekrandaki = text(driver, "(//*[@resource-id='" + PKG + "tvLoginDate'])[1]");
        String normal = beklenen.length() == 18 ? "0" + beklenen : beklenen;
        if (!normal.equals(ekrandaki)) {
            throw new AssertionError(tur + " giriş tarihi eşleşmedi. Beklenen = [" + normal + "], ekrandaki = [" + ekrandaki + "]");
        }
        System.out.println(tur + " giriş doğrulaması OK: " + ekrandaki);
    }

    private static String bosluksuz(String s) {
        return s.replaceAll(" ", "");
    }

    /** "Murabaha - X Finansmani" -> "X Finansmani" (eski: substring(indexOf("-")).replace("-","").substring(1)). */
    private static String finansmanAdi(String s) {
        return s.substring(s.indexOf("-")).replace("-", "").substring(1);
    }

    /**
     * Ekrani kaydirir (mobileSteps.scroll karsiligi). "down" = icerik asagi (parmak yukari),
     * "up" = icerik yukari. W3C pointer swipe; UiAutomator2 destekler.
     */
    private static void kaydir(WebDriver driver, String yon) {
        Dimension size = driver.manage().window().getSize();
        int x = size.getWidth() / 2;
        int alt = (int) (size.getHeight() * 0.70);
        int ust = (int) (size.getHeight() * 0.30);
        int baslangic = "down".equals(yon) ? alt : ust;
        int bitis = "down".equals(yon) ? ust : alt;

        PointerInput finger = new PointerInput(PointerInput.Kind.TOUCH, "finger");
        Sequence swipe = new Sequence(finger, 1)
                .addAction(finger.createPointerMove(Duration.ZERO, PointerInput.Origin.viewport(), x, baslangic))
                .addAction(finger.createPointerDown(PointerInput.MouseButton.LEFT.asArg()))
                .addAction(finger.createPointerMove(Duration.ofMillis(600), PointerInput.Origin.viewport(), x, bitis))
                .addAction(finger.createPointerUp(PointerInput.MouseButton.LEFT.asArg()));
        ((Interactive) driver).perform(Collections.singletonList(swipe));
    }

    private static void bekle(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
