"""Backend facade module.

This file intentionally stays small and re-exports service-layer functions.
Core legacy implementation lives in `backend/core_engine.py`.
"""

from services.threads_service import get_threads, create_thread, delete_thread
from services.chat_service import chat_streaming, summarize_thread
from services.share_service import create_share_link, import_shared_thread, render_shared_link_page
from services.admin_service import get_chat_logs, get_email_health, send_test_email

__all__ = [
    "get_threads",
    "create_thread",
    "delete_thread",
    "chat_streaming",
    "summarize_thread",
    "create_share_link",
    "import_shared_thread",
    "render_shared_link_page",
    "get_chat_logs",
    "get_email_health",
    "send_test_email",
]
