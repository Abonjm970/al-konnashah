# webhook.py
"""سكربت إدارة الـ webhook — يُنفَّذ يدوياً عند الحاجة.

الاستخدام:
    python webhook.py set      # ضبط الـ webhook على WEBHOOK_URL
    python webhook.py delete   # حذف الـ webhook (للعودة إلى polling)
    python webhook.py info     # عرض حالة الـ webhook الحالية
"""
import asyncio
import sys

import config
from core import create_bot, setup_logging

setup_logging()

ALLOWED_UPDATES = ["message", "my_chat_member"]


async def set_webhook() -> None:
    bot = create_bot()
    try:
        url = f"{config.WEBHOOK_URL.rstrip('/')}{config.WEBHOOK_PATH}"
        ok = await bot.set_webhook(
            url,
            secret_token=config.WEBHOOK_SECRET or None,
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
        )
        print(f"{'✅' if ok else '❌'} setWebhook -> {url}")
    finally:
        await bot.session.close()


async def delete_webhook() -> None:
    bot = create_bot()
    try:
        ok = await bot.delete_webhook(drop_pending_updates=True)
        print(f"{'✅' if ok else '❌'} deleteWebhook")
    finally:
        await bot.session.close()


async def webhook_info() -> None:
    bot = create_bot()
    try:
        info = await bot.get_webhook_info()
        print(f"URL:              {info.url or '(فارغ — لا webhook مضبوط)'}")
        print(f"تحديثات معلّقة:   {info.pending_update_count}")
        if info.last_error_message:
            print(f"⚠️ آخر خطأ:       {info.last_error_message}")
        if info.last_synchronization_error_date:
            print(f"آخر مزامنة خطأ:   {info.last_synchronization_error_date}")
    finally:
        await bot.session.close()


ACTIONS = {"set": set_webhook, "delete": delete_webhook, "info": webhook_info}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        sys.exit(f"الاستخدام: python webhook.py [{' | '.join(ACTIONS)}]")
    asyncio.run(ACTIONS[sys.argv[1]]())
