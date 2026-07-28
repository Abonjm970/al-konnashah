# bot_forwarder_auto.py
import asyncio
import os
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import sys
from dotenv import load_dotenv
from pyrogram import Client, filters, errors
from pyrogram.types import Message, ChatMemberUpdated
from pyrogram.enums import ChatMemberStatus

# --- تحميل الإعدادات من ملف .env ---
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", "forwarder.db")

# التحقق من وجود المتغيّرات الإلزامية
_required = {"API_ID": API_ID, "API_HASH": API_HASH, "BOT_TOKEN": BOT_TOKEN}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    sys.exit(f"❌ متغيّرات بيئة مفقودة: {', '.join(_missing)}  — أضفها في ملف .env")

API_ID = int(API_ID)

# مصادر الرسائل (قائمة مفصولة بفاصلة في .env)
SOURCE_CHATS = [
    s.strip() for s in os.getenv("SOURCE_CHATS", "").split(",") if s.strip()
]
FILTER_SOURCE_CHATS = []
for s in SOURCE_CHATS:
    clean_s = s.strip()
    if clean_s.startswith("-") and clean_s[1:].isdigit():
        FILTER_SOURCE_CHATS.append(int(clean_s))
    elif clean_s.isdigit():
        FILTER_SOURCE_CHATS.append(int(clean_s))
    else:
        FILTER_SOURCE_CHATS.append(clean_s.lstrip("@"))
# إعدادات معدل الإرسال
RATE_PER_SEC    = int(os.getenv("RATE_PER_SEC",  "25"))   # رسالة/ثانية
BATCH_SIZE      = int(os.getenv("BATCH_SIZE",    "200"))  # مشتركون/دفعة
_SLEEP_BETWEEN  = 1 / RATE_PER_SEC                        # ثانية بين كل رسالة
# ------------------------------

# --- إعداد السجل ---
LOG_FILE        = os.getenv("LOG_FILE",         "forwarder_bot.log")
LOG_MAX_BYTES   = int(os.getenv("LOG_MAX_BYTES",  "5242880"))  # 5 MiB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "3"))

_log_fmt = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# معالج الطرفية (stdout)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)

# معالج الملف الدوار
_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
logger = logging.getLogger(__name__)

