"""
Database Configuration
FIXED: Timeout increased to 60s & WAL Mode
"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_platform.db"

# --- KİLİT ÇÖZÜMÜ ---
# "timeout": 60 -> Veritabanı meşgulse hemen hata verme, 60 saniye bekle.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False, "timeout": 60} 
)

# --- WAL MODU (Performans) ---
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception as e:
        print(f"Pragma ayar hatası: {e}")
    finally:
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    import models.db_models
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """Mevcut DB'ye yeni kolonlar ekle (SQLite ALTER TABLE)."""
    migrations = [
        "ALTER TABLE repositories ADD COLUMN provider TEXT NOT NULL DEFAULT 'generic'",
        "ALTER TABLE repositories ADD COLUMN editor_type TEXT NOT NULL DEFAULT 'ai'",
        "ALTER TABLE scenario_share_permissions ADD COLUMN owner_user_id INTEGER",
        "ALTER TABLE users ADD COLUMN last_login DATETIME",
        "ALTER TABLE users ADD COLUMN upload_only BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN tcg_area_path TEXT",
        "ALTER TABLE users ADD COLUMN tcg_assigned_to TEXT",
        "ALTER TABLE users ADD COLUMN tcg_state TEXT",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(_text(sql))
                conn.commit()
            except Exception:
                pass  # Kolon zaten varsa hata verir, geç


def _text(sql: str):
    from sqlalchemy import text
    return text(sql)