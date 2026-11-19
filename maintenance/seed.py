"""داده نمایشی (seed) — چون هنوز دیتابیس نداریم.

وقتی برنامه اجرا می‌شود (API یا ترمینال)، این داده‌ها یک بار در حافظه
ساخته می‌شوند تا گاراژ و گریدها خالی نباشند و کاربر بتواند سیستم را ببیند.

نکته مهم: داده‌ها با همان قدم‌های workflow ساخته می‌شوند
(ثبت تجهیز، بازدید، ارزیابی، خرابی، درخواست، تایید، حکم کار)،
نه با نوشتن مستقیم در دیکشنری‌های store؛ پس ترتیب و شماره رهگیری‌ها
درست می‌مانند و درخواست‌ها REQ واقعی هستند (نه تاییدیه در انتظار).
"""
from . import store, workflow


def _check(result: dict, step: str) -> str:
    """اگر قدم workflow موفق نبود، خطا بده؛ وگرنه شماره رهگیری را برگردان."""
    if not result.get("ok"):
        raise RuntimeError(f"seed خراب شد در قدم «{step}»: {result.get('message')}")
    return result["tracking"]


def _register_repair_request(evaluation_id: str, fault_id: str, description: str = "") -> str:
    """درخواست تعمیراتی را مثل کاربر واقعی بساز: اول تاییدیه، بعد تایید آن.

    register_repair_request_step فقط تاییدیه در انتظار می‌سازد؛
    confirm_repair_request_step آن را تایید می‌کند تا درخواست واقعی (REQ) ثبت شود.
    """
    pending = workflow.register_repair_request_step(evaluation_id, fault_id, description)
    if not pending.get("ok"):
        raise RuntimeError(f"seed خراب شد در ساخت تاییدیه درخواست: {pending.get('message')}")
    confirmed = workflow.confirm_repair_request_step(pending["confirmation_id"], True)
    return _check(confirmed, "تایید درخواست تعمیراتی")


def seed_demo_data() -> bool:
    """داده نمایشی را بساز و True برگردان.

    اگر قبلاً تجهیز ثبت شده باشد (یعنی داده هست)، چیزی نمی‌سازد و False
    برمی‌گرداند؛ پس صدا زدن دوباره‌اش هیچ رکورد تکراری نمی‌سازد.
    """
    # اگر تجهیز ثبت شده، یعنی داده هست؛ seed نکن
    if store.list_vehicles():
        return False

    # --- خودروی ۱: سمند LX با پلاک 123 ---
    _check(workflow.register_equipment_step("123", "سمند LX"), "ثبت تجهیز سمند")

    # بازدید ۱ (موتور) → ارزیابی → خرابی سیلندر
    insp1 = _check(
        workflow.register_inspection_step("123", "موتور", "بازدید دوره‌ای موتور"),
        "بازدید اول سمند",
    )
    ev1 = _check(
        workflow.register_evaluation_step("123", insp1, "سیلندر آسیب دیده است"),
        "ارزیابی اول سمند",
    )
    _check(workflow.register_fault_step(ev1, "خرابی سیلندر", "موتور"), "خرابی سیلندر")

    # بازدید ۲ (موتور) → ارزیابی → خرابی موتور
    insp2 = _check(
        workflow.register_inspection_step("123", "موتور", "بازدید دوم موتور"),
        "بازدید دوم سمند",
    )
    ev2 = _check(
        workflow.register_evaluation_step("123", insp2, "موتور خراب است"),
        "ارزیابی دوم سمند",
    )
    flt2 = _check(
        workflow.register_fault_step(ev2, "خرابی موتور", "موتور"), "خرابی موتور"
    )
    # درخواست تعمیراتی برای خرابی دوم (موتور)؛ تایید نمی‌شود
    # (وضعیت «در انتظار تایید» می‌ماند)
    _register_repair_request(ev2, flt2, "خرابی موتور")

    # --- خودروی ۲: پژو با پلاک 456 ---
    _check(workflow.register_equipment_step("456", "پژو"), "ثبت تجهیز پژو")

    # بازدید ۱ (موتور) → ارزیابی بدون خرابی (ارزیابی می‌تواند بدون خرابی باشد)
    insp3 = _check(
        workflow.register_inspection_step("456", "موتور", "بازدید دوره‌ای"),
        "بازدید اول پژو",
    )
    _check(
        workflow.register_evaluation_step("456", insp3, "خرابی مشاهده نشد"),
        "ارزیابی اول پژو",
    )

    # بازدید ۲ (چرخ) → ارزیابی → خرابی لاستیک
    insp4 = _check(
        workflow.register_inspection_step("456", "چرخ", "بازدید چرخ"),
        "بازدید دوم پژو",
    )
    ev4 = _check(
        workflow.register_evaluation_step("456", insp4, "لاستیک آسیب دیده است"),
        "ارزیابی دوم پژو",
    )
    flt4 = _check(
        workflow.register_fault_step(ev4, "خرابی لاستیک", "چرخ"), "خرابی لاستیک"
    )
    # درخواست تعمیراتی برای خرابی لاستیک، بعد تایید و حکم کار
    # (حکم کار فقط بعد از تایید درخواست ممکن است)
    req2 = _register_repair_request(ev4, flt4, "خرابی لاستیک")
    _check(workflow.approve_request_step(req2), "تایید درخواست پژو")
    _check(
        workflow.register_work_order_step(req2, "شهید همت", "لاستیک بارز"),
        "حکم کار پژو",
    )

    # --- خودروی ۳: پراید با پلاک 789 — فقط تجهیز، بدون هیچ سابقه‌ای ---
    _check(workflow.register_equipment_step("789", "پراید"), "ثبت تجهیز پراید")
    return True
