import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DATA_DIR = Path(os.environ.get("POCKET_MONEY_DATA_DIR", Path(__file__).resolve().parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{(DATA_DIR / 'pocket_money.db').as_posix()}"


def _load_encryption_key() -> bytes:
    """Завантажує або створює ключ шифрування для чутливих полів БД.

    Ключ береться із змінної оточення POCKET_MONEY_DB_KEY або з файлу
    DATA_DIR / .db_key. Якщо немає ні того ні іншого — генерується новий і
    записується у файл .db_key (читання лише для поточного користувача).
    """
    env_key = os.environ.get("POCKET_MONEY_DB_KEY")
    if env_key:
        return base64.urlsafe_b64decode(env_key.encode("utf-8"))

    key_file = DATA_DIR / ".db_key"
    if key_file.exists():
        return key_file.read_bytes()

    key = Fernet.generate_key()
    try:
        key_file.write_bytes(key)
    except OSError:
        pass
    return key


_ENCRYPTION_KEY = _load_encryption_key()
_fernet = Fernet(_ENCRYPTION_KEY)


def encrypt_field(value: str | None) -> str | None:
    """Шифрує рядок для збереження у відкритому тексті SQLite."""
    if value is None:
        return None
    return _fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_field(value: str | None) -> str | None:
    """Дешифрує рядок, що повертається із SQLite."""
    if value is None:
        return None
    return _fernet.decrypt(value.encode("utf-8")).decode("utf-8")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def protect_sqlite_connection(dbapi_connection, _connection_record):
    """Keep relational integrity and avoid leaving deleted secrets in SQLite pages."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA secure_delete=ON")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Створює окрему сесію бази даних для кожного запиту."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
