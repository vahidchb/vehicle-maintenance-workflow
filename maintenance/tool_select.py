"""انتخاب پویای ابزار — به مدل فقط ابزارهایی را بفرست که لازم دارد.

ایده (از وحید): به‌جای اینکه هر بار همه ۱۴ ابزار (~۲۶۰۰ توکن) را
بفرستیم، فقط ابزارهای مربوط به «درخواست فعلی» را می‌فرستیم.
انتخاب قطعی (deterministic) است — فراخوانی اضافه‌ای به مدل نیست
و با فلسفه workflow صریح این پروژه جور است.

ابزارها سه دسته‌اند:
1. همیشه‌روشن (core): از هر حالتی معتبرند — جستجوی خودرو،
   ثبت تجهیز، سرچ مقاله، خواندن مقاله، گزارش.
2. جستجوهای فقط‌خواندنی: درخواست و ارزیابی و حکم کار — ارزان‌اند
   و از هر مرحله‌ای معتبرند.
3. ابزار مرحله: فقط ابزار قدم بعدی خودروی فعال، از روی
   workflow.current_stage(plate) — مثلا اگر خودرو ثبت شده و
   بازدید ندارد، فقط register_inspection اضافه می‌شود.

خودروی فعال (active_plate) دو منبع دارد:
- سشن: پلاکی که در دورهای قبلی با آن کار شده (در session_memory).
- پیام فعلی کاربر: اگر پلاک ثبت‌شده‌ای در آن باشد، همان برنده است
  (کاربر وسط مکالمه خودرو را عوض کرده).

کلید قطع (kill-switch): اگر TOOL_SELECTION=off باشد (در .env)،
انتخاب خاموش می‌شود و همه ابزارها فرستاده می‌شوند — برای اینکه
بشود با/بدون انتخاب را با هم مقایسه کرد (A/B).
"""
import json

from . import config, store, workflow
from .tools import TOOLS

# --- دسته‌های ابزار (با اسم؛ ترتیب نهایی همان ترتیب TOOLS است) ---

# همیشه‌روشن: از هر حالتی معتبرند.
CORE_TOOLS = [
    "search_vehicle",
    "register_equipment",
    "search_articles",
    "read_article",
    "run_report",
]

# جستجوهای فقط‌خواندنی: ارزان و از هر مرحله‌ای معتبرند.
SEARCH_TOOLS = [
    "search_repair_request",
    "search_evaluation",
    "search_work_order",
]

# ابزار قدم بعدی، بر اساس مرحله فعلی خودرو (کلید current_stage).
# مرحله evaluation دو حالت دارد (بازدید بدون ارزیابی / ارزیابی بدون
# خرابی) و در تابع stage_tools جدا حساب می‌شود، پس اینجا نیست.
_STAGE_TOOLS = {
    "equipment": [],  # خودرو هنوز ثبت نشده؛ register_equipment در core هست
    "inspection": ["register_inspection"],
    "fault": ["register_repair_request"],
    "repair_request": ["approve_request"],
    "approval": ["register_work_order"],
    "work_order": ["register_inspection"],  # روال کامل شده؛ چرخه جدید
}

# ارقام فارسی و عربی به لاتین — کاربر پلاک را با ارقام فارسی می‌نویسد
# ولی پلاک در دیتابیس با ارقام لاتین ذخیره شده؛ برای اینکه پیدا شود،
# موقع مقایسه هر دو را به لاتین برمی‌گردانیم.
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_digits(text: str) -> str:
    """ارقام فارسی/عربی متن را به لاتین برگردان."""
    return str(text or "").translate(_DIGITS)


def _registered_plates() -> list[str]:
    """پلاک همه خودروهای ثبت‌شده را برگردان."""
    return [v["plate"] for v in store.list_vehicles()]


def detect_plate(text: str, plates: list[str] | None = None) -> str | None:
    """اگر پلاک ثبت‌شده‌ای در متن باشد، همان را برگردان؛ وگرنه None.

    مقایسه با تطابق زیررشته (substring) است؛ اگر چند پلاک پیدا شد،
    بلندترین برنده است (تا پلاک کوتاه‌تر اشتباهی انتخاب نشود).
    پلاک‌های تک‌حرفی نادیده گرفته می‌شوند (همه‌جا پیدا می‌شوند).
    """
    if plates is None:
        plates = _registered_plates()
    normalized = normalize_digits(text)
    best: str | None = None
    for plate in plates:
        plate = (plate or "").strip()
        if len(plate) < 2:
            continue
        if normalize_digits(plate) in normalized:
            if best is None or len(plate) > len(best):
                best = plate
    return best


