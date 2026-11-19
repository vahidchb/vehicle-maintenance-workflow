"""گزارش‌گیری از دیتابیس — SQL همین‌جا زندگی می‌کند، نه در tools.py.

دو راه برای گزارش هست:
1) گزارش‌های آماده (REPORTS): کوئری‌های از پیش تیون‌شده — فقط ستون‌های
   لازم (نه SELECT *)، جوین روی ستون‌های ایندکس‌دار، و سقف ردیف.
   همیشه اول این‌ها را امتحان کن.
2) کوئری آزاد (run_sql): وقتی هیچ گزارش آماده‌ای جواب نمی‌دهد، مدل یک
   SELECT می‌نویسد؛ با گاردریل اجرا می‌شود (فقط خواندنی، سقف ۵۰ ردیف،
   تایم‌اوت ۵ ثانیه) تا یک کوئری بد نتواند سیستم را قفل کند.

نکته مهم: داده‌ها هیچ‌وقت کامل وارد context مدل نمی‌شوند؛ فقط «نتیجه»
گزارش (چند ردیف) برمی‌گردد. دیتابیس حافظه است، مدل فقط سؤال می‌پرسد.
"""
import re
import sqlite3
import time
from urllib.parse import quote

from . import db

# سقف ردیف هر گزارش — برای اینکه جواب گزارش، context را پر نکند.
MAX_ROWS = 50

# تایم‌اوت کوئری آزاد (ثانیه).
SQL_TIMEOUT_SECONDS = 5

# کلمه‌هایی که در کوئری آزاد ممنوع‌اند (فقط خواندن مجاز است).
_FORBIDDEN_WORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
    "TRUNCATE", "VACUUM", "PRAGMA", "ATTACH", "DETACH", "REINDEX", "ANALYZE",
)


# --- اجرای کوئری و شکل یکنواخت نتیجه ---
def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    """یک SELECT اجرا کن و ردیف‌ها را به‌صورت دیکشنری برگردان."""
    cursor = conn.execute(sql, params)
    columns = [d[0] for d in cursor.description] if cursor.description else []
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _result(title: str, rows: list[dict], total: int, truncated: bool) -> dict:
    """نتیجه یک گزارش، با شکل یکنواخت برای همه گزارش‌ها."""
    return {
        "ok": True,
        "title": title,
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows,
        "total": total,
        "truncated": truncated,
    }


def _error(message: str) -> dict:
    """نتیجه خطا، با همان شکل یکنواخت."""
    return {"ok": False, "title": "", "columns": [], "rows": [],
            "total": 0, "truncated": False, "message": message}


def _cap(rows: list[dict], total: int) -> tuple[list[dict], bool]:
    """ردیف‌ها را به سقف برسان؛ بگو چیزی جا ماند یا نه."""
    if len(rows) > MAX_ROWS:
        return rows[:MAX_ROWS], True
    return rows, total > len(rows)


# --- گزارش‌های آماده (هر کدام یک کوئری تیون‌شده) ---
def _pending_approvals(conn, params: dict) -> dict:
    """درخواست‌های در انتظار تایید، با خرابیِ هر کدام."""
    rows = _rows(conn, """
        SELECT r.tracking AS tracking, r.plate AS plate,
               r.description AS description, f.description AS fault
        FROM repair_requests r
        LEFT JOIN faults f ON f.tracking = r.fault_id
        WHERE r.status = 'در انتظار تایید'
        ORDER BY r.rowid
        LIMIT 51
    """)
    total = conn.execute(
        "SELECT COUNT(*) FROM repair_requests WHERE status = 'در انتظار تایید'"
    ).fetchone()[0]
    rows, truncated = _cap(rows, total)
    return _result("درخواست‌های در انتظار تایید", rows, total, truncated)


