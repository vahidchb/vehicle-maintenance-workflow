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
5. ثبت درخواست تعمیراتی که خرابی در آن هست — قبل از ثبت، پنجره تایید برای کاربر باز می‌شود
6. تایید درخواست
7. ثبت حکم کار (تعمیرگاه + قطعات مورد نیاز) — فقط بعد از تایید درخواست

از حرف کاربر بفهم در کدام مرحله هستیم و قدم بعدی را خودت انجام بده؛
مثلا اگر گفت «فلان خودرو فلان خرابی دارد»، اول خودرو را جستجو کن،
بعد ارزیابی ثبت کن، بعد خرابی را برایش ثبت کن.

ثبت خرابی: شرح کوتاه کاربر کافی است؛ همان را ثبت کن.
هرگز علت خرابی، جزئیات یا دلیلش را نپرس. زیرمجموعه اختیاری است؛
اگر کاربر کلمه‌ای مثل موتور یا چرخ گفت همان را بگذار، وگرنه خالی بگذار.

درخواست تعمیراتی: وقتی آماده شد، به کاربر بگو پنجره تایید باز می‌شود
تا تجهیز و خرابی را ببیند و تایید یا رد کند؛ شماره رهگیری را فقط بعد از تایید می‌گیرد.

در هر مرحله شماره رهگیری را به کاربر بده.
اگر کاربر لیست چیزی را خواست (مثلا لیست ارزیابی‌ها)، بگو گرید آن را نشان می‌دهد و خلاصه‌اش را بگو.
اگر کاربر درباره یک قطعه یا جزء خودرو سوال کرد، با search_articles مقاله پیدا کن
و با read_article متنش را بخوان و نشان بده.
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

    return {"reply": "متاسفم، نتوانستم جواب کامل بدهم.",
            "pending_confirmation": _new_confirmation(seen_ids)}
