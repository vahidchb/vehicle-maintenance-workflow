"""تنظیمات پروژه — همه کلیدها فقط از فایل .env خوانده می‌شوند.

هیچ کلیدی داخل کد نیست. تو فقط فایل .env را پر می‌کنی.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def get_setting(name: str, default: str = "") -> str:
    """یک تنظیم را از محیط بخوان، اگر نبود مقدار پیش‌فرض را بده."""
    return os.getenv(name, default)


# --- LLM از توکن هاربور (سازگار با OpenAI) ---
# TOKEN_HARBOR_API_KEY: کلیدی که از پنل توکن هاربور گرفتی
# LLM_BASE_URL: آدرس API توکن هاربور، از پنل آن کپی کن
# LLM_MODEL: اسم مدلی که توکن هاربور بهت داده، مثلا gpt-4o-mini
LLM_API_KEY = get_setting("TOKEN_HARBOR_API_KEY") or get_setting("LLM_API_KEY")
LLM_BASE_URL = get_setting("LLM_BASE_URL")
LLM_MODEL = get_setting("LLM_MODEL", "gpt-4o-mini")

# --- ابزار سرچ مقاله ---
TAVILY_API_KEY = get_setting("TAVILY_API_KEY")

# --- LangSmith برای eval و مشاهده ردگیری ---
LANGSMITH_API_KEY = get_setting("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = get_setting("LANGSMITH_PROJECT", "vehicle-maintenance-workflow")

# --- مدیریت توکن ---
# وقتی توکن‌های مکالمه از این عدد بیشتر شد، compaction انجام می‌شود.
MAX_TOKENS = int(get_setting("MAX_TOKENS", "4000"))
# در compaction این تعداد پیام آخر دست‌نخورده می‌مانند.
KEEP_LAST_MESSAGES = int(get_setting("KEEP_LAST_MESSAGES", "4"))


def check_config() -> list[str]:
    """بررسی کن چه چیزی کم است؛ لیست پیام‌های راهنما را برگردان."""
    missing = []
    if not LLM_API_KEY:
        missing.append("TOKEN_HARBOR_API_KEY را در فایل .env بگذار.")
    if not LLM_BASE_URL:
        missing.append("LLM_BASE_URL را در فایل .env بگذار (از پنل توکن هاربور).")
    if not TAVILY_API_KEY:
        missing.append("TAVILY_API_KEY خالی است؛ سرچ مقاله کار نمی‌کند (بقیه چت کار می‌کند).")
    return missing
