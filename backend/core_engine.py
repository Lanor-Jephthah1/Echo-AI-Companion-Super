"""Modular backend composition root.

Phase-2 refactor:
- Keeps legacy runtime behavior stable via `legacy_core_engine`.
- Routes extracted concerns (knowledge, summaries, sharing, providers) through modules.
"""

from typing import Any, Dict, Generator

import legacy_core_engine as _legacy
from core.knowledge import _build_bible_context, _build_knowledge_context
from core.providers import (
    gemini_generate_reply,
    nexttoken_generate_reply,
    use_nexttoken,
)
from core.sharing import (
    create_share_link as _create_share_link_impl,
    import_shared_thread as _import_shared_thread_impl,
    render_shared_link_page as _render_shared_link_page_impl,
)
from core.summarization import collective_thread_title as _collective_thread_title_impl
from core.summarization import summarize_thread as _summarize_thread_impl


# Patch legacy chat pipeline to use extracted modules.
_legacy._build_knowledge_context = _build_knowledge_context  # type: ignore[attr-defined]
_legacy._build_bible_context = _build_bible_context  # type: ignore[attr-defined]
_legacy._collective_thread_title = (  # type: ignore[attr-defined]
    lambda first_user_message, assistant_reply: _collective_thread_title_impl(
        first_user_message,
        assistant_reply,
        use_nexttoken=use_nexttoken,
        nexttoken_generate_reply=nexttoken_generate_reply,
        gemini_generate_reply=gemini_generate_reply,
    )
)


def get_threads(**args):
    return _legacy.get_threads(**args)


def create_thread(**args):
    return _legacy.create_thread(**args)


def delete_thread(**args):
    return _legacy.delete_thread(**args)


def chat_streaming(**args) -> Generator[Dict[str, Any], None, None]:
    return _legacy.chat_streaming(**args)


def get_chat_logs(limit: int = 200):
    return _legacy.get_chat_logs(limit=limit)


def get_email_health(**args):
    return _legacy.get_email_health(**args)


def send_test_email(**args):
    return _legacy.send_test_email(**args)


def summarize_thread(**args):
    return _summarize_thread_impl(
        thread_id=str(args.get("thread_id", "")).strip(),
        client_id=args.get("client_id"),
        load_threads=_legacy.load_threads,
        now_utc_iso=_legacy._now_utc_iso,
        use_nexttoken=use_nexttoken,
        nexttoken_generate_reply=nexttoken_generate_reply,
        gemini_generate_reply=gemini_generate_reply,
    )


def create_share_link(**args):
    return _create_share_link_impl(
        thread_id=str(args.get("thread_id", "")).strip(),
        client_id=_legacy._sanitize_client_id(args.get("client_id")),
        load_threads=_legacy.load_threads,
        now_utc_iso=_legacy._now_utc_iso,
        put_shared_snapshot=_legacy._put_shared_snapshot,
    )


def import_shared_thread(**args):
    return _import_shared_thread_impl(
        share_id=str(args.get("share_id", "")).strip(),
        sanitize_client_id=_legacy._sanitize_client_id,
        get_shared_snapshot=_legacy._get_shared_snapshot,
        load_threads=_legacy.load_threads,
        now_utc_iso=_legacy._now_utc_iso,
    )


def render_shared_link_page(**args) -> str:
    return _render_shared_link_page_impl(
        share_id=str(args.get("share_id", "")).strip(),
        get_shared_snapshot=_legacy._get_shared_snapshot,
    )


__all__ = [
    "get_threads",
    "create_thread",
    "delete_thread",
    "chat_streaming",
    "get_chat_logs",
    "get_email_health",
    "send_test_email",
    "summarize_thread",
    "create_share_link",
    "import_shared_thread",
    "render_shared_link_page",
]

