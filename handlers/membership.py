# handlers/membership.py
"""معالج تحديثات عضوية البوت في المجموعات/القنوات (my_chat_member)."""
import asyncio
import logging

from aiogram import Bot, Router
from aiogram.types import ChatMemberUpdated

import config
import db

logger = logging.getLogger(__name__)
router = Router(name="membership")

# الحالات التي تعني أن البوت أصبح عضواً فعلياً
_JOINED_STATUSES = {"member", "administrator", "creator"}
# الحالات التي تعني مغادرة/حظر البوت
_LEFT_STATUSES = {"left", "kicked"}


def _is_source_chat(chat) -> bool:
    """True إذا كانت الدردشة من مصادر الرسائل المُهيّأة."""
    if not config.SOURCE_CHATS:
        return False
    chat_id_str = str(chat.id)
    username = (chat.username or "").lower()
    for src in config.SOURCE_CHATS:
        clean = src.lstrip("@").lower()
        if clean == username or clean == chat_id_str:
            return True
    return False


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot) -> None:
    """اشتراك تلقائي عند إضافة البوت، وإلغاء عند إزالته."""
    try:
        chat_id = event.chat.id
        new_status = event.new_chat_member.status
        old_status = event.old_chat_member.status
        logger.info(
            f"my_chat_member: chat_id={chat_id} old={old_status} new={new_status}"
        )

        if new_status in _JOINED_STATUSES:
            # تجاهل قنوات/مجموعات المصدر — لا تُسجَّل كمشتركين
            if _is_source_chat(event.chat):
                logger.info(f"تجاهل تسجيل مصدر الرسائل كمشترك: {chat_id}")
                return

            await db.add_subscriber(chat_id)
            try:
                sent = await bot.send_message(
                    chat_id,
                    "✅ تم الاشتراك بالبوت وستصلك الرسائل.\n"
                    "_(ستُحذف هذه الرسالة خلال 5 ثوانٍ)_",
                )
                await asyncio.sleep(5)
                await bot.delete_message(chat_id, sent.message_id)
                logger.info(f"تمت إضافة البوت كمشترك: {chat_id} (حُذفت رسالة الترحيب)")
            except Exception as e:
                logger.debug(f"تعذر إرسال/حذف رسالة الترحيب في {chat_id}: {e}")

        elif new_status in _LEFT_STATUSES:
            await db.remove_subscriber(chat_id)
            logger.info(f"البوت غادر/حُذف من {chat_id}: تم إلغاء الاشتراك تلقائياً")

    except Exception:
        logger.error("خطأ في معالج تحديث حالة العضو", exc_info=True)
