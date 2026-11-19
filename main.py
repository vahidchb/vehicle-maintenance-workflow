"""نقطه شروع برنامه: python main.py"""
from maintenance.chat import run_chat
from maintenance.seed import seed_demo_data

if __name__ == "__main__":
    # داده نمایشی را موقع اجرا یک بار بساز (اگر store خالی باشد)
    if seed_demo_data():
        print("داده نمایشی بارگذاری شد: سمند LX (پلاک 123) و پژو (پلاک 456).")
    run_chat()
