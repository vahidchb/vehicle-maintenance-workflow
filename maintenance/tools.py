"""ابزارها (Tools) — کاری که مدل خودش نمی‌تواند انجام دهد.

ابزارها فقط «درِ ورودی» مدل به workflow هستند:
خودِ قانون ترتیب قدم‌ها در workflow.py است، نه اینجا.
مدل وقتی لازم بداند، خودش این ابزارها را صدا می‌زند.
"""
import json
from . import config, store, workflow

# معرفی ابزارها به مدل، با فرمت OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "register_equipment",
            "description": "یک خودرو/تجهیز جدید را با شماره پلاک وارد سیستم کن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plate": {"type": "string", "description": "شماره پلاک، مثلا '12ب345 ایران 67'"},
                    "name": {"type": "string", "description": "نام خودرو، مثلا 'پراید'"},
                    "kind": {"type": "string", "description": "نوع تجهیز، مثلا 'سواری'"},
                },
                "required": ["plate", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_vehicle",
            "description": "یک خودرو را با پلاک یا نام جستجو کن؛ مرحله فعلی workflow آن را هم نشان می‌دهد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "پلاک یا نام خودرو"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_inspection",
            "description": "برای یک خودرو بازدید ثبت کن. اول باید خودرو ثبت شده باشد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plate": {"type": "string", "description": "شماره پلاک خودرو"},
                    "subsystem": {"type": "string", "description": "زیرمجموعه، مثلا 'موتور' یا 'چرخ'"},
                    "note": {"type": "string", "description": "توضیح بازدید"},
                },
                "required": ["plate", "subsystem"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_evaluation",
            "description": "برای یک بازدید، ارزیابی ثبت کن. ارزیابی می‌تواند بدون خرابی باشد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plate": {"type": "string", "description": "شماره پلاک خودرو"},
                    "inspection_id": {"type": "string", "description": "شماره رهگیری بازدید، مثلا 'INSP-001'"},
                    "summary": {"type": "string", "description": "خلاصه ارزیابی"},
                },
                "required": ["plate", "inspection_id", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_fault",
            "description": "یک خرابی برای یک ارزیابی ثبت کن. اول باید ارزیابی ثبت شده باشد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "evaluation_id": {"type": "string", "description": "شماره رهگیری ارزیابی، مثلا 'EV-001'"},
                    "description": {"type": "string", "description": "شرح خرابی"},
                    "subsystem": {"type": "string", "description": "زیرمجموعه، مثلا 'موتور'"},
                },
                "required": ["evaluation_id", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_repair_request",
            "description": "برای یک ارزیابی، درخواست تعمیراتی ثبت کن که خرابی در آن هست.",
            "parameters": {
                "type": "object",
                "properties": {
                    "evaluation_id": {"type": "string", "description": "شماره رهگیری ارزیابی، مثلا 'EV-001'"},
                    "fault_id": {"type": "string", "description": "شماره رهگیری خرابی، مثلا 'FLT-001'"},
                    "description": {"type": "string", "description": "شرح درخواست"},
                },
                "required": ["evaluation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_request",
            "description": "یک درخواست تعمیراتی را تایید کن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "شماره رهگیری درخواست، مثلا 'REQ-001'"},
                },
                "required": ["request_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_work_order",
            "description": "برای یک درخواست تاییدشده، حکم کار ثبت کن. تعمیرگاه و قطعات مورد نیاز را بگیر.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "شماره رهگیری درخواست تاییدشده، مثلا 'REQ-001'"},
                    "shop": {"type": "string", "description": "نام تعمیرگاه"},
                    "parts": {"type": "string", "description": "قطعات مورد نیاز"},
                },
                "required": ["request_id", "shop", "parts"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_repair_request",
            "description": "درخواست‌های تعمیراتی را با شماره رهگیری، پلاک یا کلمه جستجو کن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "شماره رهگیری، پلاک یا کلمه"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_evaluation",
            "description": "ارزیابی‌ها را با شماره رهگیری، پلاک یا کلمه جستجو کن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "شماره رهگیری، پلاک یا کلمه"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_work_order",
            "description": "حکم‌های کار را با شماره رهگیری، پلاک یا کلمه جستجو کن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "شماره رهگیری، پلاک یا کلمه"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_articles",
            "description": "در وب مقاله پیدا کن. وقتی کاربر درباره یک قطعه یا جزء خودرو سوال دارد از این استفاده کن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "موضوع سرچ، مثلا 'نگهداری موتور خودرو'"},
                    "max_results": {"type": "integer", "description": "چند نتیجه برگردان (پیش‌فرض 3)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_article",
            "description": "متن کامل یک مقاله را از روی لینکش بخوان تا محتوایش را نشان بدهی، نه فقط لینک را.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "لینک کامل مقاله"},
                },
                "required": ["url"],
            },
        },
    },
]


