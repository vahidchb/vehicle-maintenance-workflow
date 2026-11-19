"""اتصال و ساختار دیتابیس SQLite — فقط همین فایل با فایل .db حرف می‌زند.

دیتابیس یک فایل ساده است:
    data/maintenance.db

با کتابخانه استاندارد پایتون (sqlite3) کار می‌کنیم؛
هیچ پکیج جدیدی لازم نیست و requirements.txt عوض نمی‌شود.

چند نکته مهم:
1) هر عملیات، اتصال «تازه» خودش را باز می‌کند و بعد می‌بندد؛
   پس اگر FastAPI چند نخ (thread) داشته باشد، خطای
   «SQLite objects created in a thread» پیش نمی‌آید.
2) همه عملیات زیر یک قفل (lock) انجام می‌شوند تا دو عملیات
   هم‌زمان با هم قاطی نشوند (مثلا دو شماره رهگیری تکراری نسازند).
3) روی هر اتصال، `PRAGMA foreign_keys = ON` اجرا می‌شود تا
   کلیدهای خارجی واقعا اعمال شوند (پیش‌فرض SQLite خاموش است).
4) موقع اولین اتصال به یک فایل، تابع migrate() اجرا می‌شود:
   اگر دیتابیس قدیمی باشد (قبل از ایندکس‌ها و ستون extra_data)،
   ستون‌ها و ایندکس‌ها را اضافه می‌کند بدون اینکه داده‌ها پاک شوند.
   فقط قید FOREIGN KEY به دیتابیس قدیمی اضافه نمی‌شود (SQLite با
   ALTER TABLE نمی‌تواند قید اضافه کند)؛ برای اسکیمای کامل، فایل
   data/maintenance.db را پاک کن و برنامه را دوباره اجرا کن
   (داده نمایشی دوباره seed می‌شود).
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
#
# رابطه‌ها (کلید خارجی): هر جدول به جدول «قبل از خودش» در workflow
# وصل است؛ مثلا خرابی بدون ارزیابی نمی‌تواند وجود داشته باشد.
# دو ستون «عمدا» کلید خارجی ندارند:
# - fault_id در repair_requests و pending_confirmations: ممکن است خالی ('')
#   باشد، چون درخواست می‌تواند بدون خرابی هم باشد.
# - plate در همه جدول‌ها: برای جستجو کنار رکورد نگه داشته شده
#   (denormalized) و مرجع سفت و سخت نیست.
#
# extra_data: دیتای اضافی‌ای که کاربر موقع ثبت گفته ولی فیلد مشخصی
# ندارد (مثلا «سطح روغن کم بود»)، به‌صورت JSON اینجا می‌رود؛
# ستون‌های ثابت برای گزارش سریع و ایندکس‌دار می‌مانند.
#
# session_memory: حافظه هر جلسه چت — دو لایه (session_memory.py):
# summary = خلاصه غلتان همه حرف‌های قبل از چند پیام آخر،
# recent_messages = چند پیام آخر، عیناً به‌صورت JSON.
# چون CREATE TABLE IF NOT EXISTS است، روی دیتابیس قدیمی هم با اولین
# اتصال ساخته می‌شود و migrate لازم ندارد.
SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
    tracking TEXT PRIMARY KEY,
    plate TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    extra_data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS inspections (
    tracking TEXT PRIMARY KEY,
    plate TEXT NOT NULL,
    subsystem TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    extra_data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS evaluations (
    tracking TEXT PRIMARY KEY,
    plate TEXT NOT NULL,
    inspection_id TEXT NOT NULL REFERENCES inspections(tracking),
    summary TEXT NOT NULL,
    extra_data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS faults (
    tracking TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(tracking),
    plate TEXT NOT NULL,
    description TEXT NOT NULL,
    subsystem TEXT NOT NULL DEFAULT '',
    extra_data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS repair_requests (
    tracking TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(tracking),
    fault_id TEXT NOT NULL DEFAULT '',
    plate TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    extra_data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS work_orders (
    tracking TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES repair_requests(tracking),
    plate TEXT NOT NULL,
    shop TEXT NOT NULL,
    parts TEXT NOT NULL,
    status TEXT NOT NULL,
    extra_data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS pending_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    plate TEXT NOT NULL,
    equipment TEXT NOT NULL,
    evaluation_id TEXT NOT NULL REFERENCES evaluations(tracking),
    fault_id TEXT NOT NULL DEFAULT '',
    fault TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    inspection_json TEXT,
    extra_data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS session_memory (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    recent_messages TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""

# ایندکس‌ها — روی ستون‌هایی که در JOIN و WHERE استفاده می‌شوند.
# بدون ایندکس، هر JOIN یعنی اسکن کامل جدول (با بزرگ شدن داده کند می‌شود)؛
# با ایندکس، JOIN یک جستجوی سریع است. با EXPLAIN QUERY PLAN می‌شود
# دید که دیتابیس از ایندکس استفاده می‌کند (SEARCH) یا اسکن می‌کند (SCAN).
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_inspections_plate ON inspections(plate);
CREATE INDEX IF NOT EXISTS idx_evaluations_plate ON evaluations(plate);
CREATE INDEX IF NOT EXISTS idx_evaluations_inspection ON evaluations(inspection_id);
CREATE INDEX IF NOT EXISTS idx_faults_plate ON faults(plate);
CREATE INDEX IF NOT EXISTS idx_faults_evaluation ON faults(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_requests_plate ON repair_requests(plate);
CREATE INDEX IF NOT EXISTS idx_requests_evaluation ON repair_requests(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_requests_fault ON repair_requests(fault_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON repair_requests(status);
CREATE INDEX IF NOT EXISTS idx_work_orders_plate ON work_orders(plate);
CREATE INDEX IF NOT EXISTS idx_work_orders_request ON work_orders(request_id);
CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status);
"""

# جدول‌هایی که ستون extra_data دارند (برای migrate).
_TABLES_WITH_EXTRA = [
    "equipment",
    "inspections",
    "evaluations",
    "faults",
    "repair_requests",
    "work_orders",
    "pending_confirmations",
]

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


def migrate(conn: sqlite3.Connection) -> None:
    """دیتابیس قدیمی را به اسکیمای جدید برسان؛ داده‌ها دست نمی‌خورند.

    - اگر ستون extra_data نباشد، اضافه‌اش می‌کند (ALTER TABLE).
    - ایندکس‌ها را می‌سازد (اگر نیستند).
    صدا زدن دوباره‌اش بی‌ضرر است (اول چک می‌کند، بعد اضافه می‌کند).
    """
    for table in _TABLES_WITH_EXTRA:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "extra_data" not in columns:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN extra_data TEXT NOT NULL DEFAULT '{{}}'"
            )
    conn.executescript(INDEXES)


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
    روی هر اتصال، کلیدهای خارجی روشن می‌شوند.
    """
    path = _db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row  # ردیف‌ها مثل دیکشنری رفتار می‌کنند
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if str(path) not in _initialized:
            conn.executescript(SCHEMA)
            migrate(conn)
            conn.commit()
            _initialized.add(str(path))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