def _faults_by_vehicle(conn, params: dict) -> dict:
    """خرابی‌ها با وضعیت درخواست و حکم کارشان؛ plate اختیاری است."""
    plate = (params.get("plate") or "").strip()
    where = "WHERE f.plate = ?" if plate else ""
    args = (plate,) if plate else ()
    rows = _rows(conn, f"""
        SELECT f.tracking AS tracking, f.plate AS plate,
               f.description AS description, f.subsystem AS subsystem,
               r.tracking AS request_id, r.status AS request_status,
               w.tracking AS work_order_id
        FROM faults f
        LEFT JOIN repair_requests r ON r.fault_id = f.tracking
        LEFT JOIN work_orders w ON w.request_id = r.tracking
        {where}
        ORDER BY f.plate, f.rowid
        LIMIT 51
    """, args)
    total = conn.execute(
        f"SELECT COUNT(*) FROM faults f {where}", args
    ).fetchone()[0]
    rows, truncated = _cap(rows, total)
    title = "خرابی‌ها با وضعیت درخواست و حکم کار"
    if plate:
        title += f" — پلاک {plate}"
    return _result(title, rows, total, truncated)


def _faults_by_subsystem(conn, params: dict) -> dict:
    """تعداد خرابی هر زیرمجموعه (موتور، چرخ و...)."""
    rows = _rows(conn, """
        SELECT subsystem, COUNT(*) AS count
        FROM faults
        GROUP BY subsystem
        ORDER BY count DESC, subsystem
        LIMIT 51
    """)
    rows, truncated = _cap(rows, len(rows))
    return _result("تعداد خرابی هر زیرمجموعه", rows, len(rows), truncated)


def _work_orders_by_shop(conn, params: dict) -> dict:
    """تعداد حکم کار هر تعمیرگاه."""
    rows = _rows(conn, """
        SELECT shop, COUNT(*) AS count
        FROM work_orders
        GROUP BY shop
        ORDER BY count DESC, shop
        LIMIT 51
    """)
    rows, truncated = _cap(rows, len(rows))
    return _result("تعداد حکم کار هر تعمیرگاه", rows, len(rows), truncated)


def _vehicle_history(conn, params: dict) -> dict:
    """سابقه کامل یک خودرو: تجهیز، بازدیدها، ارزیابی‌ها، خرابی‌ها،
    درخواست‌ها و حکم کارها — هر کدام یک کوئری کوچک روی ایندکس plate."""
    plate = (params.get("plate") or "").strip()
    if not plate:
        return _error("برای گزارش سابقه خودرو، پلاک لازم است.")
    vehicle = conn.execute(
        "SELECT tracking, plate, name, kind FROM equipment WHERE plate = ?",
        (plate,),
    ).fetchone()
    if vehicle is None:
        return _error(f"خودرویی با پلاک «{plate}» پیدا نشد.")

    rows: list[dict] = [{
        "section": "تجهیز",
        "detail": f"{vehicle['name']} — پلاک {vehicle['plate']} ({vehicle['tracking']})",
    }]
    total = 1
    truncated = False
    sections = [
        ("بازدید", "SELECT tracking, subsystem, note FROM inspections "
         "WHERE plate = ? ORDER BY rowid LIMIT 51",
         lambda r: f"{r['tracking']} | {r['subsystem']} | {r['note'] or '—'}"),
        ("ارزیابی", "SELECT tracking, inspection_id, summary FROM evaluations "
         "WHERE plate = ? ORDER BY rowid LIMIT 51",
         lambda r: f"{r['tracking']} | بازدید {r['inspection_id']} | {r['summary']}"),
        ("خرابی", "SELECT tracking, description, subsystem FROM faults "
         "WHERE plate = ? ORDER BY rowid LIMIT 51",
         lambda r: f"{r['tracking']} | {r['description']} ({r['subsystem'] or '—'})"),
        ("درخواست", "SELECT tracking, description, status FROM repair_requests "
         "WHERE plate = ? ORDER BY rowid LIMIT 51",
         lambda r: f"{r['tracking']} | {r['description']} | {r['status']}"),
        ("حکم کار", "SELECT tracking, shop, parts, status FROM work_orders "
         "WHERE plate = ? ORDER BY rowid LIMIT 51",
         lambda r: f"{r['tracking']} | {r['shop']} | {r['parts']} | {r['status']}"),
    ]
    for section, sql, fmt in sections:
        items = _rows(conn, sql, (plate,))
        total += len(items)
        if len(items) > MAX_ROWS:
            items = items[:MAX_ROWS]
            truncated = True
        for item in items:
            rows.append({"section": section, "detail": fmt(item)})
    return _result(f"سابقه کامل خودروی پلاک {plate}", rows, total, truncated)