app = Client("forwarder_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------- طلب الاشتراك عبر /start ----------
@app.on_message(filters.private & filters.command("start"))
async def start_subscribe(client: Client, message: Message):
    """اشتراك المستخدم عند إرسال /start."""
    chat_id = message.chat.id
    if chat_id not in list_subscribers():
        add_subscriber(chat_id)
        await message.reply_text("تم الاشتراك بالبوت وستصلك الرسائل ✅")
        logger.info(f"اشترك مستخدم خاص عبر /start: {chat_id}")
    else:
        await message.reply_text("أنت بالفعل مشترك بالبوت.")
        logger.debug(f"المستخدم بالفعل مشترك عبر /start: {chat_id}")


# ---------- قاعدة بيانات ----------
# اتصال مشترك واحد يعيش طوال دورة حياة البوت
_db_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    """يُعيد الاتصال المشترك، وينشئه إذا لم يكن موجوداً بعد."""
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        _db_conn.execute("PRAGMA journal_mode=WAL")  # أداء أفضل عند القراءة والكتابة
        _db_conn.execute("PRAGMA foreign_keys=ON")
    return _db_conn


def init_db():
    conn = get_db()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            chat_id INTEGER PRIMARY KEY,
            message_id INTEGER
        )""")
        conn.commit()
        logger.info("تم تهيئة قاعدة البيانات أو التأكد من وجود جدول المشتركين وجدول البث")
    except sqlite3.Error as e:
        logger.error(f"فشل تهيئة قاعدة البيانات: {e}", exc_info=True)
        raise


def add_subscriber(chat_id: int):
    try:
        get_db().execute("INSERT OR IGNORE INTO subscribers(chat_id) VALUES (?)", (chat_id,))
        get_db().commit()
        logger.info(f"تم إضافة مشترك جديد: {chat_id}")
    except sqlite3.Error as e:
        logger.error(f"فشل إضافة المشترك {chat_id}: {e}", exc_info=True)


def remove_subscriber(chat_id: int):
    try:
        get_db().execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        get_db().commit()
        logger.info(f"تم حذف المشترك: {chat_id}")
    except sqlite3.Error as e:
        logger.error(f"فشل حذف المشترك {chat_id}: {e}", exc_info=True)


def list_subscribers() -> list[int]:
    try:
        cur = get_db().execute("SELECT chat_id FROM subscribers")
        rows = [r[0] for r in cur.fetchall()]
        logger.debug(f"عدد المشتركين الحالي: {len(rows)}")
        return rows
    except sqlite3.Error as e:
        logger.error(f"فشل جلب قائمة المشتركين: {e}", exc_info=True)
        return []


def save_broadcast_message(chat_id: int, message_id: int):
    try:
        get_db().execute(
            "INSERT OR REPLACE INTO broadcasts(chat_id, message_id) VALUES (?, ?)",
            (chat_id, message_id)
        )
        get_db().commit()
        logger.debug(f"سجلت رسالة البث الأخيرة للدردشة {chat_id}: {message_id}")
    except sqlite3.Error as e:
        logger.error(f"فشل تسجيل رسالة البث للدردشة {chat_id}: {e}", exc_info=True)


def get_last_broadcasts() -> list[tuple[int, int]]:
    try:
        cur = get_db().execute("SELECT chat_id, message_id FROM broadcasts")
        return [(r[0], r[1]) for r in cur.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"فشل جلب سجل البث: {e}", exc_info=True)
        return []


def clear_last_broadcasts():
    try:
        get_db().execute("DELETE FROM broadcasts")
        get_db().commit()
        logger.debug("تم مسح سجل آخر رسائل البث")
    except sqlite3.Error as e:
        logger.error(f"فشل مسح سجل البث: {e}", exc_info=True)


# ---------- الاشتراك التلقائي ----------
def _is_source_chat(chat) -> bool:
    """True إذا كانت الدردشة من مصادر الرسائل المُهيّأة."""
    if not SOURCE_CHATS:
        return False
    chat_id_str = str(chat.id)
    username = (chat.username or "").lower()
    for src in SOURCE_CHATS:
        clean = src.lstrip("@").lower()
        if clean == username or clean == chat_id_str:
            return True
    return False


@app.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
def auto_subscribe_private(client: Client, message: Message):
    # أي رسالة في الخاص -> يسجل نفسه مشترك تلقائي
    chat_id = message.chat.id
    if chat_id not in list_subscribers():
        add_subscriber(chat_id)
        message.reply_text("تم الاشتراك بالبوت وستصلك الرسائل ✅")
        logger.info(f"اشترك مستخدم خاص: {chat_id}")
    else:
        logger.debug(f"المستخدم بالفعل مشترك في الخاص: {chat_id}")


@app.on_chat_member_updated()
async def on_chat_member_updated(client: Client, chat_member: ChatMemberUpdated):
    try:
        new_member = getattr(chat_member, "new_chat_member", None)
        old_member = getattr(chat_member, "old_chat_member", None)

        is_me = False
        if new_member and new_member.user and new_member.user.is_self:
            is_me = True
        elif old_member and old_member.user and old_member.user.is_self:
            is_me = True

        if not is_me:
            return

        chat_id    = chat_member.chat.id
        new_status = getattr(new_member, "status", None) if new_member else None
        old_status = getattr(old_member, "status", None) if old_member else None
        logger.info(f"chat_member_updated: chat_id={chat_id} old={old_status} new={new_status}")

        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            # تجاهل قنوات/مجموعات المصدر — لا تُسجَّل كمشتركين
            if _is_source_chat(chat_member.chat):
                logger.info(f"تجاهل تسجيل مصدر الرسائل كمشترك: {chat_id}")
                return

            add_subscriber(chat_id)
            try:
                sent = await client.send_message(
                    chat_id,
                    "✅ تم الاشتراك بالبوت وستصلك الرسائل.\n"
                    "_(ستُحذف هذه الرسالة خلال 5 ثوانٍ)_"
                )
                await asyncio.sleep(5)
                await client.delete_messages(chat_id, sent.id)
                logger.info(f"تمت إضافة البوت كمشترك: {chat_id} (حُذفت رسالة الترحيب)")
            except Exception as e:
                logger.debug(f"تعذر إرسال/حذف رسالة الترحيب في {chat_id}: {e}")

        elif new_status is None or new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            remove_subscriber(chat_id)
            logger.info(f"البوت غادر/حُذف من {chat_id}: تم إلغاء الاشتراك تلقائياً")

    except Exception as e:
        logger.error("خطأ في معالج تحديث حالة العضو", exc_info=True)


# ---------- أوامر إضافية (اختيارية) ----------
@app.on_message(filters.command("stop"))
async def cmd_stop(client: Client, message: Message):
    chat_id = message.chat.id
    remove_subscriber(chat_id)
    await message.reply_text("تم إلغاء الاشتراك.")
    logger.info(f"أمر /stop: تم إلغاء الاشتراك للـ chat_id {chat_id}")


@app.on_message(filters.chat(FILTER_SOURCE_CHATS) & filters.command("list"))
async def cmd_list(client: Client, message: Message):
    subs = list_subscribers()
    text = f"عدد المشتركين الحالي: {len(subs)}"
    await message.reply_text(text)
    logger.info(f"أمر /list: تم عرض عدد المشتركين {len(subs)}")


@app.on_message(filters.chat(FILTER_SOURCE_CHATS) & filters.command("delast"))
async def cmd_delast(client: Client, message: Message):
    broadcasts = get_last_broadcasts()
    if not broadcasts:
        await message.reply_text("لا توجد رسالة بث سابقة ليتم حذفها.")
        logger.warning("أمر /delast فشل لعدم وجود سجل بث سابق")
        return

    deleted_count = 0
    for chat_id, msg_id in broadcasts:
        try:
            await client.delete_messages(chat_id, msg_id)
            deleted_count += 1
            logger.info(f"حُذفت رسالة البث من {chat_id}: {msg_id}")
        except Exception as e:
            logger.error(f"فشل حذف رسالة البث من {chat_id}: {msg_id} -- {e}", exc_info=True)

    clear_last_broadcasts()
    await message.reply_text(f"تم محاولة حذف آخر رسالة بث من {deleted_count} مشتركين.")
    logger.info(f"انتهى أمر /delast: حذفت {deleted_count} رسائل بث")


# ---------- بث برسالة /send من المصادر فقط ----------
async def broadcast_message(client: Client, target: Message, source_chat_id: int) -> int:
    """
    يُرسل نسخة من target إلى جميع المشتركين مع تطبيق rate-limit
    لتفادي FloodWait.
    يُعيد عدد الرسائل المُرسلة بنجاح.
    """
    subscribers = list_subscribers()
    total       = len(subscribers)
    sent_count  = 0

    logger.info(
        f"بدء البث: {total} مشترك | "
        f"معدل={RATE_PER_SEC} رسالة/ث | دفعة={BATCH_SIZE}"
    )

    for batch_start in range(0, total, BATCH_SIZE):
        batch = subscribers[batch_start : batch_start + BATCH_SIZE]

        for sub in batch:
            if sub == source_chat_id:
                logger.debug(f"تخطي المصدر نفسه: {sub}")
                continue

            try:
                copied = await client.copy_message(
                    chat_id=sub,
                    from_chat_id=target.chat.id,
                    message_id=target.id,
                )
                save_broadcast_message(sub, copied.id)
                sent_count += 1
                logger.info(f"بث الرسالة إلى: {sub} (message_id={copied.id})")

            except errors.FloodWait as fw:
                wait = fw.value + 1          # +1 ثانية هامش أمان
                logger.warning(f"⚠️ FloodWait: الانتظار {wait}s ثم الاستئناف")
                await asyncio.sleep(wait)
                try:                         # إعادة المحاولة بعد الانتظار
                    copied = await client.copy_message(
                        chat_id=sub,
                        from_chat_id=target.chat.id,
                        message_id=target.id,
                    )
                    save_broadcast_message(sub, copied.id)
                    sent_count += 1
                    logger.info(f"بث الرسالة إلى: {sub} بعد FloodWait")
                except Exception as retry_e:
                    logger.error(f"فشل إعادة المحاولة إلى {sub}: {retry_e}", exc_info=True)

            except Exception as e:
                logger.error(f"فشل البث إلى {sub}: {e}", exc_info=True)

            # فاصل زمني بين كل رسالة
            await asyncio.sleep(_SLEEP_BETWEEN)

        # انتظار إضافي بين الدفعات
        if batch_start + BATCH_SIZE < total:
            logger.info(f"🕒 انتهت الدفعة، انتظار 1s قبل الدفعة التالية")
            await asyncio.sleep(1)

    logger.info(f"✅ انتهى البث: أُرسل إلى {sent_count}/{total} مشترك")
    return sent_count


@app.on_message(filters.chat(FILTER_SOURCE_CHATS) & filters.command("send"))
async def cmd_send(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("يرجى الرد على الرسالة المراد بثها باستخدام الأمر /send")
        logger.warning(f"أمر /send بدون رد في المصدر: {message.chat.id}")
        return

    subscribers = list_subscribers()
    if not subscribers:
        await message.reply_text("لا يوجد مشتركين حالياً للبث.")
        logger.warning("أمر /send فشل لأن قائمة المشتركين فارغة")
        return

    target = message.reply_to_message
    logger.info(
        f"أمر /send من المصدر {message.chat.id} "
        f"لبث الرسالة {target.id} إلى {len(subscribers)} مشتركين"
    )

    sent_count = await broadcast_message(client, target, message.chat.id)
    await message.reply_text(f"تم بث الرسالة إلى {sent_count} مشتركين.")


# ---------- تشغيل ----------
if __name__ == "__main__":
    init_db()
    logger.info("Bot is starting...")
    app.run()
