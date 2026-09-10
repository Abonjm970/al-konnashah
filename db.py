# db.py
"""طبقة قاعدة البيانات: sqlite محلياً أو Turso (عبر واجهة HTTP) عند توفر بيانات الاتصال.

واجهة موحّدة غير متزامنة (async) بغضّ النظر عن المحرك المستخدم.
عميل Turso مصغّر مبني على aiohttp (موجودة أصلاً مع aiogram) — بلا اعتماديات إضافية.
"""
import base64
import logging
import sqlite3

import aiohttp

import config

logger = logging.getLogger(__name__)

_USE_TURSO = bool(config.TURSO_DATABASE_URL)

# ---------- محرك sqlite (محلي) ----------
_sqlite_conn: sqlite3.Connection | None = None


def _get_sqlite() -> sqlite3.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(config.DB_FILE, check_same_thread=False)
        _sqlite_conn.execute("PRAGMA journal_mode=WAL")
        _sqlite_conn.execute("PRAGMA foreign_keys=ON")
    return _sqlite_conn


# ---------- عميل Turso HTTP (بروتوكول hrana v2) ----------
_http_session: aiohttp.ClientSession | None = None


def _get_http_session() -> aiohttp.ClientSession:
    """جلسة HTTP مشتركة (تُنشأ كسولاً داخل حلقة الأحداث)."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


def _turso_url() -> str:
    url = config.TURSO_DATABASE_URL.strip().rstrip("/")
    # libsql://db-org.turso.io -> https://db-org.turso.io
    if url.startswith("libsql://"):
        url = "https://" + url.removeprefix("libsql://")
    return f"{url}/v2/pipeline"


def _encode_arg(value):
    """ترميز معامل إلى صيغة hrana."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


def _decode_value(v):
    """فك ترميز قيمة قادمة من hrana."""
    t = v.get("type")
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "null":
        return None
    if t == "blob":
        return base64.b64decode(v["base64"])
    return v.get("value")  # text


async def _turso_execute(sql: str, params: list | tuple = ()) -> list[tuple]:
    """تنفيذ استعلام واحد على Turso وإعادة الصفوف كقائمة tuples."""
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [_encode_arg(p) for p in params]}},
            {"type": "close"},
        ]
    }
    headers = {"Authorization": f"Bearer {config.TURSO_AUTH_TOKEN}"}
    async with _get_http_session().post(_turso_url(), json=payload, headers=headers) as resp:
        data = await resp.json(content_type=None)

    results = data.get("results", [])
    first = results[0] if results else {}
    if first.get("type") == "error":
        raise RuntimeError(f"خطأ Turso: {first.get('error', {}).get('message')}")
    response = first.get("response", {})
    if response.get("type") != "execute":
        return []
    rows = response.get("result", {}).get("rows", [])
    return [tuple(_decode_value(v) for v in row) for row in rows]


# ---------- التهيئة ----------
_CREATE_SUBSCRIBERS = """
CREATE TABLE IF NOT EXISTS subscribers (
    chat_id INTEGER PRIMARY KEY
)"""
_CREATE_BROADCASTS = """
CREATE TABLE IF NOT EXISTS broadcasts (
    chat_id INTEGER PRIMARY KEY,
    message_id INTEGER
)"""


async def init_db() -> None:
    """إنشاء الجداول إن لم تكن موجودة."""
    try:
        if _USE_TURSO:
            await _turso_execute(_CREATE_SUBSCRIBERS)
            await _turso_execute(_CREATE_BROADCASTS)
        else:
            conn = _get_sqlite()
            conn.execute(_CREATE_SUBSCRIBERS)
            conn.execute(_CREATE_BROADCASTS)
            conn.commit()
        logger.info("تم تهيئة قاعدة البيانات (%s)", "Turso" if _USE_TURSO else "sqlite")
    except Exception as e:
        logger.error(f"فشل تهيئة قاعدة البيانات: {e}", exc_info=True)
        raise


# ---------- المشتركون ----------
async def add_subscriber(chat_id: int) -> None:
    try:
        if _USE_TURSO:
            await _turso_execute(
                "INSERT OR IGNORE INTO subscribers(chat_id) VALUES (?)", [chat_id]
            )
        else:
            conn = _get_sqlite()
            conn.execute("INSERT OR IGNORE INTO subscribers(chat_id) VALUES (?)", (chat_id,))
            conn.commit()
        logger.info(f"تم إضافة مشترك جديد: {chat_id}")
    except Exception as e:
        logger.error(f"فشل إضافة المشترك {chat_id}: {e}", exc_info=True)


async def remove_subscriber(chat_id: int) -> None:
    try:
        if _USE_TURSO:
            await _turso_execute("DELETE FROM subscribers WHERE chat_id = ?", [chat_id])
        else:
            conn = _get_sqlite()
            conn.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
            conn.commit()
        logger.info(f"تم حذف المشترك: {chat_id}")
    except Exception as e:
        logger.error(f"فشل حذف المشترك {chat_id}: {e}", exc_info=True)


async def list_subscribers() -> list[int]:
    try:
        if _USE_TURSO:
            rows = await _turso_execute("SELECT chat_id FROM subscribers")
        else:
            cur = _get_sqlite().execute("SELECT chat_id FROM subscribers")
            rows = cur.fetchall()
        result = [r[0] for r in rows]
        logger.debug(f"عدد المشتركين الحالي: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"فشل جلب قائمة المشتركين: {e}", exc_info=True)
        return []


# ---------- سجل البث ----------
async def save_broadcast_message(chat_id: int, message_id: int) -> None:
    try:
        if _USE_TURSO:
            await _turso_execute(
                "INSERT OR REPLACE INTO broadcasts(chat_id, message_id) VALUES (?, ?)",
                [chat_id, message_id],
            )
        else:
            conn = _get_sqlite()
            conn.execute(
                "INSERT OR REPLACE INTO broadcasts(chat_id, message_id) VALUES (?, ?)",
                (chat_id, message_id),
            )
            conn.commit()
        logger.debug(f"سجلت رسالة البث الأخيرة للدردشة {chat_id}: {message_id}")
    except Exception as e:
        logger.error(f"فشل تسجيل رسالة البث للدردشة {chat_id}: {e}", exc_info=True)


async def get_last_broadcasts() -> list[tuple[int, int]]:
    try:
        if _USE_TURSO:
            rows = await _turso_execute("SELECT chat_id, message_id FROM broadcasts")
        else:
            cur = _get_sqlite().execute("SELECT chat_id, message_id FROM broadcasts")
            rows = cur.fetchall()
        return [(r[0], r[1]) for r in rows]
    except Exception as e:
        logger.error(f"فشل جلب سجل البث: {e}", exc_info=True)
        return []


async def clear_last_broadcasts() -> None:
    try:
        if _USE_TURSO:
            await _turso_execute("DELETE FROM broadcasts")
        else:
            conn = _get_sqlite()
            conn.execute("DELETE FROM broadcasts")
            conn.commit()
        logger.debug("تم مسح سجل آخر رسائل البث")
    except Exception as e:
        logger.error(f"فشل مسح سجل البث: {e}", exc_info=True)
