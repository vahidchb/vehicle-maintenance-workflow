"""حلقه اصلی چت — چت‌بات نگهداری و تعمیرات تجهیزات خودرویی.
اگر گیج شدی، اول docs/LEARN_FA.md را بخوان.

جریان هر پیام کاربر:
1. توکن‌ها را بشمار، اگر زیاد بود compaction کن.
2. پیام را به مدل بده؛ مدل از حرف کاربر می‌فهمد در کدام مرحله
   workflow هستیم و ابزار مناسب را صدا می‌زند.
3. نتیجه ابزار (با شماره رهگیری) را برگردان به مدل.
4. جواب نهایی را نشان بده.
"""
from . import config, store, workflow
from .llm import ask
from .memory import count_messages_tokens, needs_compaction, compact_messages
from .tools import TOOLS, run_tool

SYSTEM_PROMPT = """تو چت‌بات نگهداری و تعمیرات تجهیزات خودرویی هستی. کوتاه، واضح و به فارسی جواب بده.

روال کار (workflow) به ترتیب این است و ترتیب را رعایت کن:
1. ثبت تجهیز با شماره پلاک
2. ثبت بازدید بر اساس زیرمجموعه (موتور، چرخ و...)
3. ثبت ارزیابی (می‌تواند بدون خرابی باشد)
4. ثبت خرابی برای یک ارزیابی
5. ثبت درخواست تعمیراتی که خرابی در آن هست — بعد از ثبت خرابی، پنجره تایید «خودکار» باز می‌شود
6. تایید درخواست
7. ثبت حکم کار (تعمیرگاه + قطعات مورد نیاز) — فقط بعد از تایید درخواست

از حرف کاربر بفهم در کدام مرحله هستیم و قدم بعدی را خودت انجام بده؛
مثلا اگر گفت «فلان خودرو فلان خرابی دارد»، اول خودرو را جستجو کن،
بعد ارزیابی ثبت کن، بعد خرابی را برایش ثبت کن.

بازدید و ارزیابی یک فرایند است: وقتی کاربر گفت «بازدید و ارزیابی»،
اول بازدید را ثبت کن و بعد ارزیابی را روی همان بازدید ثبت کن؛
زیرمجموعه را از حرف کاربر بگیر (مثلا موتور یا چرخ).

ثبت خرابی: شرح کوتاه کاربر کافی است؛ همان را ثبت کن.
هرگز علت خرابی، جزئیات یا دلیلش را نپرس. زیرمجموعه اختیاری است؛
اگر کاربر کلمه‌ای مثل موتور یا چرخ گفت همان را بگذار، وگرنه خالی بگذار.

درخواست تعمیراتی: بعد از ثبت خرابی، سیستم «خودکار» پنجره تایید را باز می‌کند؛
تو «این درخواست ثبت شود؟ (بله/خیر)» را نپرس و خودت ابزار register_repair_request را صدا نزن.
فقط به کاربر بگو پنجره تایید باز شده تا اول گزارش بازدید و بعد تجهیز و خرابی را ببیند
و آنجا تایید یا رد کند؛ شماره رهگیری را فقط بعد از تایید می‌گیرد.

در هر مرحله شماره رهگیری را به کاربر بده.
اگر کاربر لیست چیزی را خواست (مثلا لیست ارزیابی‌ها)، بگو گرید آن را نشان می‌دهد و خلاصه‌اش را بگو.
اگر کاربر درباره یک قطعه یا جزء خودرو سوال کرد، با search_articles مقاله پیدا کن
و با read_article متنش را بخوان و نشان بده.

دیتای اضافی: اگر کاربر موقع ثبت چیزی گفت که فیلد مشخصی ندارد
(مثلا موقع بازدید گفت «سطح روغن کم بود»)، همان‌جا در extra ذخیره‌اش کن:
{"سطح روغن": "کم"} — کلید و مقدار هر دو رشته کوتاه باشند؛ چیزهایی که
فیلد دارند (پلاک، زیرمجموعه و...) را در extra نگذار.

گزارش‌گیری: وقتی کاربر گزارش یا آمار خواست، ابزار run_report را صدا بزن.
اول گزارش آماده را امتحان کن:
- pending_approvals: درخواست‌های در انتظار تایید
- faults_by_vehicle: خرابی‌ها با وضعیت درخواست و حکم کار (plate اختیاری)
- faults_by_subsystem: تعداد خرابی هر زیرمجموعه
- work_orders_by_shop: تعداد حکم کار هر تعمیرگاه
- vehicle_history: سابقه کامل یک خودرو (plate لازم است)
فقط وقتی هیچ‌کدام جواب نداد، با sql یک کوئری SELECT بنویس (فقط خواندنی؛
INSERT و UPDATE و DELETE ممنوع است). ساختار دیتابیس:
equipment(tracking, plate, name, kind) | inspections(tracking, plate, subsystem, note)
evaluations(tracking, plate, inspection_id, summary) | faults(tracking, evaluation_id, plate, description, subsystem)
repair_requests(tracking, evaluation_id, fault_id, plate, description, status)
work_orders(tracking, request_id, plate, shop, parts, status)
هر جدول یک ستون extra_data (JSON) هم دارد؛ با json_extract(extra_data, '$.کلید') خوانده می‌شود.
"""


