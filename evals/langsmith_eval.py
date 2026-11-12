"""ارزیابی (Eval) با LangSmith — ساده و آموزشی.

چطور کار می‌کند:
1. سوال‌های test_cases.json را می‌خواند.
2. هر سوال را به چت‌بات می‌دهد.
3. چک می‌کند جواب کلمه مورد انتظار را دارد یا نه.
4. اگر LANGSMITH_API_KEY باشد، نتیجه در LangSmith ثبت می‌شود.

اجرا:  python -m evals.langsmith_eval
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maintenance.chat import chat_one_turn, SYSTEM_PROMPT
from maintenance import config

try:
    from langsmith import traceable
except Exception:  # اگر langsmith نصب نبود، بدون trace ادامه بده
    def traceable(name=None):  # type: ignore
        def wrap(fn):
            return fn
        return wrap


@traceable(name="answer_question")
def answer_question(question: str) -> str:
    """یک سوال را جواب بده؛ این تابع در LangSmith دیده می‌شود."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    return chat_one_turn(messages)


def score_answer(answer: str, expected_keyword: str) -> int:
    """ارزیاب ساده: 1 اگر کلمه مورد انتظار در جواب بود، وگرنه 0."""
    return 1 if expected_keyword in answer else 0


def main() -> None:
    if not config.LLM_API_KEY:
        print("اول TOKEN_HARBOR_API_KEY را در .env بگذار.")
        return

    path = os.path.join(os.path.dirname(__file__), "test_cases.json")
    with open(path, encoding="utf-8") as f:
        cases = json.load(f)

    print(f"LangSmith project: {config.LANGSMITH_PROJECT}")
    print(f"تعداد تست: {len(cases)}\n")

    passed = 0
    for case in cases:
        answer = answer_question(case["question"])
        score = score_answer(answer, case["expected_keyword"])
        passed += score
        print(f"سوال: {case['question']}")
        print(f"جواب: {answer[:200]}")
        print(f"امتیاز: {score}/1\n")

    print(f"نتیجه: {passed}/{len(cases)} درست")
    if config.LANGSMITH_API_KEY:
        print("نتیجه‌ها در LangSmith هم ثبت شدند (پروژه بالا را در سایت LangSmith ببین).")
    else:
        print("برای ثبت در LangSmith، LANGSMITH_API_KEY را در .env بگذار.")


if __name__ == "__main__":
    main()
