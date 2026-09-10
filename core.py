# core.py
"""بناء كائنَي Bot و Dispatcher المشتركين بين كل أوضاع التشغيل."""
import logging
import os
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher

import config
from handlers import get_router


def setup_logging() -> None:
    """إعداد السجلات: stdout دائماً + ملف دوّار ما لم نكن على Vercel."""
    log_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_fmt)

    handlers: list[logging.Handler] = [console_handler]

    # على Vercel نظام الملفات للقراءة فقط — نكتفي بـ stdout
    if not os.environ.get("VERCEL"):
        file_handler = RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(log_fmt)
        handlers.append(file_handler)

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def create_bot() -> Bot:
    """إنشاء كائن Bot جديد (يُفضَّل كائن لكل طلب في البيئات serverless)."""
    return Bot(token=config.BOT_TOKEN)


_dispatcher: Dispatcher | None = None


def create_dispatcher() -> Dispatcher:
    """يُعيد Dispatcher مشتركاً (يُنشأ مرة واحدة — الموجّهات لا تقبل أكثر من أب)."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(get_router())
    return _dispatcher