def _matches(record: dict, query: str, fields: list[str]) -> bool:
    """آیا پرسمان در یکی از فیلدهای رکورد هست؟ (بدون حساسیت به حروف)"""
    query = query.strip().lower()
    if not query:
        return True
    for field in fields:
        if query in str(record.get(field, "")).lower():
            return True
    return False


# --- ابزارهای ثبت: فقط پیام workflow را برمی‌گردانند ---
def register_equipment(plate: str, name: str, kind: str = "") -> str:
    """قدم 1 workflow: تجهیز را با پلاک ثبت کن."""
    return workflow.register_equipment_step(plate, name, kind)["message"]


def register_inspection(plate: str, subsystem: str, note: str = "") -> str:
    """قدم 2 workflow: بازدید ثبت کن."""
    return workflow.register_inspection_step(plate, subsystem, note)["message"]


def register_evaluation(plate: str, inspection_id: str, summary: str) -> str:
    """قدم 3 workflow: ارزیابی ثبت کن."""
    return workflow.register_evaluation_step(plate, inspection_id, summary)["message"]


def register_fault(evaluation_id: str, description: str, subsystem: str = "") -> str:
    """قدم 4 workflow: خرابی ثبت کن."""
    return workflow.register_fault_step(evaluation_id, description, subsystem)["message"]


def register_repair_request(evaluation_id: str, fault_id: str = "", description: str = "") -> str:
    """قدم 5 workflow: درخواست تعمیراتی ثبت کن."""
    return workflow.register_repair_request_step(evaluation_id, fault_id, description)["message"]


def approve_request(request_id: str) -> str:
    """قدم 6 workflow: درخواست را تایید کن."""
    return workflow.approve_request_step(request_id)["message"]


def register_work_order(request_id: str, shop: str, parts: str) -> str:
    """قدم 7 workflow: حکم کار ثبت کن."""
    return workflow.register_work_order_step(request_id, shop, parts)["message"]


# --- ابزارهای جستجو در حافظه ---
def search_vehicle(query: str) -> str:
    """خودرو را با پلاک یا نام پیدا کن و مرحله فعلی‌اش را هم بگو."""
    found = [v for v in store.list_vehicles() if _matches(v, query, ["plate", "name", "kind"])]
    if not found:
        return "خودرویی پیدا نشد. اگر جدید است، اول با شماره پلاک ثبتش کن."
    lines = []
    for v in found:
        stage = workflow.current_stage(v["plate"])
        lines.append(
            f"- {v['tracking']} | پلاک: {v['plate']} | {v['name']}\n"
            f"  مرحله فعلی: {stage['stage_name']} — {stage['next_step']}"
        )
    return "\n".join(lines)


def search_repair_request(query: str) -> str:
    """درخواست‌های تعمیراتی را جستجو کن."""
    found = [r for r in store.list_requests()
             if _matches(r, query, ["tracking", "plate", "description", "status"])]
    if not found:
        return "درخواست تعمیراتی‌ای پیدا نشد."
    lines = [f"- {r['tracking']} | پلاک: {r['plate']} | وضعیت: {r['status']} | {r['description']}"
             for r in found]
    return "\n".join(lines)