def run_chat() -> None:
    """چت ترمینالی را اجرا کن؛ با exit یا quit خارج شو."""
    missing = config.check_config()
    for msg in missing:
        print("⚠️", msg)
    if not config.LLM_API_KEY or not config.LLM_BASE_URL:
        print("اول فایل .env را کامل کن (راهنما در README است).")
        return

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("چت‌بات نگهداری و تعمیرات آماده است. برای خروج بنویس: exit")
    print("-" * 40)

    while True:
        user_text = input("\nتو: ").strip()
        if user_text.lower() in ("exit", "quit", "خروج"):
            print("خداحافظ!")
            break
        if not user_text:
            continue

        messages.append({"role": "user", "content": user_text})

        # 1) مدیریت توکن + compaction
        if needs_compaction(messages):
            print(f"[compaction] توکن‌ها زیاد شد ({count_messages_tokens(messages)})، خلاصه می‌کنم...")
            messages = compact_messages(messages)

        # 2) و 3) مدل + ابزار، حداکثر 3 دور
        result = chat_one_turn(messages)
        print(f"\nبات: {result['reply']}")

        # 4) اگر درخواست تعمیراتی آماده شد، در ترمینال از کاربر تایید بگیر
        pending = result["pending_confirmation"]
        if pending is not None:
            print("\n--- تایید درخواست تعمیراتی ---")
            inspection = pending.get("inspection")
            if inspection:
                print("گزارش بازدید:")
                print(f"  شماره رهگیری: {inspection['tracking']}")
                print(f"  زیرمجموعه: {inspection['subsystem']}")
                print(f"  توضیح: {inspection['note'] or '—'}")
            print(f"تجهیز: {pending['equipment']} (پلاک {pending['plate']})")
            print(f"خرابی: {pending['fault'] or '—'}")
            if pending["description"]:
                print(f"شرح: {pending['description']}")
            answer = input("این درخواست ثبت شود؟ (بله/خیر): ").strip()
            confirmed = answer in ("بله", "بلی", "آره", "yes", "y")
            outcome = workflow.confirm_repair_request_step(pending["confirmation_id"], confirmed)
            print(outcome["message"])
            # نتیجه تایید را به مکالمه اضافه کن تا مدل در دور بعدی بداند چه شد
            messages.append({"role": "system", "content": f"[نتیجه تایید درخواست تعمیراتی] {outcome['message']}"})

        print(f"[توکن‌ها: {count_messages_tokens(messages)} / {config.MAX_TOKENS}]")


def _new_confirmation(seen_ids: set[str]) -> dict | None:
    """تاییدیه در انتظاری که در همین دور چت ساخته شده را برگردان؛ اگر نبود None."""
    for pending in store.list_pending_confirmations():
        if pending["confirmation_id"] not in seen_ids:
            return dict(pending)
    return None


