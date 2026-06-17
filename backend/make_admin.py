import sqlite3
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "test_platform.db")

print(f"Veritabani yolu: {db_path}")

username = input("Admin kullanici adi [admin]: ").strip() or "admin"
password = input("Sifre [123]: ").strip() or "123"
full_name = input("Ad Soyad [Admin]: ").strip() or "Admin"

try:
    from passlib.context import CryptContext
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed = pwd_ctx.hash(password)
except Exception as e:
    print(f"HATA: passlib yuklu degil - {e}")
    print("Once venv'i aktive edip 'pip install passlib[bcrypt]' calistirin.")
    sys.exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username=?", (username,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            "UPDATE users SET role='admin', hashed_password=? WHERE username=?",
            (hashed, username)
        )
        print(f"OK: '{username}' guncellendi ve admin yapildi.")
    else:
        cursor.execute(
            "INSERT INTO users (username, email, full_name, hashed_password, role, is_active) VALUES (?,?,?,?,'admin',1)",
            (username, f"{username}@local.com", full_name, hashed)
        )
        print(f"OK: '{username}' olusturuldu ve admin yapildi.")

    conn.commit()
    conn.close()
    print(f"\nGiris: kullanici={username}  sifre={password}")

except Exception as e:
    print(f"HATA: {e}")
