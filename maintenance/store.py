"""حافظه رکوردها — حالا روی دیتابیس SQLite ذخیره می‌شود.

قبلاً رکوردها فقط در حافظه (RAM) بودند و با خاموش شدن برنامه پاک می‌شدند.
حالا هر رکورد در فایل data/maintenance.db نوشته می‌شود و بعد از
ری‌استارت بک‌اند هم سر جایش هست.

این فایل «ظاهرش» عوض نشده: اسم و ورودی/خروجی تابع‌ها دقیقاً مثل قبل است،
پس workflow.py و tools.py و chat.py و api.py بدون هیچ تغییری کار می‌کنند.
فقط «داخل» تابع‌ها به‌جای دیکشنری، به دیتابیس حرف می‌زنند.
(اتصال و ساختار جدول‌ها در maintenance/db.py است.)

هر رکورد یک شماره رهگیری دارد: EQ-001 ، INSP-001 ، EV-001 ،
FLT-001 ، REQ-001 ، WO-001
"""
import json

from . import db

# برای راحتی: init_db و مسیر دیتابیس از همین‌جا هم در دسترس‌اند.
init_db = db.init_db
get_db_path = db.get_db_path

# هر پیشوند شماره رهگیری، مال کدام جدول و کدام ستون است؟
# (برای ادامه دادن شماره‌ها بعد از ری‌استارت لازم است.)
_PREFIX_TABLES = {
    "EQ": ("equipment", "tracking"),
    "INSP": ("inspections", "tracking"),
    "EV": ("evaluations", "tracking"),
    "FLT": ("faults", "tracking"),
    "REQ": ("repair_requests", "tracking"),
    "WO": ("work_orders", "tracking"),
    "CONF": ("pending_confirmations", "confirmation_id"),
}

# شمارنده هر پیشوند، داخل حافظه (برای اینکه دو next_tracking پشت سر هم
# شماره تکراری ندهند). موقع ری‌استارت خالی است و از دیتابیس پر می‌شود.
_counters: dict[str, int] = {}


def set_db_path(path) -> None:
    """مسیر فایل دیتابیس را عوض کن (برای تست)؛ شمارنده‌ها را هم صفر کن."""
    with db.lock:
        db.set_db_path(path)
        _counters.clear()


def _max_suffix(prefix: str) -> int:
    """بزرگ‌ترین عدد آخر شماره‌های یک پیشوند را از دیتابیس بخوان.

    مثلا اگر در جدول تجهیز EQ-001 تا EQ-003 باشد، 3 برمی‌گرداند.
    اگر جدول خالی باشد یا پیشوند را نشناسیم، 0 برمی‌گرداند.
    """
    mapping = _PREFIX_TABLES.get(prefix)
    if mapping is None:
        return 0
    table, column = mapping
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {column} FROM {table}").fetchall()
    biggest = 0
    for row in rows:
        try:
            number = int(str(row[0]).rsplit("-", 1)[-1])
        except (ValueError, IndexError):
            continue
        biggest = max(biggest, number)
    return biggest


def next_tracking(prefix: str) -> str:
    """شماره رهگیری بعدی را بساز، مثلا EQ-001.

    از بزرگ‌ترین شماره‌ای که در دیتابیس هست ادامه می‌دهد،
    پس بعد از ری‌استارت هم شماره تکراری ساخته نمی‌شود.
    """
    with db.lock:
        _counters[prefix] = max(_counters.get(prefix, 0), _max_suffix(prefix)) + 1
        return f"{prefix}-{_counters[prefix]:03d}"


def reset() -> None:
    """همه رکوردها و شمارنده‌ها را پاک کن (برای تست). جدول‌ها می‌مانند."""
    with db.lock:
        with db.connect() as conn:
            for table, _ in _PREFIX_TABLES.values():
                conn.execute(f"DELETE FROM {table}")
        _counters.clear()


# --- تبدیل ردیف دیتابیس به دیکشنری رکورد ---
def _record(row) -> dict:
    """یک ردیف دیتابیس را به دیکشنری رکورد تبدیل کن."""
    return dict(row)


def _pending_record(row) -> dict:
    """ردیف تاییدیه در انتظار را به دیکشنری تبدیل کن.

    گزارش بازدید (inspection) در دیتابیس به‌صورت متن JSON نگه داشته می‌شود؛
    موقع خواندن دوباره دیکشنری‌اش می‌کنیم (یا None اگر نبود).
    """
    record = dict(row)
    raw = record.pop("inspection_json", None)
    record["inspection"] = json.loads(raw) if raw else None
    return record


