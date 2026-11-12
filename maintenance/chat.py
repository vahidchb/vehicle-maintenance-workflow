"""حلقه اصلی چت — چت‌بات نگهداری و تعمیرات تجهیزات خودرویی.
اگر گیج شدی، اول docs/LEARN_FA.md را بخوان.

جریان هر پیام کاربر:
1. توکن‌ها را بشمار، اگر زیاد بود compaction کن.
2. پیام را به مدل بده؛ مدل از حرف کاربر می‌فهمد در کدام مرحله
   workflow هستیم و ابزار مناسب را صدا می‌زند.
3. نتیجه ابزار (با شماره رهگیری) را برگردان به مدل.
4. جواب نهایی را نشان بده.
"""
from . import config
from .llm import ask
from .memory import count_messages_tokens, needs_compaction, compact_messages
from .tools import TOOLS, run_tool

SYSTEM_PROMPT = """تو چت‌بات نگهداری و تعمیرات تجهیزات خودرویی هستی. کوتاه، واضح و به فارسی جواب بده.

روال کار (workflow) به ترتیب این است و ترتیب را رعایت کن:
1. ثبت تجهیز با شماره پلاک
2. ثبت بازدید بر اساس زیرمجموعه (موتور، چرخ و...)
3. ثبت ارزیابی (می‌تواند بدون خرابی باشد)
4. ثبت خرابی برای یک ارزیابی
5. ثبت درخواست تعمیراتی که خرابی در آن هست
6. تایید درخواست
7. ثبت حکم کار (تعمیرگاه + قطعات مورد نیاز) — فقط بعد از تایید درخواست

از حرف کاربر بفهم در کدام مرحله هستیم و قدم بعدی را خودت انجام بده؛
مثلا اگر گفت «فلان خودرو فلان خرابی دارد»، اول خودرو را جستجو کن،
بعد ارزیابی ثبت کن، بعد خرابی را برایش ثبت کن.
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
        answer = chat_one_turn(messages)
        print(f"\nبات: {answer}")
        print(f"[توکن‌ها: {count_messages_tokens(messages)} / {config.MAX_TOKENS}]")


def chat_one_turn(messages: list[dict]) -> str:
    """یک پیام کاربر را جواب بده؛ ابزار را هم در همین تابع مدیریت کن."""
    for _ in range(3):  # حداکثر 3 بار ابزار
        response = ask(messages, tools=TOOLS)
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        # اگر مدل ابزار نخواست، جواب نهایی همین است
        if not msg.tool_calls:
            return msg.content or ""

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

    return "متاسفم، نتوانستم جواب کامل بدهم."
