# test_units.py — اختبارات محلية بدون توكن حقيقي (جلسة API مزيّفة)
"""يتحقق من: قاعدة البيانات، معالجات الاشتراك، أوامر الإدارة، وتطبيق ASGI."""
import asyncio
import json
import os
import sys

os.environ.setdefault("BOT_TOKEN", "123:FAKE")
os.environ["DB_FILE"] = "/tmp/opencode/test_forwarder.db"
os.environ["SOURCE_CHATS"] = "-100999,@sourceschan"

# إعادة تحميل نظيفة
for m in list(sys.modules):
    if m in ("config", "db", "core", "broadcast") or m.startswith("handlers"):
        del sys.modules[m]

if os.path.exists(os.environ["DB_FILE"]):
    os.remove(os.environ["DB_FILE"])

import config  # noqa: E402
import db  # noqa: E402
from core import create_dispatcher  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.types import Update  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods.base import TelegramMethod, TelegramType  # noqa: E402


class FakeSession(BaseSession):
    """جلسة API مزيّفة: تسجّل الطلبات وتعيد نتائج مصطنعة بدل الاتصال بتيليجرام."""

    def __init__(self):
        super().__init__()
        self._requests: list[tuple[str, dict]] = []

    async def close(self):
        pass

    async def make_request(self, bot, method: TelegramMethod[TelegramType], timeout=None):
        data = method.model_dump(exclude_none=True)
        self._requests.append((method.__api_method__, data))
        # نتائج مصطنعة حسب نوع الطلب (تُحلَّل إلى كائنات aiogram كما تفعل الجلسة الحقيقية)
        if method.__api_method__ == "sendMessage":
            raw = {"message_id": 500, "chat": {"id": data.get("chat_id"), "type": "private"}, "date": 1}
        elif method.__api_method__ == "copyMessage":
            raw = {"message_id": 600}
        else:
            raw = True
        from aiogram.methods.base import Response
        response_type = Response[method.__returning__]
        response = response_type.model_validate(
            {"ok": True, "result": raw}, context={"bot": bot}
        )
        return response.result

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b""

    def requests(self):
        class R:
            def __init__(self, m, d):
                self.method = m
                self.data = d
        return [R(m, d) for m, d in self._requests]


class MockedBot(Bot):
    def __init__(self):
        super().__init__("123:FAKE", session=FakeSession())

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


def make_message_update(text, chat_id, uid=111, chat_type="private", username=None, reply_to=None):
    chat = {"id": chat_id, "type": chat_type}
    if username:
        chat["username"] = username
    msg = {
        "message_id": 10,
        "from": {"id": uid, "is_bot": False, "first_name": "T"},
        "chat": chat,
        "date": 1700000000,
        "text": text,
    }
    if text.startswith("/"):
        msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    if reply_to:
        msg["reply_to_message"] = reply_to
    return {"update_id": 1, "message": msg}