# نام گزارش → (عنوان، تابع، توضیح یک‌خطی برای مدل)
REPORTS = {
    "pending_approvals": (
        "درخواست‌های در انتظار تایید", _pending_approvals,
        "لیست و تعداد درخواست‌های تعمیراتی که هنوز تایید نشده‌اند",
    ),
    "faults_by_vehicle": (
        "خرابی‌ها با وضعیت درخواست و حکم کار", _faults_by_vehicle,
        "خرابی هر خودرو با شماره درخواست و حکم کارش (plate اختیاری است)",
    ),
    "faults_by_subsystem": (
        "تعداد خرابی هر زیرمجموعه", _faults_by_subsystem,
        "مثلا موتور چند خرابی داشته و چرخ چند تا",
    ),
    "work_orders_by_shop": (
        "تعداد حکم کار هر تعمیرگاه", _work_orders_by_shop,
        "هر تعمیرگاه چند حکم کار گرفته است",
    ),
    "vehicle_history": (
        "سابقه کامل یک خودرو", _vehicle_history,
        "همه بازدیدها، ارزیابی‌ها، خرابی‌ها، درخواست‌ها و حکم کارهای یک پلاک (plate لازم است)",
    ),
}


def run_report(name: str, params: dict | None = None) -> dict:
    """یک گزارش آماده را با نامش اجرا کن.

    name: یکی از کلیدهای REPORTS. params: مثلا {"plate": "123"}.
    اگر نام را نشناسیم، خطای فارسی با لیست گزارش‌ها برمی‌گردد.
    """
    entry = REPORTS.get((name or "").strip())
    if entry is None:
        available = "، ".join(
            f"{key} ({desc})" for key, (_, _, desc) in REPORTS.items()
        )
        return _error(f"گزارشی به اسم «{name}» نداریم. گزارش‌های آماده: {available}")
    _, fn, _ = entry
    with db.connect() as conn:
        return fn(conn, params or {})


# --- کوئری آزاد با گاردریل ---
def _strip_literals(sql: str) -> str:
    """متن داخل کوتیشن‌ها را حذف کن تا کلمه‌های ممنوعه داخل
    رشته‌ها (مثلا WHERE description LIKE '%update%') اشتباهی رد نشوند."""
    no_single = re.sub(r"'(?:[^']|'')*'", "''", sql)
    return re.sub(r'"(?:[^"]|"")*"', '""', no_single)


def _validate_sql(sql: str) -> tuple[str, str | None]:
    """کوئری آزاد را چک کن؛ اگر مشکل داشت، پیام خطای فارسی برگردان.

    قوانین: فقط یک کوئری؛ فقط SELECT یا WITH؛ هیچ کلمه تغییردهنده‌ای.
    """
    clean = sql.strip()
    # نقطه‌ویرگول‌های آخر را بردار؛ اگر وسط کوئری نقطه‌ویرگول ماند،
    # یعنی چند کوئری است و رد می‌شود.
    clean = clean.rstrip(";").strip()
    if ";" in _strip_literals(clean):
        return "", "فقط یک کوئری می‌توانم اجرا کنم؛ چند کوئری با نقطه‌ویرگول نفرست."
    # کامنت‌های اول کوئری را برای چک کردن شروع، کنار بگذار
    head = re.sub(r"^(--.*\n|\s|/\*.*?\*/)*", "", clean, flags=re.S)
    if not re.match(r"(?i)(SELECT|WITH)\b", head):
        return "", "فقط کوئری خواندنی (SELECT یا WITH) مجاز است."
    stripped = _strip_literals(clean).upper()
    for word in _FORBIDDEN_WORDS:
        if re.search(rf"\b{word}\b", stripped):
            return "", f"کلمه «{word}» در کوئری آزاد مجاز نیست؛ فقط خواندن."
    return clean, None


