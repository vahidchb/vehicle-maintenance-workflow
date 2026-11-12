# چت‌بات workflow نگهداری و تعمیرات تجهیزات خودرویی

یک چت‌بات آموزشی که یک **workflow واقعی و صریح** را نشان می‌دهد:
ثبت تجهیز، بازدید، ارزیابی، خرابی، درخواست تعمیراتی، تایید و حکم کار —
با **tool calling، مدیریت توکن، compaction و eval با LangSmith.**

همه‌چیز ساده و قابل خواندن است؛ هر فایل یک کار مشخص می‌کند.
دیتابیس نداریم؛ رکوردها در حافظه نگه داشته می‌شوند.

> برای یادگیری قدم به قدم، اول بخوان: [`docs/LEARN_FA.md`](docs/LEARN_FA.md)

## مراحل workflow

```
ثبت تجهیز (EQ-001)
      ↓  با شماره پلاک
ثبت بازدید (INSP-001)
      ↓  بر اساس زیرمجموعه: موتور، چرخ و...
ثبت ارزیابی (EV-001)
      ↓  می‌تواند بدون خرابی باشد
ثبت خرابی (FLT-001)  ← اختیاری، وصل به یک ارزیابی
      ↓
ثبت درخواست تعمیراتی (REQ-001)
      ↓  خرابی در درخواست هست
تایید درخواست
      ↓
ثبت حکم کار (WO-001)
         تعمیرگاه + قطعات مورد نیاز
```

هر مرحله یک شماره رهگیری می‌دهد و قدم بعدی را نمی‌توان
قبل از قدم قبلی انجام داد (مثلا حکم کار بدون تایید درخواست ثبت نمی‌شود).

## ساختار پروژه

```
vehicle-maintenance-workflow/
├── main.py                  # شروع برنامه: python main.py
├── api.py                   # API برای Angular (چت + گریدها + نمودار ماژول‌ها)
├── maintenance/
│   ├── config.py            # خواندن کلیدها از .env
│   ├── llm.py               # اتصال به مدل (توکن هاربور)
│   ├── memory.py            # شمارش توکن + compaction
│   ├── store.py             # حافظه رکوردها (بدون دیتابیس)
│   ├── workflow.py          # مراحل صریح workflow + کنترل ترتیب
│   ├── tools.py             # ابزارهای مدل (13 ابزار)
│   └── chat.py              # حلقه اصلی چت + SYSTEM_PROMPT
└── evals/
    ├── langsmith_eval.py    # اجرای تست‌ها و ثبت در LangSmith
    └── test_cases.json      # سوال‌های تست
```

## نصب و اجرا (5 دقیقه)

```bash
# 1) نصب
python -m venv .venv
source .venv/bin/activate   # ویندوز: .venv\Scripts\activate
pip install -r requirements.txt

# 2) تنظیم کلیدها
cp .env.example .env
# حالا .env را باز کن و پر کن:
# TOKEN_HARBOR_API_KEY و LLM_BASE_URL از پنل توکن هاربور
# TAVILY_API_KEY از سایت Tavily (رایگان)
# LANGSMITH_API_KEY از سایت LangSmith (رایگان، اختیاری)

# 3) اجرا — نسخه ترمینالی
python main.py
```

بعد در ترمینال بنویس، مثلا:
> یک خودروی پراید با پلاک 12ب345 ایران 67 ثبت کن

> خودروی پراید پلاک 12ب345 ایران 67 موتورش صدای غیرعادی می‌دهد

## رابط کاربری Angular + API پایتون

```bash
# ترمینال 1 — بک‌اند پایتون
python -m uvicorn api:app --reload --port 8000

# ترمینال 2 — فرانت‌اند Angular
cd frontend
npm install
npm start
# بعد باز کن: http://localhost:4200
```

همه کارها با چت انجام می‌شود؛ هیچ فرم ورودی نیست.
گریدها فقط رکوردها را نشان می‌دهند و آیکن نمودار، ماژول‌ها را جداگانه نشان می‌دهد.

## مفاهیم، خیلی ساده

| مفهوم | کجاست؟ | یعنی چی؟ |
|---|---|---|
| **Workflow صریح** | `maintenance/workflow.py` | ترتیب قدم‌ها را ما تعیین کرده‌ایم؛ هر قدم، قدم قبلی را چک می‌کند. |
| **Tool calling** | `maintenance/tools.py` + `maintenance/chat.py` | مدل از حرف کاربر می‌فهمد کدام ابزار را صدا بزند. |
| **Token management** | `maintenance/memory.py` | توکن‌های مکالمه را می‌شمارد تا از حد نگذرد. |
| **Compaction** | `maintenance/memory.py` | وقتی توکن زیاد شد، پیام‌های قدیمی را خلاصه می‌کند. |
| **Eval با LangSmith** | `evals/langsmith_eval.py` | سوال‌های تست را می‌پرسد، امتیاز می‌دهد و در LangSmith ثبت می‌کند. |

اجرای eval:
```bash
python -m evals.langsmith_eval
```

## نکته امنیتی

فایل `.env` واقعی را هرگز در گیت‌هاب نگذار؛ در `.gitignore` هست.
فقط `.env.example` در ریپو است.
