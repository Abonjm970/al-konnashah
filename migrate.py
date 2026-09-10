# migrate.py
"""سكربت ترحيل البيانات من قاعدة sqlite المحلية (forwarder.db) إلى Turso.

يُنفَّذ مرة واحدة محلياً بعد ضبط TURSO_DATABASE_URL و TURSO_AUTH_TOKEN في .env:

    python migrate.py

القاعدة المحلية لا تُعدَّل ولا تُحذف — النسخ فقط.
"""
import asyncio
import sqlite3
import sys

import config
import db
from core import setup_logging

setup_logging()


def read_local(db_file: str) -> tuple[list[int], list[tuple[int, int]]]:
    """قراءة المشتركين وسجل البث من قاعدة sqlite المحلية."""
    conn = sqlite3.connect(db_file)
    try:
        subs = [r[0] for r in conn.execute("SELECT chat_id FROM subscribers")]
        broadcasts = [
            (r[0], r[1])
            for r in conn.execute("SELECT chat_id, message_id FROM broadcasts")
        ]
        return subs, broadcasts
    finally:
        conn.close()


async def main() -> None:
    if not config.TURSO_DATABASE_URL:
        sys.exit("❌ يجب ضبط TURSO_DATABASE_URL و TURSO_AUTH_TOKEN في .env أولاً")

    subs, broadcasts = read_local(config.DB_FILE)
    print(f"📦 القاعدة المحلية ({config.DB_FILE}): {len(subs)} مشترك، {len(broadcasts)} سجل بث")

    if not subs and not broadcasts:
        print("لا توجد بيانات للترحيل.")
        return

    answer = input("هل تريد المتابعة بالترحيل إلى Turso؟ [y/N] ").strip().lower()
    if answer != "y":
        print("أُلغي الترحيل.")
        return

    await db.init_db()  # ينشئ الجداول في Turso إن لم تكن موجودة

    for chat_id in subs:
        await db.add_subscriber(chat_id)
    for chat_id, message_id in broadcasts:
        await db.save_broadcast_message(chat_id, message_id)

    # تحقق
    migrated_subs = await db.list_subscribers()
    migrated_broadcasts = await db.get_last_broadcasts()
    print(f"✅ اكتمل الترحيل: {len(migrated_subs)} مشترك، {len(migrated_broadcasts)} سجل بث في Turso")

    missing = set(subs) - set(migrated_subs)
    if missing:
        print(f"⚠️ مشتركون لم يُرحَّلوا: {sorted(missing)}")
    else:
        print("✅ التحقق ناجح — كل المشتركين موجودون في Turso")


if __name__ == "__main__":
    asyncio.run(main())
