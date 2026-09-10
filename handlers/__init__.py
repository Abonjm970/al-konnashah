# handlers/__init__.py
"""تجميع موجّهات (routers) المعالجات."""
from aiogram import Router

from . import subscribe, membership, admin


def get_router() -> Router:
    """يُعيد الموجّه الرئيسي الذي يضم كل المعالجات."""
    root = Router()
    root.include_router(subscribe.router)
    root.include_router(membership.router)
    root.include_router(admin.router)
    return root