async def main():
    print("== اختبار قاعدة البيانات (sqlite) ==")
    await db.init_db()
    await db.add_subscriber(1001)
    await db.add_subscriber(1002)
    await db.add_subscriber(1001)  # تكرار — يجب تجاهله
    subs = await db.list_subscribers()
    check("إضافة مشتركَين بدون تكرار", sorted(subs) == [1001, 1002])

    await db.remove_subscriber(1002)
    check("حذف مشترك", await db.list_subscribers() == [1001])

    await db.save_broadcast_message(1001, 55)
    check("حفظ/قراءة سجل البث", await db.get_last_broadcasts() == [(1001, 55)])
    await db.clear_last_broadcasts()
    check("مسح سجل البث", await db.get_last_broadcasts() == [])

    print("== اختبار المعالجات عبر Dispatcher (API مزيّف) ==")
    bot = MockedBot()
    dp = create_dispatcher()

    # /start من مستخدم جديد
    await dp.feed_update(bot, Update(**make_message_update("/start", 2001)))
    check("/start يضيف مشتركاً", 2001 in await db.list_subscribers())

    # رسالة خاصة عادية -> اشتراك تلقائي
    await dp.feed_update(bot, Update(**make_message_update("مرحبا", 2002)))
    check("الاشتراك التلقائي برسالة خاصة", 2002 in await db.list_subscribers())

    # /stop
    await dp.feed_update(bot, Update(**make_message_update("/stop", 2002)))
    check("/stop يحذف المشترك", 2002 not in await db.list_subscribers())

    # /list من غير المصدر — يجب تجاهله
    before = await db.list_subscribers()
    await dp.feed_update(bot, Update(**make_message_update("/list", 3003, chat_type="group")))
    check("/list من غير المصدر لا يُغيّر شيئاً", await db.list_subscribers() == before)

    # /list من المصدر بالمعرّف
    await dp.feed_update(bot, Update(**make_message_update("/list", -100999, chat_type="supergroup")))
    reqs = bot.session.requests()
    check("/list من المصدر (id) يرد", any("عدد المشتركين" in str(r.data.get("text", "")) for r in reqs if r.method == "sendMessage"))

    # /send من المصدر بدون رد
    bot.session.reset_history() if hasattr(bot.session, "reset_history") else None
    await dp.feed_update(bot, Update(**make_message_update("/send", -100999, chat_type="supergroup")))
    reqs = bot.session.requests()
    check("/send بدون رد يطلب الرد", any("يرجى الرد" in str(r.data.get("text", "")) for r in reqs if r.method == "sendMessage"))

    # /send من المصدر مع رد -> بث فعلي إلى المشتركين (2001 فقط)
    replied = {
        "message_id": 77,
        "from": {"id": 999, "is_bot": False, "first_name": "A"},
        "chat": {"id": -100999, "type": "supergroup"},
        "date": 1700000000,
        "text": "رسالة للبث",
    }
    await dp.feed_update(bot, Update(**make_message_update("/send", -100999, chat_type="supergroup", reply_to=replied)))
    reqs = bot.session.requests()
    copy_targets = [r.data.get("chat_id") for r in reqs if r.method == "copyMessage"]
    check(f"/send يبث إلى المشتركين (copyMessage -> {copy_targets})", 2001 in copy_targets)
    check("سجل البث محفوظ بعد /send", len(await db.get_last_broadcasts()) >= 1)

    # /delast من المصدر
    await dp.feed_update(bot, Update(**make_message_update("/delast", -100999, chat_type="supergroup")))
    reqs = bot.session.requests()
    check("/delast يستدعي deleteMessage", any(r.method == "deleteMessage" for r in reqs))
    check("/delast يمسح السجل", await db.get_last_broadcasts() == [])

    # my_chat_member: إضافة البوت لمجموعة جديدة
    upd = {
        "update_id": 99,
        "my_chat_member": {
            "chat": {"id": -100555, "type": "supergroup", "title": "G"},
            "from": {"id": 111, "is_bot": False, "first_name": "T"},
            "date": 1700000000,
            "old_chat_member": {"user": {"id": 123, "is_bot": True, "first_name": "B"}, "status": "left"},
            "new_chat_member": {"user": {"id": 123, "is_bot": True, "first_name": "B"}, "status": "member"},
        },
    }
    await dp.feed_update(bot, Update(**upd))
    await asyncio.sleep(0.1)
    check("إضافة البوت لمجموعة تسجّلها مشتركاً", -100555 in await db.list_subscribers())

    # my_chat_member: إضافة البوت لدردشة مصدر -> يجب تجاهلها
    upd_src = {
        "update_id": 100,
        "my_chat_member": {
            "chat": {"id": -100999, "type": "channel", "title": "SRC"},
            "from": {"id": 111, "is_bot": False, "first_name": "T"},
            "date": 1700000000,
            "old_chat_member": {"user": {"id": 123, "is_bot": True, "first_name": "B"}, "status": "left"},
            "new_chat_member": {"user": {"id": 123, "is_bot": True, "first_name": "B"}, "status": "member"},
        },
    }
    await dp.feed_update(bot, Update(**upd_src))
    check("دردشة المصدر لا تُسجَّل كمشترك", -100999 not in await db.list_subscribers())

    # my_chat_member: طرد البوت -> إلغاء اشتراك
    upd_kick = {
        "update_id": 101,
        "my_chat_member": {
            "chat": {"id": -100555, "type": "supergroup", "title": "G"},
            "from": {"id": 111, "is_bot": False, "first_name": "T"},
            "date": 1700000000,
            "old_chat_member": {"user": {"id": 123, "is_bot": True, "first_name": "B"}, "status": "member"},
            "new_chat_member": {"user": {"id": 123, "is_bot": True, "first_name": "B"}, "status": "kicked", "until_date": 0},
        },
    }
    await dp.feed_update(bot, Update(**upd_kick))
    check("طرد البوت يلغي اشتراك المجموعة", -100555 not in await db.list_subscribers())

    await bot.session.close()

    print("== اختبار تطبيق ASGI (api/index) ==")
    os.environ["MODE"] = "webhook"
    os.environ["WEBHOOK_URL"] = "https://example.vercel.app"
    os.environ["WEBHOOK_SECRET"] = "s3cr3t"
    for m in list(sys.modules):
        if m in ("config", "api.index", "api"):
            del sys.modules[m]
    from api.index import app as asgi_app

    async def call_asgi(method, path, body=b"", headers=None):
        sent = []
        headers = headers or []
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(k.encode(), v.encode()) for k, v in headers],
        }
        messages = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(msg):
            sent.append(msg)

        await asgi_app(scope, receive, send)
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        resp_body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return status, resp_body

    st, _ = await call_asgi("GET", "/")
    check("GET / يعيد 200 (فحص صحي)", st == 200)

    st, _ = await call_asgi("POST", config.WEBHOOK_PATH, b"{}", [])
    check("POST بدون سر -> 403", st == 403)

    st, _ = await call_asgi(
        "POST", config.WEBHOOK_PATH, b"not-json",
        [("x-telegram-bot-api-secret-token", "wrong")],
    )
    check("POST بسر خاطئ -> 403", st == 403)

    st, _ = await call_asgi(
        "POST", config.WEBHOOK_PATH, b"not-json",
        [("x-telegram-bot-api-secret-token", "s3cr3t")],
    )
    check("POST بجسم غير صالح -> 400", st == 400)

    upd = make_message_update("/start", 4001)
    st, _ = await call_asgi(
        "POST", config.WEBHOOK_PATH, json.dumps(upd).encode(),
        [("x-telegram-bot-api-secret-token", "s3cr3t")],
    )
    check("POST بتحديث صالح -> 200", st == 200)
    check("التحديث عبر webhook أضاف المشترك", 4001 in await db.list_subscribers())

    print(f"\n{'='*40}\nالنتيجة: {PASS} نجح، {FAIL} فشل")
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
