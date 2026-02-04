import sys
import os
import logging

# Global Log Seviyesi Force
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Proje kök dizinini path'e ekle
abs_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(abs_path)

def main():
    from core.config import initialize_persistence
    initialize_persistence()
    
    print("Desktop Otomasyon Başlatılıyor...")
    from ui.main_window import MainWindow
    app = MainWindow()
    app.mainloop()

if __name__ == "__main__":
    main()
