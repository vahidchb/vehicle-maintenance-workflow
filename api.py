"""API برای رابط کاربری Angular — همین کدهای پایتون، پشت HTTP.

اجرا:
    uvicorn api:app --reload --port 8000

بعد Angular از http://localhost:8000/api/chat صدا می‌زند.
گریدها و نمودار ماژول‌ها هم از /api/modules و /api/records می‌خوانند.
"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from maintenance import config, session_memory, store
from maintenance.chat import SYSTEM_PROMPT, chat_one_turn
from maintenance.memory import count_messages_tokens
from maintenance.seed import seed_demo_data
from maintenance.workflow import WORKFLOW_STAGES, confirm_repair_request_step


@asynccontextmanager
async def lifespan(app: FastAPI):
    """موقع بالا آمدن API: اول جدول‌های دیتابیس را بساز، بعد داده نمایشی
    را یک بار بساز (اگر دیتابیس خالی باشد)."""
    store.init_db()
    seed_demo_data()
    yield


app = FastAPI(title="Vehicle Maintenance Workflow", lifespan=lifespan)

# Angular روی پورت 4200 اجرا می‌شود؛ اجازه بده به API وصل شود.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# حافظه چت در دیتابیس است (جدول session_memory)، نه در حافظه برنامه؛
# پس API بی‌حافظه (stateless) است و ری‌استارت بک‌اند تاریخچه را پاک نمی‌کند.
# هر جلسه با session_id شناخته می‌شود (هنوز لاگین نداریم؛ user_id بعداً می‌آید).

# ماژول‌ها: کلید، نام فارسی، و تابع لیست رکوردها
MODULES = [
    {"key": "equipment", "name": "تجهیزها", "list_fn": store.list_vehicles},
    {"key": "inspections", "name": "بازدیدها", "list_fn": store.list_inspections},
    {"key": "evaluations", "name": "ارزیابی‌ها", "list_fn": store.list_evaluations},
    {"key": "faults", "name": "خرابی‌ها", "list_fn": store.list_faults},
    {"key": "requests", "name": "درخواست‌های تعمیراتی", "list_fn": store.list_requests},
    {"key": "work_orders", "name": "حکم‌های کار", "list_fn": store.list_work_orders},
]


def _find_module(key: str) -> dict:
    """ماژول را با کلید پیدا کن؛ اگر نبود خطای 404 بده."""
    for module in MODULES:
        if module["key"] == key:
            return module
    raise HTTPException(status_code=404, detail=f"ماژول «{key}» پیدا نشد.")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tokens: int
    max_tokens: int
    used_tool: bool
    # اگر در این دور درخواست تعمیراتی آماده شده باشد، پنجره تایید با این اطلاعات باز می‌شود
    pending_confirmation: dict | None = None


class ConfirmRequest(BaseModel):
    confirmation_id: str
    confirmed: bool
    # جلسه چتی که تاییدیه از آن آمده؛ اگر بدهی، نتیجه تایید به مکالمه‌اش
    # اضافه می‌شود تا مدل در دور بعدی بداند درخواست ثبت (یا رد) شده و دوباره نپرسد
    session_id: str | None = None


class ConfirmResponse(BaseModel):
    ok: bool
    tracking: str | None = None
    message: str


@app.get("/api/health")
def health():
    """سلامتی API را برگردان؛ مدل هم نشان بده."""
    return {"status": "ok", "model": config.LLM_MODEL}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """یک پیام بگیر، با همان منطق chat.py جواب بده.

    جریان حافظه (stateless): حافظه سشن را از دیتابیس بخوان،
    کانتکس را بساز (خلاصه غلتان + چند پیام آخر + پیام جدید)،
    جواب بده و حافظه جدید را ذخیره کن.
    """
    if not config.LLM_API_KEY or not config.LLM_BASE_URL:
        raise HTTPException(
            status_code=400,
            detail="اول TOKEN_HARBOR_API_KEY و LLM_BASE_URL را در فایل .env بگذار.",
        )
    session_id = req.session_id or str(uuid.uuid4())
    memory = session_memory.load_session(session_id)
    messages, included = session_memory.build_context(SYSTEM_PROMPT, memory, req.message)

    before = len(messages)
    result = chat_one_turn(messages, active_plate=memory["active_plate"])
    session_memory.save_turn(session_id, memory, messages, included,
                             active_plate=result["active_plate"])
    used_tool = any(m.get("role") == "tool" for m in messages[before:])

    return ChatResponse(
        reply=result["reply"],
        session_id=session_id,
        tokens=count_messages_tokens(messages),
        max_tokens=config.MAX_TOKENS,
        used_tool=used_tool,
        pending_confirmation=result["pending_confirmation"],
    )


@app.post("/api/confirm-repair-request", response_model=ConfirmResponse)
def confirm_repair_request(req: ConfirmRequest):
    """تاییدیه در انتظار درخواست تعمیراتی را تایید یا رد کن.

    تایید → درخواست ثبت می‌شود و شماره رهگیری REQ می‌گیرد.
    رد → تاییدیه پاک می‌شود و هیچ درخواستی ثبت نمی‌شود.
    یک بار تایید کافی است؛ نتیجه به مکالمه اضافه می‌شود تا مدل دوباره نپرسد.
    """
    outcome = confirm_repair_request_step(req.confirmation_id, req.confirmed)
    # نتیجه تایید را به حافظه جلسه چت اضافه کن تا مدل در دور بعدی بداند چه شد
    # (حافظه در دیتابیس است؛ اگر سشن نبود ساخته می‌شود)
    if req.session_id:
        session_memory.append_system_note(
            req.session_id,
            f"[نتیجه تایید درخواست تعمیراتی] {outcome['message']}",
        )
    return ConfirmResponse(
        ok=outcome["ok"],
        tracking=outcome["tracking"],
        message=outcome["message"],
    )


@app.get("/api/modules")
def modules():
    """همه ماژول‌ها را با تعداد رکورد و مراحل workflow برگردان."""
    return {
        "modules": [
            {"key": m["key"], "name": m["name"], "count": len(m["list_fn"]())}
            for m in MODULES
        ],
        "stages": WORKFLOW_STAGES,
    }


@app.get("/api/records/{module_key}")
def records(module_key: str):
    """رکوردهای یک ماژول را برای گرید برگردان."""
    module = _find_module(module_key)
    return {"module": module["key"], "name": module["name"], "records": module["list_fn"]()}


@app.get("/api/records/{module_key}/{tracking_id}")
def record_detail(module_key: str, tracking_id: str):
    """جزئیات یک رکورد را با شماره رهگیری برگردان."""
    module = _find_module(module_key)
    for record in module["list_fn"]():
        if record.get("tracking", "").upper() == tracking_id.upper():
            return {"module": module["key"], "name": module["name"], "record": record}
    raise HTTPException(status_code=404, detail=f"رکوردی با شماره {tracking_id} پیدا نشد.")