def _maybe_create_confirmation(fault: dict) -> dict | None:
    """برای یک خرابی، تاییدیه درخواست تعمیراتی بساز؛ اگر قبلاً درخواست یا
    تاییدیه‌ای برای این خرابی (یا این خودرو) هست، چیزی نساز و None برگردان."""
    fault_id = fault["tracking"]
    # اگر برای این خرابی قبلاً درخواست ثبت شده، تاییدیه جدید نساز
    if any(r["fault_id"] == fault_id for r in store.list_requests()):
        return None
    # اگر برای این خرابی یا این خودرو تاییدیه در انتظار هست، تکراری نساز
    if any(p["fault_id"] == fault_id or p["plate"] == fault["plate"]
           for p in store.list_pending_confirmations()):
        return None
    result = workflow.register_repair_request_step(fault["evaluation_id"], fault_id)
    if not result.get("ok"):
        return None
    return result.get("summary")


def _auto_create_confirmations(known_faults: set[str], known_inspections: set[str]) -> dict | None:
    """بعد از ثبت خرابی یا بازدید جدید، تاییدیه درخواست تعمیراتی را خودکار بساز
    تا مودال تایید بدون سوال اضافه باز شود.

    - خرابی جدید → تاییدیه برای همان خرابی.
    - بازدید جدید → اگر خودرو خرابی بدون درخواست دارد، تاییدیه برای آخرین آن خرابی.
    برمی‌گرداند: تاییدیه ساخته‌شده، یا None اگر چیزی ساخته نشد.
    """
    # 1) خرابی‌های جدید این دور
    for fault in store.list_faults():
        if fault["tracking"] not in known_faults:
            created = _maybe_create_confirmation(fault)
            if created is not None:
                return created
    # 2) بازدیدهای جدید این دور — فقط اگر خرابی بدون درخواست هست
    for inspection in store.list_inspections():
        if inspection["tracking"] in known_inspections:
            continue
        plate = inspection["plate"]
        open_faults = [
            f for f in store.list_faults()
            if f["plate"] == plate
            and not any(r["fault_id"] == f["tracking"] for r in store.list_requests())
            and not any(p["fault_id"] == f["tracking"] for p in store.list_pending_confirmations())
        ]
        if open_faults:
            created = _maybe_create_confirmation(open_faults[-1])
            if created is not None:
                return created
    return None


def chat_one_turn(messages: list[dict]) -> dict:
    """یک پیام کاربر را جواب بده؛ ابزار را هم در همین تابع مدیریت کن.

    برمی‌گرداند: {"reply": جواب نهایی، "pending_confirmation": تاییدیه در انتظار یا None}
    اگر در این دور، درخواست تعمیراتی آماده شده باشد، pending_confirmation پر است
    تا رابط کاربری پنجره تایید را نشان بدهد.
    """
    # تاییدیه‌های قبلی را نگه دار تا فقط تاییدیه «جدید» این دور را برگردانیم
    seen_ids = {p["confirmation_id"] for p in store.list_pending_confirmations()}

    for _ in range(3):  # حداکثر 3 بار ابزار
        response = ask(messages, tools=TOOLS)
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        # اگر مدل ابزار نخواست، جواب نهایی همین است
        if not msg.tool_calls:
            return {"reply": msg.content or "",
                    "pending_confirmation": _new_confirmation(seen_ids)}

        # اگر ابزار خواست، اجراش کن و نتیجه را به مکالمه اضافه کن
        # (رکوردهای قبل از اجرا را نگه دار تا خرابی/بازدید «جدید» این دور را بشناسیم)
        known_faults = {f["tracking"] for f in store.list_faults()}
        known_inspections = {i["tracking"] for i in store.list_inspections()}
        for call in msg.tool_calls:
            print(f"[tool] {call.function.name} را صدا می‌زنم...")
            result = run_tool(call.function.name, call.function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

        # تایید خودکار: بعد از ثبت خرابی یا بازدید جدید، اگر خرابی بدون
        # درخواست هست، تاییدیه را خودکار بساز تا مودال تایید باز شود
        created = _auto_create_confirmations(known_faults, known_inspections)
        if created is not None:
            messages.append({
                "role": "system",
                "content": "[تاییدیه خودکار] پنجره تایید درخواست تعمیراتی برای خرابی "
                           f"{created['fault_id']} باز شد؛ کاربر آنجا تایید یا رد می‌کند.",
            })

    return {"reply": "متاسفم، نتوانستم جواب کامل بدهم.",
            "pending_confirmation": _new_confirmation(seen_ids)}