def _apply_limit(sql: str) -> str:
    """سقف ردیف را اعمال کن: اگر LIMIT نداشت اضافه کن،
    اگر داشت و بیشتر از سقف بود، به سقف برسان."""
    stripped = _strip_literals(sql)
    if not re.search(r"(?i)\bLIMIT\b", stripped):
        return sql + f" LIMIT {MAX_ROWS}"

    def _cap_match(match: re.Match) -> str:
        number = int(match.group(1))
        capped = MAX_ROWS if (number < 0 or number > MAX_ROWS) else number
        return f"LIMIT {capped}"

    return re.sub(r"(?i)\bLIMIT\s+(-?\d+)", _cap_match, sql)


def _read_only_connection() -> sqlite3.Connection:
    """اتصال فقط-خواندنی به دیتابیس (mode=ro)؛ حتی اگر کوئری بخواهد
    چیزی بنویسد، SQLite اجازه نمی‌دهد."""
    path = db.get_db_path()
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=SQL_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    return conn


def run_sql(sql: str) -> dict:
    """یک کوئری SELECT آزاد اجرا کن؛ با گاردریل (فقط خواندنی،
    سقف ۵۰ ردیف، تایم‌اوت ۵ ثانیه)."""
    clean, error = _validate_sql(sql)
    if error is not None:
        return _error(error)
    clean = _apply_limit(clean)
    started = time.monotonic()

    def _progress() -> int:
        # هر ۱۰۰۰ دستور ماشین صدا زده می‌شود؛ اگر تایم‌اوت شد،
        # با برگرداندن ۱ کوئری را قطع کن.
        return 1 if time.monotonic() - started > SQL_TIMEOUT_SECONDS else 0

    try:
        conn = _read_only_connection()
    except sqlite3.Error:
        return _error("دیتابیس پیدا نشد؛ اول برنامه را اجرا کن تا ساخته شود.")
    try:
        conn.set_progress_handler(_progress, 1000)
        cursor = conn.execute(clean)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        fetched = cursor.fetchall()
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            return _error(
                f"کوئری خیلی طول کشید (بیش از {SQL_TIMEOUT_SECONDS} ثانیه)؛ "
                "کوئری ساده‌تری بنویس یا از گزارش‌های آماده استفاده کن."
            )
        return _error(f"کوئری اجرا نشد: {exc}")
    except sqlite3.Error as exc:
        return _error(f"کوئری اجرا نشد: {exc}")
    finally:
        conn.close()
    rows = [dict(zip(columns, row)) for row in fetched]
    truncated = len(rows) >= MAX_ROWS
    return {
        "ok": True,
        "title": "نتیجه کوئری",
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "total": len(rows),
        "truncated": truncated,
    }


def explain_query_plan(sql: str, params: tuple = ()) -> list[str]:
    """نقشه اجرای یک کوئری را برگردان (برای چک کردن ایندکس).

    اگر روی جدول جوین‌شده SEARCH ... USING INDEX ببینی، یعنی ایندکس
    استفاده شده؛ SCAN یعنی اسکن کامل جدول.
    """
    with db.connect() as conn:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    return [row[3] for row in rows]


# --- قالب‌بندی نتیجه برای چت ---
def format_result(result: dict) -> str:
    """نتیجه یک گزارش را به متن فارسی ساده تبدیل کن (برای ابزار چت)."""
    if not result.get("ok"):
        return result.get("message", "گزارش اجرا نشد.")
    rows = result["rows"]
    if not rows:
        return f"{result['title']}: چیزی پیدا نشد."
    lines = [f"{result['title']} ({result['total']} ردیف):"]
    for row in rows:
        parts = [str(value) if value not in ("", None) else "—"
                 for value in row.values()]
        lines.append("- " + " | ".join(parts))
    if result["truncated"]:
        lines.append(f"… فقط {MAX_ROWS} ردیف اول نشان داده شد.")
    return "\n".join(lines)
