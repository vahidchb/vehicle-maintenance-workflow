"""Workflow صریح نگهداری و تعمیرات — قلب این پروژه.

فرق این فایل با tool calling ساده چیست؟
در tool calling، مدل خودش تصمیم می‌گیرد چه ابزاری صدا بزند.
اینجا ترتیب قدم‌ها را «ما» تعیین کرده‌ایم و هر قدم، قدم قبلی را
چک می‌کند. اگر قدم قبلی انجام نشده باشد، قدم بعدی اجرا نمی‌شود
و پیام می‌گوید کدام مرحله جا مانده است.

مراحل (هر مرحله یک شماره رهگیری می‌دهد):
1. ثبت تجهیز (EQ) → 2. ثبت بازدید (INSP) → 3. ثبت ارزیابی (EV)
→ 4. ثبت خرابی (FLT، اختیاری) → 5. درخواست تعمیراتی (REQ)
→ 6. تایید درخواست → 7. حکم کار (WO)

بدون هیچ فریم‌ورکی؛ فقط تابع‌های ساده پایتون.
"""
from . import store

# مراحل workflow، به ترتیب. هر مرحله: کلید، نام فارسی، توضیح
WORKFLOW_STAGES = [
    {"key": "equipment", "name": "ثبت تجهیز", "prefix": "EQ",
     "description": "خودرو با شماره پلاک وارد سیستم می‌شود."},
    {"key": "inspection", "name": "ثبت بازدید", "prefix": "INSP",
     "description": "بازدید بر اساس زیرمجموعه‌ها، مثل موتور و چرخ."},
    {"key": "evaluation", "name": "ثبت ارزیابی", "prefix": "EV",
     "description": "ارزیابی بازدید؛ می‌تواند بدون خرابی باشد."},
    {"key": "fault", "name": "ثبت خرابی", "prefix": "FLT",
     "description": "خرابی مشاهده‌شده، وصل به یک ارزیابی. (اختیاری)"},
    {"key": "repair_request", "name": "ثبت درخواست تعمیراتی", "prefix": "REQ",
     "description": "درخواست تعمیراتی که خرابی در آن هست."},
    {"key": "approval", "name": "تایید درخواست", "prefix": "REQ",
     "description": "کاربر درخواست تعمیراتی را تایید می‌کند."},
    {"key": "work_order", "name": "ثبت حکم کار", "prefix": "WO",
     "description": "حکم کار با تعمیرگاه و قطعات مورد نیاز."},
]

# نتیجه هر قدم: موفق بود؟ شماره رهگیری؟ پیام فارسی؟
# {"ok": True/False, "tracking": "...", "message": "..."}


