# api/index.py
"""معالج Vercel Serverless — يستقبل تحديثات تيليجرام عبر webhook.

Vercel يشغّل التطبيق ASGI المُصدَّر باسم `app` تلقائياً.
"""
import logging

import config
import db
from core import create_bot, create_dispatcher, setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Dispatcher عديم الحالة — يُنشأ مرة واحدة لكل نسخة serverless (يُعاد استخدامه)
dp = create_dispatcher()
_db_ready = False


async def _ensure_db() -> None:
    """تهيئة قاعدة البيانات مرة واحدة لكل نسخة serverless."""
    global _db_ready
    if not _db_ready:
        await db.init_db()
        _db_ready = True


async def app(scope, receive, send):  # ASGI
    """تطبيق ASGI بسيط: يمرّر التحديثات إلى dispatcher ويرد 200 فوراً."""
    from aiogram.types import Update

    if scope["type"] != "http":
        return

    async def respond(status: int, body: bytes = b"OK") -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    method = scope.get("method", "GET")

    # فحص صحي بسيط
    if method == "GET":
        await respond(200, "al-konnashah webhook is running".encode())
        return

    # نعالج POST على أي مسار — التحقق من السر أدناه هو خط الدفاع الحقيقي
    # (بعد rewrites في Vercel قد يختلف المسار الظاهر للتطبيق عن WEBHOOK_PATH)
    if method != "POST":
        await respond(404, b"Not Found")
        return

    # التحقق من السر المشترك مع تيليجرام
    if config.WEBHOOK_SECRET:
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        if headers.get("x-telegram-bot-api-secret-token") != config.WEBHOOK_SECRET:
            logger.warning("طلب webhook بسرّ غير صحيح — مرفوض")
            await respond(403, b"Forbidden")
            return

    # قراءة جسم الطلب
    body = b""
    while True:
        message = await receive()
        if message["type"] == "http.request":
            body += message.get("body", b"")
            if not message.get("more_body"):
                break

    try:
        update = Update.model_validate_json(body)
    except Exception:
        logger.warning("تحديث غير صالح البنية — تم تجاهله", exc_info=True)
        await respond(400, b"Bad Request")
        return

    await _ensure_db()

    bot = create_bot()
    try:
        await dp.feed_webhook_update(bot, update)
    except Exception:
        logger.error("خطأ أثناء معالجة التحديث", exc_info=True)
    finally:
        await bot.session.close()

    # الرد 200 دائماً حتى لا يعيد تيليجرام الإرسال
    await respond(200)
