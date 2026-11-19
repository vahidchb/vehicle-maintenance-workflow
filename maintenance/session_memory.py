"""حافظه سشن چت — دو لایه، روی دیتابیس.

قبلاً تاریخچه چت فقط در حافظه (RAM) بود و با ری‌استارت بک‌اند پاک می‌شد.
حالا هر جلسه چت در جدول `session_memory` ذخیره می‌شود و بعد از ری‌استارت
هم برمی‌گردد. API دیگر حافظه ندارد (stateless): هر بار حافظه را از دیتابیس
می‌خواند، کانتکس را می‌سازد، جواب می‌دهد و دوباره ذخیره می‌کند.

دو لایه حافظه — چرا دو لایه؟
1. چند پیام آخر «عیناً» (verbatim): جزئیات دقیق حرف‌های تازه.
2. خلاصه غلتان (rolling summary): همه حرف‌های قبل از آن چند پیام،
   فشرده‌شده در چند خط. هر بار که پیامی از پنجره بیرون می‌افتد،
   به خلاصه اضافه می‌شود — پس هیچی گم نمی‌شود، ولی کانتکس هم
   هیچ‌وقت بزرگ نمی‌شود.

پنجره عیناً کوچک است: KEEP_LAST_MESSAGES (۴ پیام، از config) —
خلاصه کار سنگین را می‌کند. برای اینکه بعداً بشود فهمید خلاصه‌سازی
چقدر مؤثر است، پنجره عمداً کوچک نگه داشته شده.

نکته مهم — توالی tool-call را نصف نکن:
یک پیام tool همیشه بعد از پیام assistantای می‌آید که آن ابزار را صدا زده.
اگر پنجره از وسط این توالی بریده شود (پیام tool بماند ولی پیام assistant
بیرون بیفتد)، API مدل خطا می‌دهد. پس موقع بریدن پنجره، پیام‌های tool
اولِ پنجره کنار گذاشته می‌شوند (و به خلاصه می‌روند).

هنوز لاگین نداریم؛ سشن فقط با session_id شناخته می‌شود.
وقتی لاگین آمد، user_id هم به این جدول اضافه می‌شود.
"""
import json
from datetime import datetime, timezone

from . import config, db
from .memory import count_messages_tokens, summarize_text

# جلسه نسخه ترمینالی (main.py) — یک سشن ثابت، تا تاریخچه ترمینال هم بماند.
CLI_SESSION_ID = "cli"

# ابتدای پیام خلاصه در کانتکس.
SUMMARY_PREFIX = "خلاصه مکالمه قبلی:"


