"""Modular backend composition root.

Phase-2 refactor:
- Keeps legacy runtime behavior stable via `legacy_core_engine`.
- Routes extracted concerns (knowledge, summaries, sharing, providers, storage) through modules.
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
from core.storage_backend import StorageBackend
from core.storage_ops import StorageOps
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

# Patch legacy persistence pipeline to use extracted storage modules.
_storage_backend = StorageBackend(
    data_dir=_legacy.DATA_DIR,  # type: ignore[attr-defined]
    chat_log_file=_legacy.CHAT_LOG_FILE,  # type: ignore[attr-defined]
    email_events_file=_legacy.EMAIL_EVENTS_FILE,  # type: ignore[attr-defined]
    shared_links_file=_legacy.SHARED_LINKS_FILE,  # type: ignore[attr-defined]
    shared_snapshots_file=_legacy.SHARED_SNAPSHOTS_FILE,  # type: ignore[attr-defined]
)
_storage = StorageOps(
    backend=_storage_backend,
    sanitize_client_id=_legacy._sanitize_client_id,  # type: ignore[attr-defined]
    threads_file_for_client=_legacy._threads_file_for_client,  # type: ignore[attr-defined]
    now_utc_iso=_legacy._now_utc_iso,  # type: ignore[attr-defined]
    parse_iso_utc=_legacy._parse_iso_utc,  # type: ignore[attr-defined]
    parse_any_timestamp=_legacy._parse_any_timestamp,  # type: ignore[attr-defined]
    format_human_timestamp=_legacy._format_human_timestamp,  # type: ignore[attr-defined]
    detect_sentiment=_legacy._detect_sentiment,  # type: ignore[attr-defined]
    sentiment_to_score=_legacy._sentiment_to_score,  # type: ignore[attr-defined]
)
_legacy._db_url = _storage_backend.db_url  # type: ignore[attr-defined]
_legacy._db_enabled = _storage_backend.db_enabled  # type: ignore[attr-defined]
_legacy._db_conn = _storage_backend.db_conn  # type: ignore[attr-defined]
_legacy._db_init = _storage_backend.db_init  # type: ignore[attr-defined]
_legacy._mongo_uri = _storage_backend.mongo_uri  # type: ignore[attr-defined]
_legacy._mongo_enabled = _storage_backend.mongo_enabled  # type: ignore[attr-defined]
_legacy._mongo_db = _storage_backend.mongo_db  # type: ignore[attr-defined]
_legacy.ensure_data_dir = _storage.ensure_data_dir  # type: ignore[attr-defined]
_legacy.load_threads = _storage.load_threads  # type: ignore[attr-defined]
_legacy.save_threads = _storage.save_threads  # type: ignore[attr-defined]
_legacy.get_chat_logs = _storage.get_chat_logs  # type: ignore[attr-defined]
_legacy._reconstruct_events_from_threads = _storage.reconstruct_events_from_threads  # type: ignore[attr-defined]
_legacy._append_chat_log = (  # type: ignore[attr-defined]
    lambda client_ip, client_id, user_message, bot_reply, sentiment, sentiment_score: _storage.append_chat_log(
        client_ip=client_ip,
        client_id=client_id,
        user_message=user_message,
        bot_reply=bot_reply,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
    )
)
_legacy._get_email_event = _storage.get_email_event  # type: ignore[attr-defined]
_legacy._put_email_event = _storage.put_email_event  # type: ignore[attr-defined]
_legacy._email_event_recent = _storage.email_event_recent  # type: ignore[attr-defined]
_legacy._list_email_events = _storage.list_email_events  # type: ignore[attr-defined]
_legacy._get_shared_link = _storage.get_shared_link  # type: ignore[attr-defined]
_legacy._put_shared_link = _storage.put_shared_link  # type: ignore[attr-defined]
_legacy._get_shared_snapshot = _storage.get_shared_snapshot  # type: ignore[attr-defined]
_legacy._put_shared_snapshot = _storage.put_shared_snapshot  # type: ignore[attr-defined]


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
