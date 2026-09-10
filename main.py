# main.py
"""نقطة الدخول الرئيسية.

- MODE=polling  : للتطوير المحلي (python main.py)
- MODE=webhook  : خادم webhook عبر aiohttp — للاستضافة على VPS/Railway/Render
                  (على Vercel يُستخدم api/index.py بدلاً من هذا الملف)
"""
import asyncio
import logging

import config
import db
from core import create_bot, create_dispatcher, setup_logging

setup_logging()
logger = logging.getLogger(__name__)

ALLOWED_UPDATES = ["message", "my_chat_member"]


async def run_polling() -> None:
    """تشغيل البوت بوضع الاستطلاع (للتطوير المحلي)."""
    await db.init_db()
    bot = create_bot()
    dp = create_dispatcher()
    try:
        logger.info("Bot is starting (polling)...")
        await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        await bot.session.close()


def run_webhook_server() -> None:
    """تشغيل خادم webhook (aiohttp) للاستضافات ذات العملية الدائمة."""
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import (
        SimpleRequestHandler,
        setup_application,
    )

    async def on_startup(bot) -> None:
        await db.init_db()
        await bot.set_webhook(
            f"{config.WEBHOOK_URL.rstrip('/')}{config.WEBHOOK_PATH}",
            secret_token=config.WEBHOOK_SECRET or None,
            allowed_updates=ALLOWED_UPDATES,
        )
        logger.info(f"تم ضبط الـ webhook على: {config.WEBHOOK_URL}{config.WEBHOOK_PATH}")

    async def on_shutdown(bot) -> None:
        await bot.delete_webhook()
        logger.info("تم حذف الـ webhook عند الإيقاف")

    bot = create_bot()
    dp = create_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.WEBHOOK_SECRET or None,
    ).register(app, path=config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    logger.info(f"Bot is starting (webhook server على المنفذ {config.PORT})...")
    web.run_app(app, host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    if config.MODE == "webhook":
        run_webhook_server()
    else:
        asyncio.run(run_polling())