def current_stage(plate: str) -> dict:
    """بگو یک خودرو الان در کدام مرحله workflow است و قدم بعدی چیست."""
    plate = plate.strip()
    vehicle = store.get_vehicle(plate)
    if vehicle is None:
        return {"stage_key": "equipment", "stage_name": "ثبت تجهیز",
                "next_step": "اول تجهیز (خودرو) را با شماره پلاک ثبت کن."}

    plate_inspections = [i for i in store.list_inspections() if i["plate"] == plate]
    if not plate_inspections:
        return {"stage_key": "inspection", "stage_name": "ثبت بازدید",
                "next_step": "برای این خودرو یک بازدید ثبت کن (مثلا موتور یا چرخ)."}

    plate_evaluations = [e for e in store.list_evaluations() if e["plate"] == plate]
    if not plate_evaluations:
        return {"stage_key": "evaluation", "stage_name": "ثبت ارزیابی",
                "next_step": "برای بازدید این خودرو یک ارزیابی ثبت کن."}

    plate_faults = [f for f in store.list_faults() if f["plate"] == plate]
    plate_requests = [r for r in store.list_requests() if r["plate"] == plate]
    if not plate_faults and not plate_requests:
        return {"stage_key": "evaluation", "stage_name": "ثبت ارزیابی",
                "next_step": "ارزیابی ثبت شده. اگر خرابی هست، ثبت خرابی کن؛ "
                             "وگرنه روال همین‌جا کامل است."}
    if plate_faults and not plate_requests:
        return {"stage_key": "fault", "stage_name": "ثبت خرابی",
                "next_step": "برای این خرابی یک درخواست تعمیراتی ثبت کن."}

    latest_request = plate_requests[-1]
    if latest_request["status"] != "تایید شده":
        return {"stage_key": "repair_request", "stage_name": "ثبت درخواست تعمیراتی",
                "next_step": f"درخواست {latest_request['tracking']} در انتظار تایید است؛ "
                             "آن را تایید کن."}

    plate_orders = [w for w in store.list_work_orders() if w["plate"] == plate]
    if not plate_orders:
        return {"stage_key": "approval", "stage_name": "تایید درخواست",
                "next_step": f"درخواست {latest_request['tracking']} تایید شده؛ "
                             "حالا حکم کار را ثبت کن (تعمیرگاه + قطعات)."}
    return {"stage_key": "work_order", "stage_name": "ثبت حکم کار",
            "next_step": "روال کامل شد؛ حکم کار ثبت شده است."}


def register_equipment_step(plate: str, name: str, kind: str = "") -> dict:
    """قدم 1: تجهیز را با پلاک ثبت کن."""
    existing = store.get_vehicle(plate)
    if existing is not None:
        return {"ok": True, "tracking": existing["tracking"],
                "message": f"این خودرو قبلاً ثبت شده است. شماره رهگیری: {existing['tracking']}\n"
                           "مرحله بعدی: ثبت بازدید"}
    record = store.add_vehicle(plate, name, kind)
    return {"ok": True, "tracking": record["tracking"],
            "message": f"تجهیز ثبت شد. شماره رهگیری: {record['tracking']}\n"
                       "مرحله بعدی: ثبت بازدید"}


def register_inspection_step(plate: str, subsystem: str, note: str = "") -> dict:
    """قدم 2: بازدید ثبت کن؛ اول باید تجهیز ثبت شده باشد."""
    if store.get_vehicle(plate) is None:
        return {"ok": False, "tracking": None,
                "message": "نمی‌توانم بازدید ثبت کنم؛ مرحله «ثبت تجهیز» هنوز انجام نشده است. "
                           "اول خودرو را با شماره پلاک ثبت کن."}
    record = store.add_inspection(plate, subsystem, note)
    return {"ok": True, "tracking": record["tracking"],
            "message": f"بازدید ثبت شد. شماره رهگیری: {record['tracking']}\n"
                       "مرحله بعدی: ثبت ارزیابی"}


def register_evaluation_step(plate: str, inspection_id: str, summary: str) -> dict:
    """قدم 3: ارزیابی ثبت کن؛ اول باید بازدید ثبت شده باشد."""
    inspection = store.get_inspection(inspection_id)
    if inspection is None:
        return {"ok": False, "tracking": None,
                "message": "نمی‌توانم ارزیابی ثبت کنم؛ مرحله «ثبت بازدید» هنوز انجام نشده است. "
                           f"بازدیدی با شماره {inspection_id} پیدا نشد."}
    record = store.add_evaluation(plate, inspection_id, summary)
    return {"ok": True, "tracking": record["tracking"],
            "message": f"ارزیابی ثبت شد. شماره رهگیری: {record['tracking']}\n"
                       "مرحله بعدی: اگر خرابی هست، ثبت خرابی کن؛ وگرنه روال همین‌جا کامل است."}


