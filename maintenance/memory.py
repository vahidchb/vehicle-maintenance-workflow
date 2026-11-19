"""مدیریت توکن و compaction — حافظه مکالمه را سبک نگه دار.

ایده ساده است:
1. توکن‌ها را بشمار.
2. اگر از حد گذشت، پیام‌های قدیمی را خلاصه کن (compaction)
   و فقط خلاصه + چند پیام آخر را نگه دار.
"""
from . import config
from .llm import ask_text


def count_tokens(text: str) -> int:
    """تعداد توکن یک متن را تخمین بزن."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # اگر tiktoken نبود، تخمین ساده: هر 4 حرف ~ 1 توکن
        return max(1, len(text) // 4)


def count_messages_tokens(messages: list[dict]) -> int:
    """مجموع توکن‌های همه پیام‌ها را بشمار."""
    total = 0
    for msg in messages:
        total += count_tokens(str(msg.get("content", "")))
    return total


def needs_compaction(messages: list[dict]) -> bool:
    """آیا توکن‌ها از حد مجاز گذشته‌اند؟"""
    return count_messages_tokens(messages) > config.MAX_TOKENS


def summarize_text(text: str) -> str:
    """یک متن (معمولاً مکالمه قدیمی) را در 5 خط خلاصه کن.

    این همان یک فراخوانی به مدل است که compaction هم از آن استفاده می‌کند؛
    حافظه سشن (session_memory) هم خلاصه غلتانش را با همین تابع می‌سازد،
    پس فراخوانی اضافه‌ای به مدل اضافه نمی‌شود.
    """
    return ask_text(
        [
            {"role": "system", "content": "مکالمه زیر را در 5 خط خلاصه کن؛ نکات مهم را نگه دار."},
            {"role": "user", "content": text},
        ]
    )


def summarize_messages(messages: list[dict]) -> str:
    """لیست پیام‌ها را به متن تبدیل کن و خلاصه‌اش کن."""
    old_text = "\n".join(
        f"{m.get('role')}: {m.get('content') or ''}" for m in messages
    )
    return summarize_text(old_text)


def compact_messages(messages: list[dict]) -> list[dict]:
    """پیام‌های قدیمی را خلاصه کن و لیست جدید را برگردان.

    پیام system اول و چند پیام آخر سالم می‌مانند،
    بقیه در یک پیام خلاصه جمع می‌شوند.
    """
    if len(messages) <= config.KEEP_LAST_MESSAGES + 1:
        return messages

    keep = messages[-config.KEEP_LAST_MESSAGES:]
    old = messages[:-config.KEEP_LAST_MESSAGES]

    summary = summarize_messages(old)

    # پیام اول اگر system بود نگهش دار، بعد خلاصه، بعد پیام‌های آخر
    first = [messages[0]] if messages and messages[0].get("role") == "system" else []
    summary_msg = {"role": "system", "content": f"خلاصه مکالمه قبلی:\n{summary}"}
    return first + [summary_msg] + keep
