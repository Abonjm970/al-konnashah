# handlers/subscribe.py
"""معالجات الاشتراك: /start، الاشتراك التلقائي في الخاص، /stop."""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

import db

logger = logging.getLogger(__name__)
router = Router(name="subscribe")


@router.message(Command("start"), F.chat.type == "private")
async def start_subscribe(message: Message) -> None:
    """اشتراك المستخدم عند إرسال /start."""
    chat_id = message.chat.id
    if chat_id not in await db.list_subscribers():
        await db.add_subscriber(chat_id)
        await message.answer("تم الاشتراك بالبوت وستصلك الرسائل ✅")
        logger.info(f"اشترك مستخدم خاص عبر /start: {chat_id}")
    else:
        await message.answer("أنت بالفعل مشترك بالبوت.")
        logger.debug(f"المستخدم بالفعل مشترك عبر /start: {chat_id}")


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def auto_subscribe_private(message: Message) -> None:
    """أي رسالة نصية في الخاص -> اشتراك تلقائي."""
    chat_id = message.chat.id
    if chat_id not in await db.list_subscribers():
        await db.add_subscriber(chat_id)
        await message.answer("تم الاشتراك بالبوت وستصلك الرسائل ✅")
        logger.info(f"اشترك مستخدم خاص: {chat_id}")
    else:
        logger.debug(f"المستخدم بالفعل مشترك في الخاص: {chat_id}")


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    """إلغاء الاشتراك."""
    chat_id = message.chat.id
    await db.remove_subscriber(chat_id)
    await message.answer("تم إلغاء الاشتراك.")
    logger.info(f"أمر /stop: تم إلغاء الاشتراك للـ chat_id {chat_id}")