def load_session(session_id: str) -> dict:
    """حافظه یک سشن را از دیتابیس بخوان.

    برمی‌گرداند: {"summary": خلاصه غلتان، "recent": [چند پیام آخر],
    "active_plate": پلاک خودروی فعلی سشن ("" اگر هنوز نیست)}
    اگر سشن نبود، حافظه خالی برگردان (خطا نمی‌دهد).
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT summary, recent_messages, active_plate FROM session_memory"
            " WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return {"summary": "", "recent": [], "active_plate": ""}
    try:
        recent = json.loads(row["recent_messages"])
    except (ValueError, TypeError):
        recent = []
    return {
        "summary": row["summary"] or "",
        "recent": recent if isinstance(recent, list) else [],
        "active_plate": row["active_plate"] or "",
    }


def save_session(session_id: str, summary: str, recent: list[dict],
                 active_plate: str | None = None) -> None:
    """حافظه یک سشن را در دیتابیس بنویس (اگر بود، جایگزین کن).

    اگر active_plate داده نشد (None)، پلاک قبلی همان سشن حفظ می‌شود؛
    برای پاک کردنش، رشته خالی "" بده.
    """
    if active_plate is None:
        active_plate = load_session(session_id)["active_plate"]
    with db.lock:
        with db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO session_memory"
                " (session_id, summary, recent_messages, active_plate, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    summary or "",
                    json.dumps(list(recent), ensure_ascii=False),
                    active_plate or "",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def append_system_note(session_id: str, content: str) -> None:
    """یک یادداشت سیستمی به حافظه سشن اضافه کن (بدون خلاصه‌سازی).

    برای نتیجه تایید درخواست تعمیراتی استفاده می‌شود: مودال تایید
    خارج از چت است، ولی نتیجه‌اش باید در مکالمه بیاید تا مدل بداند چه شد.
    خلاصه‌سازی اینجا انجام نمی‌شود (نیازی به فراخوانی مدل نیست)؛
    اگر پنجره پر شود، در دور بعدی چت (save_turn) غلت می‌خورد.
    """
    memory = load_session(session_id)
    memory["recent"].append({"role": "system", "content": content})
    save_session(session_id, memory["summary"], memory["recent"])


def _drop_leading_tools(messages: list[dict]) -> list[dict]:
    """پیام‌های tool اول لیست را کنار بگذار.

    پیام tool بدون پیام assistantای که آن را صدا زده معتبر نیست؛
    اگر پنجره از وسط توالی بریده شده باشد، این‌ها را حذف می‌کنیم
    (به خلاصه می‌روند، گم نمی‌شوند).
    """
    kept = list(messages)
    while kept and kept[0].get("role") == "tool":
        kept.pop(0)
    return kept


def _trim_to_window(messages: list[dict], size: int) -> list[dict]:
    """آخرین size پیام را برگردان، با مرز امن (نصف نکردن توالی tool-call)."""
    if size <= 0:
        return []
    return _drop_leading_tools(messages[-size:])


def build_context(system_prompt: str, memory: dict, user_text: str) -> tuple[list[dict], int]:
    """کانتکس یک دور چت را بساز.

    ترتیب پیام‌ها: [system prompt] + [خلاصه غلتان، اگر بود]
    + [چند پیام آخر، عیناً] + [پیام جدید کاربر].

    اگر توکن‌ها از حد بگذرند، پیام‌های آخر را از قدیمی‌ترین کم می‌کند
    (خلاصه سر جایش می‌ماند، چون همان فشرده حرف‌های قدیمی است).

    برمی‌گرداند: (لیست پیام‌ها برای مدل، تعداد پیام‌های ذخیره‌شده‌ای
    که عیناً در کانتکس آمدند) — عدد دوم را save_turn لازم دارد تا
    بداند کدام پیام‌ها «جدید» این دور بوده‌اند.
    """
    messages = [{"role": "system", "content": system_prompt}]
    if memory["summary"]:
        messages.append(
            {"role": "system", "content": f"{SUMMARY_PREFIX}\n{memory['summary']}"}
        )

    recent = _trim_to_window(memory["recent"], config.KEEP_LAST_MESSAGES)
    user_msg = {"role": "user", "content": user_text}
    # اگر جا نشد، از قدیمی‌ترین پیام آخر کم کن (پیام کاربر همیشه می‌ماند).
    while recent and count_messages_tokens(messages + recent + [user_msg]) > config.MAX_TOKENS:
        recent = _drop_leading_tools(recent[1:])

    messages.extend(recent)
    messages.append(user_msg)
    return messages, len(recent)


def _summarize_history(old_summary: str, overflow: list[dict]) -> str:
    """خلاصه غلتان جدید را بساز: خلاصه قبلی + پیام‌هایی که از پنجره افتادند.

    از همان یک فراخوانی خلاصه‌سازی compaction استفاده می‌کند
    (memory.summarize_text) — فراخوانی اضافه‌ای به مدل نیست.
    """
    parts = []
    if old_summary:
        parts.append(f"خلاصه قبلی:\n{old_summary}")
    parts.append(
        "\n".join(f"{m.get('role')}: {m.get('content') or ''}" for m in overflow)
    )
    return summarize_text("\n\n".join(parts))


def save_turn(session_id: str, old_memory: dict, messages: list[dict],
              included_count: int, active_plate: str | None = None) -> dict:
    """بعد از یک دور چت، حافظه سشن را به‌روز کن و ذخیره کن.

    messages: همان لیستی که build_context ساخت و chat_one_turn
    جواب و نتیجه ابزارها را به آن اضافه کرد (درجا عوض شده).
    included_count: عددی که build_context برگرداند.
    active_plate: پلاک خودروی فعلی این دور (از chat_one_turn)؛
    اگر None باشد، پلاک قبلی سشن حفظ می‌شود.

    منطق: تاریخچه کامل = پیام‌های ذخیره‌شده قبلی + پیام‌های جدید این دور.
    از این تاریخچه، چند پیام آخر عیناً می‌مانند و بقیه به خلاصه غلتان
    می‌روند. چون تاریخچه کامل از حافظه قبلی + دور جدید ساخته می‌شود،
    هیچ پیامی گم نمی‌شود — حتی اگر در این دور به‌خاطر بودجه توکن
    در کانتکس نیامده باشد.

    برمی‌گرداند: حافظه جدید {"summary": ...، "recent": ...، "active_plate": ...}.
    """
    # پیام‌های جدید این دور = همه پیام‌ها به‌جز [system] + [خلاصه؟] + [پنجره قبلی]
    prefix = 1 + (1 if old_memory["summary"] else 0) + included_count
    new_messages = messages[prefix:]

    full = list(old_memory["recent"]) + list(new_messages)
    recent_new = _trim_to_window(full, config.KEEP_LAST_MESSAGES)
    overflow = full[:len(full) - len(recent_new)] if recent_new else full

    if overflow:
        summary = _summarize_history(old_memory["summary"], overflow)
    else:
        summary = old_memory["summary"]

    if active_plate is None:
        active_plate = old_memory.get("active_plate", "")
    save_session(session_id, summary, recent_new, active_plate)
    return {"summary": summary, "recent": recent_new, "active_plate": active_plate}
