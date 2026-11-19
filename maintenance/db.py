"""اتصال و ساختار دیتابیس SQLite — فقط همین فایل با فایل .db حرف می‌زند.

دیتابیس یک فایل ساده است:
    data/maintenance.db

با کتابخانه استاندارد پایتون (sqlite3) کار می‌کنیم؛
هیچ پکیج جدیدی لازم نیست و requirements.txt عوض نمی‌شود.

دو نکته مهم:
1) هر عملیات، اتصال «تازه» خودش را باز می‌کند و بعد می‌بندد؛
   پس اگر FastAPI چند نخ (thread) داشته باشد، خطای
   «SQLite objects created in a thread» پیش نمی‌آید.
2) همه عملیات زیر یک قفل (lock) انجام می‌شوند تا دو عملیات
   هم‌زمان با هم قاطی نشوند (مثلا دو شماره رهگیری تکراری نسازند).
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

# ریشه پروژه = پوشه‌ای که maintenance/ داخل آن است.
# با pathlib حساب می‌کنیم تا روی ویندوز هم درست کار کند.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# مسیر پیش‌فرض فایل دیتابیس.
# با متغیر محیطی VEHICLE_DB_PATH می‌شود عوضش کرد (تست‌ها همین کار را می‌کنند).
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "maintenance.db"

# ساختار جدول‌ها — یک جدول برای هر ماژول.
# شماره رهگیری (EQ-001 و...) کلید اصلی هر جدول است؛
# برای تجهیز، پلاک هم یکتا (UNIQUE) است چون جستجو با پلاک انجام می‌شود.
SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
    tracking TEXT PRIMARY KEY,
    plate TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS inspections (
    tracking TEXT PRIMARY KEY,
    plate TEXT NOT NULL,
    subsystem TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS evaluations (
    tracking TEXT PRIMARY KEY,
    plate TEXT NOT NULL,
    inspection_id TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS faults (
    tracking TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    plate TEXT NOT NULL,
    description TEXT NOT NULL,
    subsystem TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS repair_requests (
    tracking TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    fault_id TEXT NOT NULL DEFAULT '',
    plate TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_orders (
    tracking TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    plate TEXT NOT NULL,
    shop TEXT NOT NULL,
    parts TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    plate TEXT NOT NULL,
    equipment TEXT NOT NULL,
    evaluation_id TEXT NOT NULL,
    fault_id TEXT NOT NULL DEFAULT '',
    fault TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    inspection_json TEXT
);
"""

# قفل سراسری (RLock تا توابع بتوانند همدیگر را صدا بزنند).
lock = threading.RLock()

# مسیر فعلی فایل دیتابیس (با set_db_path عوض می‌شود).
_db_path: Path = Path(os.environ.get("VEHICLE_DB_PATH") or DEFAULT_DB_PATH)

# مسیرهایی که جدول‌هایشان ساخته شده؛ هر مسیر فقط یک بار ساخته می‌شود.
_initialized: set[str] = set()


def get_db_path() -> Path:
    """مسیر فعلی فایل دیتابیس را برگردان."""
    return _db_path


def set_db_path(path: str | Path) -> None:
    """مسیر فایل دیتابیس را عوض کن (برای تست؛ تست‌ها فایل موقت می‌دهند)."""
    global _db_path
    _db_path = Path(path)


def init_db() -> Path:
    """جدول‌ها را بساز (اگر نیستند) و مسیر فایل دیتابیس را برگردان.

    موقع بالا آمدن برنامه صدا زده می‌شود (api.py و main.py).
    صدا زدن دوباره‌اش بی‌ضرر است (CREATE TABLE IF NOT EXISTS).
    """
    with lock:
        with connect():
            pass
    return _db_path


@contextmanager
def connect():
    """یک اتصال تازه به دیتابیس بده؛ موقع خروج commit کن و ببند.

    اگر جدول‌ها هنوز ساخته نشده‌اند، همین‌جا ساخته می‌شوند؛
    پس لازم نیست جایی حتماً قبلش init_db صدا زده شود.
    """
    path = _db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row  # ردیف‌ها مثل دیکشنری رفتار می‌کنند
    try:
        if str(path) not in _initialized:
            conn.executescript(SCHEMA)
            conn.commit()
            _initialized.add(str(path))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
