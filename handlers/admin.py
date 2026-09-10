# handlers/admin.py
"""أوامر الإدارة من دردشات المصدر فقط: /list, /send, /delast."""
import logging

from aiogram import Bot, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

import config
import db
from broadcast import broadcast_message

logger = logging.getLogger(__name__)
router = Router(name="admin")


class IsSourceChat(BaseFilter):
    """يمرّر الرسائل الواردة من دردشات المصدر فقط (بالمعرّف أو اسم المستخدم)."""

    async def __call__(self, message: Message) -> bool:
        username = (message.chat.username or "").lower()
        for c in config.FILTER_SOURCE_CHATS:
            if isinstance(c, int) and message.chat.id == c:
                return True
            if isinstance(c, str) and c.lower() == username:
                return True
        return False


@router.message(Command("list"), IsSourceChat())
async def cmd_list(message: Message) -> None:
    """عرض عدد المشتركين الحالي."""
    subs = await db.list_subscribers()
    await message.answer(f"عدد المشتركين الحالي: {len(subs)}")
    logger.info(f"أمر /list: تم عرض عدد المشتركين {len(subs)}")


@router.message(Command("delast"), IsSourceChat())
async def cmd_delast(message: Message, bot: Bot) -> None:
    """حذف آخر رسالة بث من جميع المشتركين."""
    broadcasts = await db.get_last_broadcasts()
    if not broadcasts:
        await message.answer("لا توجد رسالة بث سابقة ليتم حذفها.")
        logger.warning("أمر /delast فشل لعدم وجود سجل بث سابق")
        return

    deleted_count = 0
    for chat_id, msg_id in broadcasts:
        try:
            await bot.delete_message(chat_id, msg_id)
            deleted_count += 1
            logger.info(f"حُذفت رسالة البث من {chat_id}: {msg_id}")
        except Exception as e:
            logger.error(
                f"فشل حذف رسالة البث من {chat_id}: {msg_id} -- {e}", exc_info=True
            )

    await db.clear_last_broadcasts()
    await message.answer(f"تم محاولة حذف آخر رسالة بث من {deleted_count} مشتركين.")
    logger.info(f"انتهى أمر /delast: حذفت {deleted_count} رسائل بث")


@router.message(Command("send"), IsSourceChat())
async def cmd_send(message: Message, bot: Bot) -> None:
    """بث الرسالة المردود عليها إلى جميع المشتركين."""
    if not message.reply_to_message:
        await message.answer("يرجى الرد على الرسالة المراد بثها باستخدام الأمر /send")
        logger.warning(f"أمر /send بدون رد في المصدر: {message.chat.id}")
        return

    subscribers = await db.list_subscribers()
    if not subscribers:
        await message.answer("لا يوجد مشتركين حالياً للبث.")
        logger.warning("أمر /send فشل لأن قائمة المشتركين فارغة")
        return

    target = message.reply_to_message
    logger.info(
        f"أمر /send من المصدر {message.chat.id} "
        f"لبث الرسالة {target.message_id} إلى {len(subscribers)} مشتركين"
    )

    sent_count = await broadcast_message(bot, target, message.chat.id)
    await message.answer(f"تم بث الرسالة إلى {sent_count} مشتركين.")