# --- تجهیز (خودرو) ---
def add_vehicle(plate: str, name: str, kind: str = "") -> dict:
    """یک تجهیز/خودرو با شماره پلاک ثبت کن."""
    with db.lock:
        record = {
            "tracking": next_tracking("EQ"),
            "plate": plate.strip(),
            "name": name,
            "kind": kind,
        }
        with db.connect() as conn:
            # اگر همین پلاک قبلاً بود، رکوردش جایگزین می‌شود (مثل قبل).
            conn.execute(
                "INSERT OR REPLACE INTO equipment (tracking, plate, name, kind)"
                " VALUES (?, ?, ?, ?)",
                (record["tracking"], record["plate"], record["name"], record["kind"]),
            )
        return record


def get_vehicle(plate: str) -> dict | None:
    """خودرو را با پلاک پیدا کن."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM equipment WHERE plate = ?", (plate.strip(),)
        ).fetchone()
    return _record(row) if row is not None else None


def list_vehicles() -> list[dict]:
    """همه تجهیزها را برگردان (به ترتیب ثبت)."""
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM equipment ORDER BY rowid").fetchall()
    return [_record(r) for r in rows]


# --- بازدید ---
def add_inspection(plate: str, subsystem: str, note: str = "") -> dict:
    """یک بازدید برای یک خودرو ثبت کن."""
    with db.lock:
        record = {
            "tracking": next_tracking("INSP"),
            "plate": plate.strip(),
            "subsystem": subsystem,
            "note": note,
        }
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO inspections (tracking, plate, subsystem, note)"
                " VALUES (?, ?, ?, ?)",
                (record["tracking"], record["plate"], record["subsystem"], record["note"]),
            )
        return record


def get_inspection(tracking: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM inspections WHERE tracking = ?", (tracking.strip().upper(),)
        ).fetchone()
    return _record(row) if row is not None else None


def list_inspections() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM inspections ORDER BY rowid").fetchall()
    return [_record(r) for r in rows]


# --- ارزیابی (می‌تواند بدون خرابی باشد) ---
def add_evaluation(plate: str, inspection_id: str, summary: str) -> dict:
    """یک ارزیابی برای یک بازدید ثبت کن."""
    with db.lock:
        record = {
            "tracking": next_tracking("EV"),
            "plate": plate.strip(),
            "inspection_id": inspection_id.strip().upper(),
            "summary": summary,
        }
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO evaluations (tracking, plate, inspection_id, summary)"
                " VALUES (?, ?, ?, ?)",
                (record["tracking"], record["plate"], record["inspection_id"], record["summary"]),
            )
        return record


def get_evaluation(tracking: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM evaluations WHERE tracking = ?", (tracking.strip().upper(),)
        ).fetchone()
    return _record(row) if row is not None else None


def list_evaluations() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM evaluations ORDER BY rowid").fetchall()
    return [_record(r) for r in rows]


# --- خرابی (قدم جدا، وصل به یک ارزیابی) ---
def add_fault(evaluation_id: str, description: str, subsystem: str = "") -> dict:
    """یک خرابی برای یک ارزیابی ثبت کن."""
    with db.lock:
        evaluation = get_evaluation(evaluation_id)
        record = {
            "tracking": next_tracking("FLT"),
            "evaluation_id": evaluation_id.strip().upper(),
            "plate": evaluation["plate"] if evaluation else "",
            "description": description,
            "subsystem": subsystem,
        }
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO faults (tracking, evaluation_id, plate, description, subsystem)"
                " VALUES (?, ?, ?, ?, ?)",
                (record["tracking"], record["evaluation_id"], record["plate"],
                 record["description"], record["subsystem"]),
            )
        return record


def get_fault(tracking: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM faults WHERE tracking = ?", (tracking.strip().upper(),)
        ).fetchone()
    return _record(row) if row is not None else None


def list_faults() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM faults ORDER BY rowid").fetchall()
    return [_record(r) for r in rows]


def faults_for_evaluation(evaluation_id: str) -> list[dict]:
    """خرابی‌های یک ارزیابی را برگردان."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM faults WHERE evaluation_id = ? ORDER BY rowid",
            (evaluation_id.strip().upper(),),
        ).fetchall()
    return [_record(r) for r in rows]