def register_fault_step(evaluation_id: str, description: str, subsystem: str = "") -> dict:
    """قدم 4: خرابی ثبت کن؛ اول باید ارزیابی ثبت شده باشد."""
    if store.get_evaluation(evaluation_id) is None:
        return {"ok": False, "tracking": None,
                "message": "نمی‌توانم خرابی ثبت کنم؛ مرحله «ثبت ارزیابی» هنوز انجام نشده است. "
                           f"ارزیابی‌ای با شماره {evaluation_id} پیدا نشد."}
    record = store.add_fault(evaluation_id, description, subsystem)
    return {"ok": True, "tracking": record["tracking"],
            "message": f"خرابی ثبت شد. شماره رهگیری: {record['tracking']}\n"
                       "مرحله بعدی: ثبت درخواست تعمیراتی"}


def register_repair_request_step(evaluation_id: str, fault_id: str = "",
                                 description: str = "") -> dict:
    """قدم 5: درخواست تعمیراتی ثبت کن؛ اول باید ارزیابی ثبت شده باشد."""
    if store.get_evaluation(evaluation_id) is None:
        return {"ok": False, "tracking": None,
                "message": "نمی‌توانم درخواست ثبت کنم؛ مرحله «ثبت ارزیابی» هنوز انجام نشده است. "
                           f"ارزیابی‌ای با شماره {evaluation_id} پیدا نشد."}
    if fault_id:
        fault = store.get_fault(fault_id)
        if fault is None or fault["evaluation_id"] != evaluation_id.strip().upper():
            return {"ok": False, "tracking": None,
                    "message": f"خرابی‌ای با شماره {fault_id} برای این ارزیابی پیدا نشد."}
    else:
        # اگر خرابی گفته نشد ولی ارزیابی خرابی دارد، آخرین خرابی را وصل کن.
        faults = store.faults_for_evaluation(evaluation_id)
        if faults:
            fault_id = faults[-1]["tracking"]
    record = store.add_repair_request(evaluation_id, fault_id, description)
    return {"ok": True, "tracking": record["tracking"],
            "message": f"درخواست تعمیراتی ثبت شد. شماره رهگیری: {record['tracking']}\n"
                       "مرحله بعدی: تایید درخواست"}


def approve_request_step(request_id: str) -> dict:
    """قدم 6: درخواست تعمیراتی را تایید کن."""
    request = store.get_request(request_id)
    if request is None:
        return {"ok": False, "tracking": None,
                "message": f"درخواستی با شماره {request_id} پیدا نشد؛ "
                           "اول مرحله «ثبت درخواست تعمیراتی» را انجام بده."}
    if request["status"] == "تایید شده":
        return {"ok": False, "tracking": request["tracking"],
                "message": f"درخواست {request['tracking']} قبلاً تایید شده است.\n"
                           "مرحله بعدی: ثبت حکم کار"}
    store.approve_request(request_id)
    return {"ok": True, "tracking": request["tracking"],
            "message": f"درخواست {request['tracking']} تایید شد.\n"
                       "مرحله بعدی: ثبت حکم کار (تعمیرگاه + قطعات مورد نیاز)"}


def register_work_order_step(request_id: str, shop: str, parts: str) -> dict:
    """قدم 7: حکم کار ثبت کن؛ اول باید درخواست تایید شده باشد."""
    request = store.get_request(request_id)
    if request is None:
        return {"ok": False, "tracking": None,
                "message": f"درخواستی با شماره {request_id} پیدا نشد؛ "
                           "اول مرحله «ثبت درخواست تعمیراتی» را انجام بده."}
    if request["status"] != "تایید شده":
        return {"ok": False, "tracking": None,
                "message": f"نمی‌توانم حکم کار ثبت کنم؛ درخواست {request['tracking']} "
                           "هنوز تایید نشده است. اول مرحله «تایید درخواست» را انجام بده."}
    record = store.add_work_order(request_id, shop, parts)
    return {"ok": True, "tracking": record["tracking"],
            "message": f"حکم کار ثبت شد. شماره رهگیری: {record['tracking']}\n"
                       "روال کامل شد."}
