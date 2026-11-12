"""حافظه رکوردها — همه‌چیز فقط در حافظه (RAM) نگه داشته می‌شود.

دیتابیس نداریم: رکوردها دیکشنری‌های ساده پایتون هستند.
با خاموش شدن برنامه، رکوردها پاک می‌شوند (عمداً ساده نگه داشته شده).

هر رکورد یک شماره رهگیری دارد: EQ-001 ، INSP-001 ، EV-001 ،
FLT-001 ، REQ-001 ، WO-001
"""
# --- جدول‌ها: دیکشنری ساده، کلید = شماره رهگیری (تجهیز: پلاک) ---
vehicles: dict[str, dict] = {}
inspections: dict[str, dict] = {}
evaluations: dict[str, dict] = {}
faults: dict[str, dict] = {}
requests: dict[str, dict] = {}
work_orders: dict[str, dict] = {}
# تاییدیه‌های در انتظار: درخواست تعمیراتی آماده شده ولی هنوز ثبت نشده؛
# کاربر باید اول تجهیز و خرابی را در پنجره تایید، تایید یا رد کند.
pending_confirmations: dict[str, dict] = {}

# شمارنده هر پیشوند، برای ساختن شماره رهگیری
_counters: dict[str, int] = {}


def next_tracking(prefix: str) -> str:
    """شماره رهگیری بعدی را بساز، مثلا EQ-001."""
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}-{_counters[prefix]:03d}"


def reset() -> None:
    """همه رکوردها و شمارنده‌ها را پاک کن (برای تست)."""
    vehicles.clear()
    inspections.clear()
    evaluations.clear()
    faults.clear()
    requests.clear()
    work_orders.clear()
    pending_confirmations.clear()
    _counters.clear()


# --- تجهیز (خودرو) ---
def add_vehicle(plate: str, name: str, kind: str = "") -> dict:
    """یک تجهیز/خودرو با شماره پلاک ثبت کن."""
    plate = plate.strip()
    record = {
        "tracking": next_tracking("EQ"),
        "plate": plate,
        "name": name,
        "kind": kind,
    }
    vehicles[plate] = record
    return record


def get_vehicle(plate: str) -> dict | None:
    """خودرو را با پلاک پیدا کن."""
    return vehicles.get(plate.strip())


def list_vehicles() -> list[dict]:
    """همه تجهیزها را برگردان."""
    return list(vehicles.values())


# --- بازدید ---
def add_inspection(plate: str, subsystem: str, note: str = "") -> dict:
    """یک بازدید برای یک خودرو ثبت کن."""
    record = {
        "tracking": next_tracking("INSP"),
        "plate": plate.strip(),
        "subsystem": subsystem,
        "note": note,
    }
    inspections[record["tracking"]] = record
    return record


def get_inspection(tracking: str) -> dict | None:
    return inspections.get(tracking.strip().upper())


def list_inspections() -> list[dict]:
    return list(inspections.values())


# --- ارزیابی (می‌تواند بدون خرابی باشد) ---
def add_evaluation(plate: str, inspection_id: str, summary: str) -> dict:
    """یک ارزیابی برای یک بازدید ثبت کن."""
    record = {
        "tracking": next_tracking("EV"),
        "plate": plate.strip(),
        "inspection_id": inspection_id.strip().upper(),
        "summary": summary,
    }
    evaluations[record["tracking"]] = record
    return record


def get_evaluation(tracking: str) -> dict | None:
    return evaluations.get(tracking.strip().upper())


def list_evaluations() -> list[dict]:
    return list(evaluations.values())


# --- خرابی (قدم جدا، وصل به یک ارزیابی) ---
def add_fault(evaluation_id: str, description: str, subsystem: str = "") -> dict:
    """یک خرابی برای یک ارزیابی ثبت کن."""
    evaluation = get_evaluation(evaluation_id)
    record = {
        "tracking": next_tracking("FLT"),
        "evaluation_id": evaluation_id.strip().upper(),
        "plate": evaluation["plate"] if evaluation else "",
        "description": description,
        "subsystem": subsystem,
    }
    faults[record["tracking"]] = record
    return record


def get_fault(tracking: str) -> dict | None:
    return faults.get(tracking.strip().upper())


def list_faults() -> list[dict]:
    return list(faults.values())


def faults_for_evaluation(evaluation_id: str) -> list[dict]:
    """خرابی‌های یک ارزیابی را برگردان."""
    key = evaluation_id.strip().upper()
    return [f for f in faults.values() if f["evaluation_id"] == key]


# --- درخواست تعمیراتی ---
def add_repair_request(evaluation_id: str, fault_id: str, description: str) -> dict:
    """یک درخواست تعمیراتی ثبت کن؛ وضعیت اول: در انتظار تایید."""
    evaluation = get_evaluation(evaluation_id)
    record = {
        "tracking": next_tracking("REQ"),
        "evaluation_id": evaluation_id.strip().upper(),
        "fault_id": fault_id.strip().upper() if fault_id else "",
        "plate": evaluation["plate"] if evaluation else "",
        "description": description,
        "status": "در انتظار تایید",
    }
    requests[record["tracking"]] = record
    return record


def get_request(tracking: str) -> dict | None:
    return requests.get(tracking.strip().upper())


def list_requests() -> list[dict]:
    return list(requests.values())


def approve_request(tracking: str) -> dict | None:
    """درخواست را تایید کن؛ اگر نبود None برگردان."""
    record = get_request(tracking)
    if record is None:
        return None
    record["status"] = "تایید شده"
    return record


# --- تاییدیه در انتظار (قبل از ثبت درخواست تعمیراتی) ---
def add_pending_confirmation(plate: str, equipment_name: str, evaluation_id: str,
                             fault_id: str, fault_description: str,
                             description: str = "") -> dict:
    """یک درخواست تعمیراتی آماده کن که هنوز ثبت نشده و منتظر تایید کاربر است."""
    record = {
        "confirmation_id": next_tracking("CONF"),
        "plate": plate.strip(),
        "equipment": equipment_name,
        "evaluation_id": evaluation_id.strip().upper(),
        "fault_id": fault_id.strip().upper() if fault_id else "",
        "fault": fault_description,
        "description": description,
    }
    pending_confirmations[record["confirmation_id"]] = record
    return record


def get_pending_confirmation(confirmation_id: str) -> dict | None:
    """تاییدیه در انتظار را با شماره‌اش پیدا کن."""
    return pending_confirmations.get(confirmation_id.strip().upper())


def list_pending_confirmations() -> list[dict]:
    """همه تاییدیه‌های در انتظار را برگردان."""
    return list(pending_confirmations.values())


def remove_pending_confirmation(confirmation_id: str) -> dict | None:
    """تاییدیه در انتظار را حذف کن (بعد از تایید یا رد)؛ اگر نبود None برگردان."""
    return pending_confirmations.pop(confirmation_id.strip().upper(), None)


# --- حکم کار ---
def add_work_order(request_id: str, shop: str, parts: str) -> dict:
    """یک حکم کار برای یک درخواست تاییدشده ثبت کن."""
    request = get_request(request_id)
    record = {
        "tracking": next_tracking("WO"),
        "request_id": request_id.strip().upper(),
        "plate": request["plate"] if request else "",
        "shop": shop,
        "parts": parts,
        "status": "ثبت شده",
    }
    work_orders[record["tracking"]] = record
    return record


def get_work_order(tracking: str) -> dict | None:
    return work_orders.get(tracking.strip().upper())


def list_work_orders() -> list[dict]:
    return list(work_orders.values())
