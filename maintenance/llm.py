"""اتصال به مدل زبانی — فقط همین فایل با LLM حرف می‌زند."""
from openai import OpenAI
from . import config


def create_client() -> OpenAI:
    """کلاینت OpenAI-compatible برای توکن هاربور بساز."""
    return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)


def ask(messages: list[dict], tools: list[dict] | None = None):
    """یک پیام به مدل بده و جوابش را بگیر.

    messages: لیست پیام‌ها با نقش system / user / assistant / tool
    tools: اگر بدهی، مدل می‌تواند ابزار صدا بزند (tool calling)
    """
    client = create_client()
    return client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        tools=tools or None,
        tool_choice="auto" if tools else None,
    )


def ask_text(messages: list[dict]) -> str:
    """نسخه ساده ask که فقط متن جواب را برمی‌گرداند."""
    response = ask(messages)
    return response.choices[0].message.content or ""