# --- درخواست تعمیراتی ---
def add_repair_request(evaluation_id: str, fault_id: str, description: str) -> dict:
    """یک درخواست تعمیراتی ثبت کن؛ وضعیت اول: در انتظار تایید."""
    with db.lock:
        evaluation = get_evaluation(evaluation_id)
        record = {
            "tracking": next_tracking("REQ"),
            "evaluation_id": evaluation_id.strip().upper(),
            "fault_id": fault_id.strip().upper() if fault_id else "",
            "plate": evaluation["plate"] if evaluation else "",
            "description": description,
            "status": "در انتظار تایید",
        }
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO repair_requests"
                " (tracking, evaluation_id, fault_id, plate, description, status)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (record["tracking"], record["evaluation_id"], record["fault_id"],
                 record["plate"], record["description"], record["status"]),
            )
        return record


def get_request(tracking: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM repair_requests WHERE tracking = ?", (tracking.strip().upper(),)
        ).fetchone()
    return _record(row) if row is not None else None


def list_requests() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM repair_requests ORDER BY rowid").fetchall()
    return [_record(r) for r in rows]


def approve_request(tracking: str) -> dict | None:
    """درخواست را تایید کن؛ اگر نبود None برگردان."""
    with db.lock:
        record = get_request(tracking)
        if record is None:
            return None
        with db.connect() as conn:
            conn.execute(
                "UPDATE repair_requests SET status = 'تایید شده' WHERE tracking = ?",
                (tracking.strip().upper(),),
            )
        record["status"] = "تایید شده"
        return record


# --- تاییدیه در انتظار (قبل از ثبت درخواست تعمیراتی) ---
def add_pending_confirmation(plate: str, equipment_name: str, evaluation_id: str,
                             fault_id: str, fault_description: str,
                             description: str = "",
                             inspection: dict | None = None) -> dict:
    """یک درخواست تعمیراتی آماده کن که هنوز ثبت نشده و منتظر تایید کاربر است.

    inspection: گزارش بازدیدی که ارزیابی روی آن ثبت شده، برای نمایش
    در پنجره تایید (شماره رهگیری، زیرمجموعه، توضیح)؛ اگر نبود None است.
    """
    with db.lock:
        record = {
            "confirmation_id": next_tracking("CONF"),
            "plate": plate.strip(),
            "equipment": equipment_name,
            "evaluation_id": evaluation_id.strip().upper(),
            "fault_id": fault_id.strip().upper() if fault_id else "",
            "fault": fault_description,
            "description": description,
            "inspection": inspection,
        }
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO pending_confirmations"
                " (confirmation_id, plate, equipment, evaluation_id, fault_id,"
                " fault, description, inspection_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (record["confirmation_id"], record["plate"], record["equipment"],
                 record["evaluation_id"], record["fault_id"], record["fault"],
                 record["description"],
                 json.dumps(inspection, ensure_ascii=False) if inspection else None),
            )
        return record


def get_pending_confirmation(confirmation_id: str) -> dict | None:
    """تاییدیه در انتظار را با شماره‌اش پیدا کن."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_confirmations WHERE confirmation_id = ?",
            (confirmation_id.strip().upper(),),
        ).fetchone()
    return _pending_record(row) if row is not None else None


def list_pending_confirmations() -> list[dict]:
    """همه تاییدیه‌های در انتظار را برگردان."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_confirmations ORDER BY rowid"
        ).fetchall()
    return [_pending_record(r) for r in rows]


def remove_pending_confirmation(confirmation_id: str) -> dict | None:
    """تاییدیه در انتظار را حذف کن (بعد از تایید یا رد)؛ اگر نبود None برگردان."""
    with db.lock:
        record = get_pending_confirmation(confirmation_id)
        if record is None:
            return None
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM pending_confirmations WHERE confirmation_id = ?",
                (confirmation_id.strip().upper(),),
            )
        return record


# --- حکم کار ---
def add_work_order(request_id: str, shop: str, parts: str) -> dict:
    """یک حکم کار برای یک درخواست تاییدشده ثبت کن."""
    with db.lock:
        request = get_request(request_id)
        record = {
            "tracking": next_tracking("WO"),
            "request_id": request_id.strip().upper(),
            "plate": request["plate"] if request else "",
            "shop": shop,
            "parts": parts,
            "status": "ثبت شده",
        }
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO work_orders (tracking, request_id, plate, shop, parts, status)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (record["tracking"], record["request_id"], record["plate"],
                 record["shop"], record["parts"], record["status"]),
            )
        return record


def get_work_order(tracking: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM work_orders WHERE tracking = ?", (tracking.strip().upper(),)
        ).fetchone()
    return _record(row) if row is not None else None


def list_work_orders() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM work_orders ORDER BY rowid").fetchall()
    return [_record(r) for r in rows]
