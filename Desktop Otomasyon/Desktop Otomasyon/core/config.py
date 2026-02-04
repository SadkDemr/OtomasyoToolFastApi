import os
import logging
import pyautogui
import subprocess

import sys

# Uygulama Veri Dizini (Yerel Depolama - v35 & v37 Flash Drive Fix)
# Eğer EXE ise (Frozen), EXE'nin olduğu yeri baz al. Değilse __file__ kullan.
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(DATA_DIR, "assets")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "automation.db")

# Uygulama Sürümü
APP_VERSION = "v37"

def get_dpi_scaling():
    """DPI Ölçeklendirme çarpanını hesaplar."""
    try:
        # Mantıksal boyut (Windows'un gördüğü)
        logical_w, logical_h = pyautogui.size()
        
        # Gerçek boyut (Piksel bazlı screenshot boyutu)
        # Not: pyautogui.screenshot() gerçek piksel boyutunu verir
        with pyautogui.screenshot() as s:
            physical_w, physical_h = s.size
            
        scaling_x = physical_w / logical_w
        scaling_y = physical_h / logical_h
        
        # Genelde x ve y aynıdır
        return scaling_x
    except:
        return 1.0

def open_data_folder():
    """Veri klasörünü Windows Explorer'da açar."""
    if os.path.exists(DATA_DIR):
        os.startfile(DATA_DIR)

def initialize_persistence():
    """Gerekli klasörleri oluşturur."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    
    # Dosya logu ayarı
    log_file = os.path.join(LOGS_DIR, "last_session.log")
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(file_handler)
    
    logging.info(f"Kalıcı Veri Dizini Hazır: {DATA_DIR} (DPI Skaler: {get_dpi_scaling():.2f})")