def plate_from_tool_call(name: str, arguments: str, result: str = "") -> str | None:
    """پلاک خودروی یک فراخوانی ابزار را پیدا کن؛ اگر نبود None.

    ترتیب جستجو:
    1. آرگومان plate (ابزارهای ثبت و گزارش).
    2. evaluation_id یا request_id در آرگومان‌ها (از دیتابیس پلاک را بگیر).
    3. پلاک در متن query یا نتیجه ابزار (مثلا جستجو با نام خودرو،
       که پلاک در جوابش می‌آید).
    """
    try:
        args = json.loads(arguments or "{}")
    except ValueError:
        args = {}
    if not isinstance(args, dict):
        args = {}

    plate = (args.get("plate") or "").strip()
    if plate:
        return plate

    evaluation_id = (args.get("evaluation_id") or "").strip()
    if evaluation_id:
        evaluation = store.get_evaluation(evaluation_id)
        if evaluation is not None:
            return evaluation["plate"]

    request_id = (args.get("request_id") or "").strip()
    if request_id:
        request = store.get_request(request_id)
        if request is not None:
            return request["plate"]

    plates = _registered_plates()
    query = args.get("query") or ""
    found = detect_plate(query, plates)
    if found is not None:
        return found
    return detect_plate(result, plates)


def _evaluation_stage_tools(plate: str) -> list[str]:
    """ابزار مرحله evaluation: بستگی دارد بازدید بی‌ارزیابی هست یا نه.

    - اگر بازدیدی هست که هنوز ارزیابی ندارد → register_evaluation.
    - اگر ارزیابی‌ای هست (و هنوز خرابی ندارد) → register_fault.
    هر دو می‌توانند هم‌زمان درست باشند (بازدید جدید + ارزیابی قدیمی).
    """
    tools: list[str] = []
    evaluations = [e for e in store.list_evaluations() if e["plate"] == plate]
    evaluated = {e["inspection_id"] for e in evaluations}
    inspections = [i for i in store.list_inspections() if i["plate"] == plate]
    if any(i["tracking"] not in evaluated for i in inspections):
        tools.append("register_evaluation")
    if evaluations:
        tools.append("register_fault")
    return tools


def stage_tools(plate: str) -> list[str]:
    """ابزار قدم بعدی یک خودرو را از روی مرحله فعلی‌اش برگردان."""
    stage_key = workflow.current_stage(plate)["stage_key"]
    if stage_key == "evaluation":
        return _evaluation_stage_tools(plate)
    return list(_STAGE_TOOLS.get(stage_key, []))


def select_tools(messages: list[dict], active_plate: str | None = None) -> list[dict]:
    """زیرمجموعه ابزارهای یک فراخوانی به مدل را برگردان.

    messages: مکالمه تا این لحظه (پلاک از آخرین پیام کاربر خوانده می‌شود).
    active_plate: پلاک خودروی فعلی سشن (از session_memory).

    اگر پلاکی در پیام کاربر باشد، همان برنده است (تعویض خودرو وسط
    مکالمه)؛ وگرنه پلاک سشن؛ اگر هیچ پلاکی نبود، فقط core + جستجوها.
    اگر TOOL_SELECTION=off باشد، همه ابزارها برگردانده می‌شوند.
    """
    if str(config.TOOL_SELECTION).strip().lower() in ("off", "0", "false", "no"):
        return list(TOOLS)

    names: set[str] = set(CORE_TOOLS) | set(SEARCH_TOOLS)

    # پلاک را اول از آخرین پیام کاربر بگیر (تعویض خودرو)، بعد از سشن.
    user_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            user_text = message.get("content") or ""
            break
    plate = detect_plate(user_text) or (active_plate or "").strip() or None
    if plate is not None and store.get_vehicle(plate) is not None:
        names.update(stage_tools(plate))

    # ترتیب نهایی همان ترتیب TOOLS است تا خروجی پایدار باشد.
    return [tool for tool in TOOLS if tool["function"]["name"] in names]


def tool_names(tools: list[dict]) -> list[str]:
    """اسم ابزارهای یک لیست را برگردان (برای تست و لاگ)."""
    return [tool["function"]["name"] for tool in tools]