def search_evaluation(query: str) -> str:
    """ارزیابی‌ها را جستجو کن."""
    found = [e for e in store.list_evaluations()
             if _matches(e, query, ["tracking", "plate", "summary", "inspection_id"])]
    if not found:
        return "ارزیابی‌ای پیدا نشد."
    lines = [f"- {e['tracking']} | پلاک: {e['plate']} | بازدید: {e['inspection_id']} | {e['summary']}"
             for e in found]
    return "\n".join(lines)


def search_work_order(query: str) -> str:
    """حکم‌های کار را جستجو کن."""
    found = [w for w in store.list_work_orders()
             if _matches(w, query, ["tracking", "plate", "shop", "parts", "request_id"])]
    if not found:
        return "حکم کاری پیدا نشد."
    lines = [f"- {w['tracking']} | پلاک: {w['plate']} | تعمیرگاه: {w['shop']} | قطعات: {w['parts']}"
             for w in found]
    return "\n".join(lines)


# --- ابزارهای مقاله (Tavily) ---
def search_articles(query: str, max_results: int = 3) -> str:
    """با Tavily در وب مقاله سرچ کن و نتیجه را به صورت متن ساده بده."""
    if not config.TAVILY_API_KEY:
        return "کلید Tavily تنظیم نشده است؛ نمی‌توانم مقاله سرچ کنم."

    from tavily import TavilyClient

    client = TavilyClient(api_key=config.TAVILY_API_KEY)
    result = client.search(query=query, max_results=max_results, search_depth="basic")

    lines = []
    for item in result.get("results", []):
        lines.append(f"- {item.get('title')}\n  {item.get('url')}\n  {item.get('content', '')[:300]}")
    if not lines:
        return "مقاله‌ای پیدا نشد."
    return "\n".join(lines)


def read_article(url: str, max_chars: int = 3000) -> str:
    """متن یک مقاله را از روی لینکش بخوان.

    max_chars برای مدیریت توکن است: متن کامل مقاله ممکن است خیلی طولانی
    باشد، پس فقط اولش را برمی‌گردانیم.
    """
    if not config.TAVILY_API_KEY:
        return "کلید Tavily تنظیم نشده است؛ نمی‌توانم مقاله را بخوانم."

    from tavily import TavilyClient

    client = TavilyClient(api_key=config.TAVILY_API_KEY)
    result = client.extract(urls=[url])

    items = result.get("results", [])
    if not items:
        return "نتوانستم متن مقاله را بخوانم."
    text = items[0].get("raw_content", "")[:max_chars]
    if not text.strip():
        return "نتوانستم متن مقاله را بخوانم."
    return text


def run_tool(name: str, arguments: str) -> str:
    """ابزار را با آرگومان‌های مدل اجرا کن."""
    args = json.loads(arguments or "{}")
    if name == "register_equipment":
        return register_equipment(args.get("plate", ""), args.get("name", ""), args.get("kind", ""))
    if name == "search_vehicle":
        return search_vehicle(args.get("query", ""))
    if name == "register_inspection":
        return register_inspection(args.get("plate", ""), args.get("subsystem", ""), args.get("note", ""))
    if name == "register_evaluation":
        return register_evaluation(args.get("plate", ""), args.get("inspection_id", ""), args.get("summary", ""))
    if name == "register_fault":
        return register_fault(args.get("evaluation_id", ""), args.get("description", ""), args.get("subsystem", ""))
    if name == "register_repair_request":
        return register_repair_request(args.get("evaluation_id", ""), args.get("fault_id", ""), args.get("description", ""))
    if name == "approve_request":
        return approve_request(args.get("request_id", ""))
    if name == "register_work_order":
        return register_work_order(args.get("request_id", ""), args.get("shop", ""), args.get("parts", ""))
    if name == "search_repair_request":
        return search_repair_request(args.get("query", ""))
    if name == "search_evaluation":
        return search_evaluation(args.get("query", ""))
    if name == "search_work_order":
        return search_work_order(args.get("query", ""))
    if name == "search_articles":
        return search_articles(query=args.get("query", ""), max_results=args.get("max_results", 3))
    if name == "read_article":
        return read_article(url=args.get("url", ""))
    return f"ابزار ناشناخته: {name}"
