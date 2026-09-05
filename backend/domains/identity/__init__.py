"""
Identity domain: User accounts, authentication tokens, admin sessions, and 2FA.
"""
from routes.admin import router as admin_router
from routes.user import router as user_router

__all__ = ["user_router", "admin_router"]
