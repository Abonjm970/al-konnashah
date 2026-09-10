# config.py
"""تحميل الإعدادات من متغيرات البيئة والتحقق منها."""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# --- المتغيرات الإلزامية ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

_missing = [k for k, v in {"BOT_TOKEN": BOT_TOKEN}.items() if not v]
if _missing:
    sys.exit(f"❌ متغيّرات بيئة مفقودة: {', '.join(_missing)}  — أضفها في ملف .env")

# --- مصادر الرسائل (قائمة مفصولة بفاصلة) ---
SOURCE_CHATS = [
    s.strip() for s in os.getenv("SOURCE_CHATS", "").split(",") if s.strip()
]

FILTER_SOURCE_CHATS: list[int | str] = []
for s in SOURCE_CHATS:
    clean_s = s.strip()
    if clean_s.startswith("-") and clean_s[1:].isdigit():
        FILTER_SOURCE_CHATS.append(int(clean_s))
    elif clean_s.isdigit():
        FILTER_SOURCE_CHATS.append(int(clean_s))
    else:
        FILTER_SOURCE_CHATS.append(clean_s.lstrip("@"))

# --- إعدادات معدل الإرسال ---
RATE_PER_SEC = int(os.getenv("RATE_PER_SEC", "25"))   # رسالة/ثانية
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "200"))      # مشتركون/دفعة
SLEEP_BETWEEN = 1 / RATE_PER_SEC                      # ثانية بين كل رسالة

# --- قاعدة البيانات ---
DB_FILE = os.getenv("DB_FILE", "forwarder.db")
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

# --- وضع التشغيل ---
MODE = os.getenv("MODE", "polling").lower()           # polling | webhook
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")            # مثل https://al-konnashah.vercel.app
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")      # نص عشوائي للتحقق من تيليجرام
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", "8080"))

if MODE == "webhook" and not WEBHOOK_URL:
    sys.exit("❌ MODE=webhook يتطلب ضبط WEBHOOK_URL")

# --- السجلات ---
LOG_FILE = os.getenv("LOG_FILE", "forwarder_bot.log")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "5242880"))  # 5 MiB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "3"))
