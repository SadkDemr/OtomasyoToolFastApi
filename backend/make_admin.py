import sqlite3
import os

# Veritabanı dosyasının yolunu bul
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "test_platform.db")

print(f"📂 Veritabanı yolu: {db_path}")

try:
    # Veritabanına bağlan
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Kullanıcıyı admin yap
    cursor.execute("UPDATE users SET role='admin' WHERE username='admin'")
    
    # Değişiklikleri kaydet
    conn.commit()
    
    # Kontrol et
    cursor.execute("SELECT username, role FROM users WHERE username='admin'")
    user = cursor.fetchone()
    
    if user and user[1] == 'admin':
        print(f"✅ BAŞARILI: '{user[0]}' kullanıcısı artık YÖNETİCİ (ADMIN) yetkisine sahip.")
    else:
        print("❌ HATA: Güncelleme yapılamadı.")

    conn.close()

except Exception as e:
    print(f"💥 Bir hata oluştu: {e}")