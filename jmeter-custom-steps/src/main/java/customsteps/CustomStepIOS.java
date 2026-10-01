package customsteps;

import org.openqa.selenium.By;
import org.openqa.selenium.NoSuchElementException;
import org.openqa.selenium.WebDriver;

/**
 * iOS — JMeter JSR223 Sampler'lardan cagrilacak custom adimlar.
 * WebDriver arayuzu kullanilir (IOSDriver da bu arayuzu implement eder),
 * boylece io.appium.java_client'a derleme zamaninda bagimlilik gerekmez.
 * Yeni method eklerken imza kuralini koru: ilk parametre WebDriver,
 * geri kalani adimin ihtiyac duydugu deger(ler).
 *
 * Kullanim (JSR223 - Groovy):
 *   import customsteps.CustomStepIOS;
 *   CustomStepIOS.temizle(driver, 4);
 */
public final class CustomStepIOS {

    private static final By DELETE_KEY_EN = By.xpath("//XCUIElementTypeKey[@name='delete' or @name='Delete']");
    private static final By DELETE_KEY_TR = By.xpath("//XCUIElementTypeKey[@name='Sil']");

    private CustomStepIOS() {
    }

    /**
     * Input alaninda xpath olmadigi durumlarda klavyedeki silme tusuna
     * elementKey kadar basar. Cihaz dili EN/TR olabileceginden hangi tusun
     * ekranda oldugu tek seferde tespit edilip donguye o locator ile girilir
     * (eski kod her tikta try/catch'e girip TR'ye gecince sayaci sifirliyordu).
     * MySteps'teki temizle333 bunun birebir kopyasiydi, ayrica tasinmadi.
     */
    public static void temizle(WebDriver driver, int elementKey) {
        By deleteKey = resolveDeleteKeyLocator(driver);
        for (int i = 0; i < elementKey; i++) {
            driver.findElement(deleteKey).click();
        }
    }

    private static By resolveDeleteKeyLocator(WebDriver driver) {
        try {
            driver.findElement(DELETE_KEY_TR);
            return DELETE_KEY_TR;
        } catch (NoSuchElementException e) {
            return DELETE_KEY_EN;
        }
    }
}
