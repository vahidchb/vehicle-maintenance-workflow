"""نقطه شروع برنامه: python main.py"""
from maintenance import store
from maintenance.chat import run_chat
from maintenance.seed import seed_demo_data

if __name__ == "__main__":
    # اول جدول‌های دیتابیس را بساز (اگر نیستند)، بعد داده نمایشی را
    # یک بار بساز (اگر دیتابیس خالی باشد)
    store.init_db()
    if seed_demo_data():
        print("داده نمایشی بارگذاری شد: سمند LX (پلاک 123)، پژو (پلاک 456) و پراید (پلاک 789).")
    run_chat()
