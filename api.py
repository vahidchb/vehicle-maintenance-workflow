"""API برای رابط کاربری Angular — همین کدهای پایتون، پشت HTTP.

اجرا:
    uvicorn api:app --reload --port 8000

بعد Angular از http://localhost:8000/api/chat صدا می‌زند.
گریدها و نمودار ماژول‌ها هم از /api/modules و /api/records می‌خوانند.
"""
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from maintenance import config, store
from maintenance.chat import SYSTEM_PROMPT, chat_one_turn
from maintenance.memory import count_messages_tokens, needs_compaction, compact_messages
from maintenance.workflow import WORKFLOW_STAGES, confirm_repair_request_step

app = FastAPI(title="Vehicle Maintenance Workflow")

# Angular روی پورت 4200 اجرا می‌شود؛ اجازه بده به API وصل شود.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# حافظه ساده: هر session_id یک مکالمه دارد.
sessions: dict[str, list[dict]] = {}

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
    """یک پیام بگیر، با همان منطق chat.py جواب بده."""
    if not config.LLM_API_KEY or not config.LLM_BASE_URL:
        raise HTTPException(
            status_code=400,
            detail="اول TOKEN_HARBOR_API_KEY و LLM_BASE_URL را در فایل .env بگذار.",
        )
    session_id = req.session_id or str(uuid.uuid4())
    messages = sessions.get(session_id)
    if messages is None:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        sessions[session_id] = messages

    messages.append({"role": "user", "content": req.message})

    # مدیریت توکن + compaction، دقیقاً مثل نسخه ترمینالی
    if needs_compaction(messages):
        messages[:] = compact_messages(messages)

    before = len(messages)
    result = chat_one_turn(messages)
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
    """
    outcome = confirm_repair_request_step(req.confirmation_id, req.confirmed)
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
