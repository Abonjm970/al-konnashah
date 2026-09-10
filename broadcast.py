# broadcast.py
"""منطق البث إلى المشتركين مع rate-limiting ومعالجة RetryAfter."""
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Message

import config
import db

logger = logging.getLogger(__name__)


async def broadcast_message(bot: Bot, target: Message, source_chat_id: int) -> int:
    """
    يُرسل نسخة من target إلى جميع المشتركين مع تطبيق rate-limit
    لتفادي RetryAfter.
    يُعيد عدد الرسائل المُرسلة بنجاح.
    """
    subscribers = await db.list_subscribers()
    total = len(subscribers)
    sent_count = 0

    logger.info(
        f"بدء البث: {total} مشترك | "
        f"معدل={config.RATE_PER_SEC} رسالة/ث | دفعة={config.BATCH_SIZE}"
    )

    for batch_start in range(0, total, config.BATCH_SIZE):
        batch = subscribers[batch_start : batch_start + config.BATCH_SIZE]

        for sub in batch:
            if sub == source_chat_id:
                logger.debug(f"تخطي المصدر نفسه: {sub}")
                continue

            try:
                copied = await bot.copy_message(
                    chat_id=sub,
                    from_chat_id=target.chat.id,
                    message_id=target.message_id,
                )
                await db.save_broadcast_message(sub, copied.message_id)
                sent_count += 1
                logger.info(f"بث الرسالة إلى: {sub} (message_id={copied.message_id})")

            except TelegramRetryAfter as ra:
                wait = ra.retry_after + 1  # +1 ثانية هامش أمان
                logger.warning(f"⚠️ RetryAfter: الانتظار {wait}s ثم الاستئناف")
                await asyncio.sleep(wait)
                try:  # إعادة المحاولة بعد الانتظار
                    copied = await bot.copy_message(
                        chat_id=sub,
                        from_chat_id=target.chat.id,
                        message_id=target.message_id,
                    )
                    await db.save_broadcast_message(sub, copied.message_id)
                    sent_count += 1
                    logger.info(f"بث الرسالة إلى: {sub} بعد RetryAfter")
                except Exception as retry_e:
                    logger.error(
                        f"فشل إعادة المحاولة إلى {sub}: {retry_e}", exc_info=True
                    )

            except Exception as e:
                logger.error(f"فشل البث إلى {sub}: {e}", exc_info=True)

            # فاصل زمني بين كل رسالة
            await asyncio.sleep(config.SLEEP_BETWEEN)

        # انتظار إضافي بين الدفعات
        if batch_start + config.BATCH_SIZE < total:
            logger.info("🕒 انتهت الدفعة، انتظار 1s قبل الدفعة التالية")
            await asyncio.sleep(1)

    logger.info(f"✅ انتهى البث: أُرسل إلى {sent_count}/{total} مشترك")
    return sent_count
