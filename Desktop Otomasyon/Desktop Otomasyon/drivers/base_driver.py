from abc import ABC, abstractmethod
from typing import Any, Tuple, Optional

class BaseDriver(ABC):
    """
    Tüm otomasyon sürücüleri (Desktop, Mobile, Web) için temel arayüz.
    Bu sınıf, platformdan bağımsız olarak senaryoların çalıştırılabilmesini sağlar.
    """

    @abstractmethod
    def launch_app(self, app_path: str) -> bool:
        """Uygulamayı başlatır."""
        pass

    @abstractmethod
    def click(self, target: str, by_image: bool = True) -> bool:
        """
        Belirtilen hedefe tıklar.
        :param target: Görsel yolu veya koordinat bilgisi
        :param by_image: True ise görsel arama yapar, False ise koordinat kullanır
        """
        pass

    @abstractmethod
    def type_text(self, text: str, interval: float = 0.1) -> bool:
        """
        Metin yazar.
        :param text: Yazılacak metin
        :param interval: Harfler arası bekleme süresi
        """
        pass

    @abstractmethod
    def wait(self, seconds: float):
        """Belirtilen süre kadar bekler."""
        pass

    @abstractmethod
    def assert_exists(self, target: str, timeout: int = 10) -> bool:
        """
        Ekranda belirli bir öğenin varlığını doğrular (Test Assertion).
        :param target: Aranacak görsel veya metin
        :param timeout: Maksimum bekleme süresi
        """
        pass

    @abstractmethod
    def take_screenshot(self, save_path: str) -> str:
        """Ekran görüntüsü alır ve kaydeder."""
        pass
