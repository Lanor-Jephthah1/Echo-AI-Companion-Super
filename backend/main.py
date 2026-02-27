import os
import json
import time
import re
import glob
import hashlib
import hmac
import base64
import smtplib
import html
import secrets
from contextlib import contextmanager
import urllib.request
import urllib.error
from typing import Generator, Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
try:
    from nexttoken import NextToken
except Exception:
    NextToken = None

# Path for storage
# Vercel functions can write to /tmp only. Local dev uses backend/data.
if os.environ.get("VERCEL"):
    DATA_DIR = os.path.join("/tmp", "echo_data")
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CHAT_LOG_FILE = os.path.join(DATA_DIR, "chat_logs.jsonl")
EMAIL_EVENTS_FILE = os.path.join(DATA_DIR, "email_events.json")
SHARED_LINKS_FILE = os.path.join(DATA_DIR, "shared_links.json")
SHARED_SNAPSHOTS_FILE = os.path.join(DATA_DIR, "shared_snapshots.json")
_DB_READY = False
_MONGO_CLIENT = None
_KB_CACHE = {"sig": "", "sections": []}
_BIBLE_RAG_CACHE = {"mtime": 0.0, "chunks": []}


# -------------------------
# Storage helpers
# -------------------------
def _sanitize_client_id(client_id: Optional[str]) -> str:
    raw = str(client_id or "anon").strip()
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", raw)[:64]
    return safe or "anon"


def _threads_file_for_client(client_id: Optional[str]) -> str:
    safe_client_id = _sanitize_client_id(client_id)
    return os.path.join(DATA_DIR, f"threads_{safe_client_id}.json")


def _knowledge_file_paths() -> List[str]:
    env_paths = os.environ.get("ECHO_KB_FILES", "").strip()
    if env_paths:
        out = []
        for p in env_paths.split(","):
            raw = p.strip()
            if not raw:
                continue
            out.append(raw if os.path.isabs(raw) else os.path.join(os.path.dirname(__file__), raw))
        if out:
            return out
    backend_dir = os.path.dirname(__file__)
    return [
        os.path.join(backend_dir, "echo_knowledge.md"),
    ]


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _compact_text(text: str, limit: int = 1800) -> str:
    one = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(one) <= limit:
        return one
    return one[: limit - 3].rstrip() + "..."


def _parse_kb_sections(raw: str, source_name: str) -> List[Dict[str, str]]:
    text = str(raw or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    blocks = re.split(r"\n(?=##\s+)", text)
    sections: List[Dict[str, str]] = []
    for block in blocks:
        b = block.strip()
        if not b:
            continue
        lines = b.split("\n")
        title = lines[0].strip().lstrip("#").strip() if lines else source_name
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        if not body:
            continue
        sections.append(
            {
                "title": title[:80],
                "body": _compact_text(body, limit=2400),
                "source": source_name,
            }
        )
    return sections


def _load_knowledge_sections() -> List[Dict[str, str]]:
    global _KB_CACHE
    paths = _knowledge_file_paths()
    sig_parts: List[str] = []
    for p in paths:
        try:
            sig_parts.append(f"{p}:{os.path.getmtime(p)}")
        except Exception:
            sig_parts.append(f"{p}:0")
    sig = "|".join(sig_parts)
    if _KB_CACHE.get("sig") == sig and isinstance(_KB_CACHE.get("sections"), list):
        return _KB_CACHE["sections"]  # type: ignore[return-value]

    parsed: List[Dict[str, str]] = []
    for p in paths:
        raw = _read_text(p)
        if not raw:
            continue
        parsed.extend(_parse_kb_sections(raw, os.path.basename(p)))

    if not parsed:
        parsed = [
            {
                "title": "Echo AI Features",
                "source": "fallback",
                "body": (
                    "Echo AI supports multi-thread chat, chat summary, emotion pulse, share links, "
                    "theme toggle, emoji picker, copy reply, and social links."
                ),
            }
        ]
    _KB_CACHE = {"sig": sig, "sections": parsed}
    return parsed


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_]{3,}", str(text or "").lower())


def _kb_relevance(query: str, section: Dict[str, str]) -> int:
    q_tokens = set(_tokenize_words(query))
    if not q_tokens:
        return 0
    hay = f"{section.get('title', '')} {section.get('body', '')}".lower()
    h_tokens = set(_tokenize_words(hay))
    overlap = q_tokens.intersection(h_tokens)
    score = len(overlap)
    for tok in overlap:
        if tok in section.get("title", "").lower():
            score += 2
    return score


def _build_knowledge_context(user_message: str, max_sections: int = 3) -> str:
    sections = _load_knowledge_sections()
    ranked = sorted(
        sections,
        key=lambda s: _kb_relevance(user_message, s),
        reverse=True,
    )
    chosen = [s for s in ranked if _kb_relevance(user_message, s) > 0][:max_sections]
    if not chosen:
        # Default guidance blocks if there was no keyword overlap.
        chosen = [s for s in sections if "feature" in s.get("title", "").lower()][:1]
        chosen += [s for s in sections if "location" in s.get("title", "").lower()][:1]
        if not chosen and sections:
            chosen = sections[:1]

    lines: List[str] = []
    for idx, sec in enumerate(chosen, start=1):
        lines.append(f"{idx}. {sec.get('title', 'Reference')} [{sec.get('source', 'doc')}]")
        lines.append(f"   {sec.get('body', '')}")
    return "\n".join(lines).strip()


def _bible_rag_file() -> str:
    return os.path.join(os.path.dirname(__file__), "bible_rag.json")


def _default_bible_chunks() -> List[Dict[str, Any]]:
    return [
        {"ref": "Psalm 34:18", "text": "The Lord is close to the brokenhearted and saves those who are crushed in spirit.", "tags": ["sad", "grief", "comfort"]},
        {"ref": "Isaiah 41:10", "text": "Do not fear, for I am with you; do not be dismayed, for I am your God.", "tags": ["fear", "anxiety", "courage"]},
        {"ref": "Philippians 4:6-7", "text": "Do not be anxious about anything; in every situation, by prayer and petition, present your requests to God.", "tags": ["anxiety", "worry", "prayer"]},
        {"ref": "Matthew 11:28", "text": "Come to me, all you who are weary and burdened, and I will give you rest.", "tags": ["stress", "tired", "rest"]},
        {"ref": "Romans 8:28", "text": "In all things God works for the good of those who love him.", "tags": ["hope", "purpose"]},
        {"ref": "Jeremiah 29:11", "text": "For I know the plans I have for you, plans to prosper you and not to harm you, plans to give you hope and a future.", "tags": ["future", "hope"]},
        {"ref": "Proverbs 3:5-6", "text": "Trust in the Lord with all your heart and lean not on your own understanding.", "tags": ["guidance", "decision"]},
        {"ref": "James 1:5", "text": "If any of you lacks wisdom, you should ask God, who gives generously to all without finding fault.", "tags": ["wisdom", "guidance"]},
        {"ref": "Joshua 1:9", "text": "Be strong and courageous. Do not be afraid; do not be discouraged, for the Lord your God will be with you.", "tags": ["courage", "strength"]},
        {"ref": "2 Timothy 1:7", "text": "God has not given us a spirit of fear, but of power and of love and of a sound mind.", "tags": ["fear", "confidence"]},
        {"ref": "1 Peter 5:7", "text": "Cast all your anxiety on him because he cares for you.", "tags": ["anxiety", "care"]},
        {"ref": "Psalm 23:1-4", "text": "The Lord is my shepherd; I shall not want. Even though I walk through the darkest valley, I will fear no evil.", "tags": ["comfort", "fear"]},
        {"ref": "Psalm 46:1", "text": "God is our refuge and strength, an ever-present help in trouble.", "tags": ["trouble", "strength"]},
        {"ref": "Romans 12:12", "text": "Be joyful in hope, patient in affliction, faithful in prayer.", "tags": ["hope", "prayer", "patience"]},
        {"ref": "Galatians 6:9", "text": "Let us not become weary in doing good, for at the proper time we will reap a harvest.", "tags": ["perseverance", "discipline"]},
        {"ref": "Ecclesiastes 4:9-10", "text": "Two are better than one... if either of them falls down, one can help the other up.", "tags": ["friendship", "support"]},
        {"ref": "Colossians 3:13", "text": "Bear with each other and forgive one another if any of you has a grievance.", "tags": ["forgiveness", "conflict"]},
        {"ref": "1 Corinthians 13:4-7", "text": "Love is patient, love is kind... it always protects, always trusts, always hopes.", "tags": ["love", "relationship"]},
    ]


def _load_bible_chunks() -> List[Dict[str, Any]]:
    global _BIBLE_RAG_CACHE
    path = _bible_rag_file()
    mtime = 0.0
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        mtime = 0.0
    if _BIBLE_RAG_CACHE.get("mtime") == mtime and isinstance(_BIBLE_RAG_CACHE.get("chunks"), list):
        return _BIBLE_RAG_CACHE["chunks"]  # type: ignore[return-value]

    chunks: List[Dict[str, Any]] = []
    if mtime > 0:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for row in data:
                        if not isinstance(row, dict):
                            continue
                        ref = str(row.get("ref", "")).strip()
                        text = str(row.get("text", "")).strip()
                        tags = row.get("tags", [])
                        if ref and text:
                            chunks.append(
                                {
                                    "ref": ref,
                                    "text": text,
                                    "tags": [str(t).strip().lower() for t in (tags if isinstance(tags, list) else []) if str(t).strip()],
                                }
                            )
        except Exception:
            chunks = []
    if not chunks:
        chunks = _default_bible_chunks()
    _BIBLE_RAG_CACHE = {"mtime": mtime, "chunks": chunks}
    return chunks


def _needs_bible_context(user_message: str, sentiment: str) -> bool:
    t = str(user_message or "").lower()
    direct = [
        "bible", "scripture", "verse", "god", "jesus", "christ", "faith", "pray", "prayer", "church", "holy spirit",
    ]
    emotional = [
        "hopeless", "i am tired", "i'm tired", "anxious", "anxiety", "afraid", "scared", "depressed", "sad",
        "broken", "hurt", "lonely", "grief", "grieving", "discouraged", "overwhelmed",
    ]
    if any(k in t for k in direct):
        return True
    if sentiment in {"negative", "crisis"} and any(k in t for k in emotional):
        return True
    return False


def _bible_relevance(query: str, chunk: Dict[str, Any]) -> int:
    q_tokens = set(_tokenize_words(query))
    if not q_tokens:
        return 0
    score = 0
    ref = str(chunk.get("ref", "")).lower()
    text = str(chunk.get("text", "")).lower()
    tags = {str(t).lower() for t in chunk.get("tags", []) if str(t).strip()}
    hay_tokens = set(_tokenize_words(f"{ref} {text} {' '.join(sorted(tags))}"))
    overlap = q_tokens.intersection(hay_tokens)
    score += len(overlap)
    for tok in q_tokens:
        if tok in tags:
            score += 2
    return score


def _build_bible_context(user_message: str, sentiment: str, max_chunks: int = 2) -> str:
    if not _needs_bible_context(user_message, sentiment):
        return ""
    chunks = _load_bible_chunks()
    ranked = sorted(chunks, key=lambda c: _bible_relevance(user_message, c), reverse=True)
    chosen = [c for c in ranked if _bible_relevance(user_message, c) > 0][:max_chunks]
    if not chosen:
        chosen = ranked[:1]
    lines: List[str] = []
    for idx, c in enumerate(chosen, start=1):
        lines.append(f"{idx}. {c.get('ref', 'Reference')} - {c.get('text', '')}")
    return "\n".join(lines).strip()


def _db_url() -> str:
    return (
        os.environ.get("DATABASE_URL", "").strip()
        or os.environ.get("POSTGRES_URL", "").strip()
        or os.environ.get("POSTGRES_PRISMA_URL", "").strip()
    )


def _mongo_uri() -> str:
    return os.environ.get("MONGODB_URI", "").strip().strip('"').strip("'")


def _mongo_enabled() -> bool:
    return bool(_mongo_uri())


def _mongo_db():
    global _MONGO_CLIENT
    if not _mongo_enabled():
        return None
    try:
        from pymongo import MongoClient
    except Exception as e:
        print(f"[BACKEND_ERROR] pymongo import failed: {e}")
        return None
    if _MONGO_CLIENT is None:
        _MONGO_CLIENT = MongoClient(_mongo_uri())
    return _MONGO_CLIENT["echo_ai"]


def _db_enabled() -> bool:
    return bool(_db_url())


@contextmanager
def _db_conn():
    import psycopg2  # lazy import for local file-only mode
    conn = psycopg2.connect(_db_url())
    try:
        yield conn
    finally:
        conn.close()


def _db_init() -> None:
    global _DB_READY
    if _DB_READY or not _db_enabled():
        return
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS echo_threads (
                      client_id TEXT NOT NULL,
                      thread_id TEXT NOT NULL,
                      title TEXT NOT NULL,
                      messages_json TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      PRIMARY KEY (client_id, thread_id)
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS echo_chat_logs (
                      id BIGSERIAL PRIMARY KEY,
                      timestamp_text TEXT NOT NULL,
                      timestamp_iso TEXT NOT NULL,
                      ip TEXT NOT NULL,
                      client_id TEXT NOT NULL,
                      sentiment TEXT NOT NULL,
                      sentiment_score INTEGER NOT NULL,
                      user_message TEXT NOT NULL,
                      bot_reply TEXT NOT NULL
                    );
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_echo_chat_logs_timestamp_iso ON echo_chat_logs(timestamp_iso DESC);"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS echo_email_events (
                      event_key TEXT PRIMARY KEY,
                      kind TEXT NOT NULL,
                      sent_at_iso TEXT NOT NULL,
                      meta_json TEXT NOT NULL
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS echo_shared_links (
                      share_id TEXT PRIMARY KEY,
                      source_client_id TEXT NOT NULL,
                      source_thread_id TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    );
                    """
                )
            conn.commit()
        _DB_READY = True
    except Exception as e:
        print(f"[BACKEND_ERROR] DB init failed: {e}")


def _format_human_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %I:%M%p").lower().replace(" 0", " ")


def _parse_any_timestamp(raw: str) -> datetime:
    s = str(raw or "").strip()
    if not s:
        return datetime.now(timezone.utc)
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    except Exception:
        return datetime.now(timezone.utc)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso_utc(raw: str) -> datetime:
    try:
        s = str(raw or "").strip()
        if not s:
            return datetime.now(timezone.utc)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _short_hash(*parts: str) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _email_enabled() -> bool:
    raw = os.environ.get("ECHO_FUN_EMAIL_ENABLED", "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(_smtp_user() and _smtp_password() and _email_to())


def _smtp_host() -> str:
    return os.environ.get("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"


def _smtp_port() -> int:
    try:
        return int(os.environ.get("SMTP_PORT", "587").strip())
    except Exception:
        return 587


def _smtp_user() -> str:
    return os.environ.get("SMTP_USER", "").strip()


def _smtp_password() -> str:
    return os.environ.get("SMTP_PASSWORD", "").strip()


def _smtp_from() -> str:
    return os.environ.get("SMTP_FROM", "").strip() or _smtp_user()


def _smtp_use_tls() -> bool:
    raw = os.environ.get("SMTP_USE_TLS", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _email_to() -> str:
    return os.environ.get("ECHO_ALERT_EMAIL_TO", "mclanorjephthah@gmail.com").strip()


def _email_cooldown_minutes() -> int:
    try:
        return max(1, int(os.environ.get("ECHO_EMAIL_COOLDOWN_MIN", "30").strip()))
    except Exception:
        return 30


def _send_email(subject: str, body_text: str, body_html: str = "") -> bool:
    if not _email_enabled():
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _smtp_from()
    msg["To"] = _email_to()
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(_smtp_host(), _smtp_port(), timeout=20) as server:
            if _smtp_use_tls():
                server.starttls()
            server.login(_smtp_user(), _smtp_password())
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[BACKEND_ERROR] email send failed: {e}")
        return False


def _load_email_events_file() -> Dict[str, Any]:
    ensure_data_dir(None)
    if not os.path.exists(EMAIL_EVENTS_FILE):
        return {}
    try:
        with open(EMAIL_EVENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_email_events_file(data: Dict[str, Any]) -> None:
    ensure_data_dir(None)
    try:
        with open(EMAIL_EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[BACKEND_ERROR] Failed to save email events file: {e}")


def _load_shared_links_file() -> Dict[str, Any]:
    ensure_data_dir(None)
    if not os.path.exists(SHARED_LINKS_FILE):
        return {}
    try:
        with open(SHARED_LINKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_shared_links_file(data: Dict[str, Any]) -> None:
    ensure_data_dir(None)
    try:
        with open(SHARED_LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[BACKEND_ERROR] Failed to save shared links file: {e}")


def _load_shared_snapshots_file() -> Dict[str, Any]:
    ensure_data_dir(None)
    if not os.path.exists(SHARED_SNAPSHOTS_FILE):
        return {}
    try:
        with open(SHARED_SNAPSHOTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_shared_snapshots_file(data: Dict[str, Any]) -> None:
    ensure_data_dir(None)
    try:
        with open(SHARED_SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[BACKEND_ERROR] Failed to save shared snapshots file: {e}")


def _put_shared_snapshot(share_id: str, snapshot: Dict[str, Any]) -> None:
    sid = str(share_id or "").strip()
    if not sid:
        return
    payload = {
        "share_id": sid,
        "snapshot": snapshot,
        "updated_at": _now_utc_iso(),
    }
    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                db.shared_snapshots.update_one(
                    {"share_id": sid},
                    {"$set": payload, "$setOnInsert": {"created_at": _now_utc_iso()}},
                    upsert=True,
                )
                return
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed mongo write shared snapshot: {e}")
    data = _load_shared_snapshots_file()
    existing = data.get(sid)
    if isinstance(existing, dict) and "created_at" in existing:
        payload["created_at"] = str(existing.get("created_at"))
    else:
        payload["created_at"] = _now_utc_iso()
    data[sid] = payload
    _save_shared_snapshots_file(data)


def _get_shared_snapshot(share_id: str) -> Optional[Dict[str, Any]]:
    sid = str(share_id or "").strip()
    if not sid:
        return None
    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                row = db.shared_snapshots.find_one({"share_id": sid}, {"_id": 0, "snapshot": 1})
                snap = row.get("snapshot") if isinstance(row, dict) else None
                return snap if isinstance(snap, dict) else None
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed mongo read shared snapshot: {e}")
    data = _load_shared_snapshots_file()
    row = data.get(sid)
    if isinstance(row, dict):
        snap = row.get("snapshot")
        return snap if isinstance(snap, dict) else None
    return None


def _get_shared_link(share_id: str) -> Optional[Dict[str, Any]]:
    sid = str(share_id or "").strip()
    if not sid:
        return None

    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                row = db.shared_links.find_one({"share_id": sid}, {"_id": 0})
                return row if isinstance(row, dict) else None
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed mongo read shared link: {e}")

    if _db_enabled():
        _db_init()
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT share_id, source_client_id, source_thread_id, created_at, updated_at FROM echo_shared_links WHERE share_id = %s",
                        (sid,),
                    )
                    row = cur.fetchone()
                    if row:
                        return {
                            "share_id": str(row[0]),
                            "source_client_id": str(row[1]),
                            "source_thread_id": str(row[2]),
                            "created_at": str(row[3]),
                            "updated_at": str(row[4]),
                        }
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed db read shared link: {e}")

    data = _load_shared_links_file()
    row = data.get(sid)
    return row if isinstance(row, dict) else None


def _put_shared_link(share_id: str, source_client_id: str, source_thread_id: str) -> Dict[str, Any]:
    now_iso = _now_utc_iso()
    payload = {
        "share_id": share_id,
        "source_client_id": _sanitize_client_id(source_client_id),
        "source_thread_id": str(source_thread_id),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                db.shared_links.update_one(
                    {"share_id": share_id},
                    {"$set": payload, "$setOnInsert": {"created_at": now_iso}},
                    upsert=True,
                )
                return payload
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed mongo write shared link: {e}")

    if _db_enabled():
        _db_init()
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO echo_shared_links (share_id, source_client_id, source_thread_id, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (share_id)
                        DO UPDATE SET source_client_id = EXCLUDED.source_client_id, source_thread_id = EXCLUDED.source_thread_id, updated_at = EXCLUDED.updated_at
                        """,
                        (
                            share_id,
                            payload["source_client_id"],
                            payload["source_thread_id"],
                            payload["created_at"],
                            payload["updated_at"],
                        ),
                    )
                conn.commit()
            return payload
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed db write shared link: {e}")

    data = _load_shared_links_file()
    if share_id in data and isinstance(data[share_id], dict):
        payload["created_at"] = str(data[share_id].get("created_at", now_iso))
    data[share_id] = payload
    _save_shared_links_file(data)
    return payload


def _get_email_event(event_key: str) -> Optional[Dict[str, Any]]:
    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                row = db.email_events.find_one({"event_key": event_key}, {"_id": 0})
                return row if isinstance(row, dict) else None
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed mongo read email event: {e}")

    if _db_enabled():
        _db_init()
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT event_key, kind, sent_at_iso, meta_json FROM echo_email_events WHERE event_key = %s",
                        (event_key,),
                    )
                    row = cur.fetchone()
                    if row:
                        meta = {}
                        try:
                            meta = json.loads(row[3] or "{}")
                        except Exception:
                            meta = {}
                        return {
                            "event_key": str(row[0]),
                            "kind": str(row[1]),
                            "sent_at_iso": str(row[2]),
                            "meta": meta,
                        }
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed db read email event: {e}")

    data = _load_email_events_file()
    row = data.get(event_key)
    return row if isinstance(row, dict) else None


def _put_email_event(event_key: str, kind: str, meta: Dict[str, Any]) -> None:
    payload = {
        "event_key": event_key,
        "kind": kind,
        "sent_at_iso": _now_utc_iso(),
        "meta": meta or {},
    }
    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                db.email_events.update_one({"event_key": event_key}, {"$set": payload}, upsert=True)
                return
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed mongo write email event: {e}")

    if _db_enabled():
        _db_init()
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO echo_email_events (event_key, kind, sent_at_iso, meta_json)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (event_key)
                        DO UPDATE SET kind = EXCLUDED.kind, sent_at_iso = EXCLUDED.sent_at_iso, meta_json = EXCLUDED.meta_json
                        """,
                        (
                            event_key,
                            kind,
                            payload["sent_at_iso"],
                            json.dumps(payload["meta"], ensure_ascii=False),
                        ),
                    )
                conn.commit()
            return
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed db write email event: {e}")

    data = _load_email_events_file()
    data[event_key] = payload
    _save_email_events_file(data)


def _email_event_recent(event_key: str, minutes: int) -> bool:
    row = _get_email_event(event_key)
    if not row:
        return False
    sent = _parse_iso_utc(row.get("sent_at_iso", ""))
    return (datetime.now(timezone.utc) - sent) < timedelta(minutes=max(1, minutes))


def _list_email_events(limit: int = 200) -> List[Dict[str, Any]]:
    n = max(1, min(int(limit), 1000))

    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                rows = list(
                    db.email_events.find({}, {"_id": 0})
                    .sort("sent_at_iso", -1)
                    .limit(n)
                )
                return [r for r in rows if isinstance(r, dict)]
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed mongo list email events: {e}")

    if _db_enabled():
        _db_init()
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT event_key, kind, sent_at_iso, meta_json FROM echo_email_events ORDER BY sent_at_iso DESC LIMIT %s",
                        (n,),
                    )
                    out: List[Dict[str, Any]] = []
                    for row in cur.fetchall():
                        meta = {}
                        try:
                            meta = json.loads(row[3] or "{}")
                        except Exception:
                            meta = {}
                        out.append(
                            {
                                "event_key": str(row[0]),
                                "kind": str(row[1]),
                                "sent_at_iso": str(row[2]),
                                "meta": meta,
                            }
                        )
                    return out
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed db list email events: {e}")

    data = _load_email_events_file()
    rows = [v for v in data.values() if isinstance(v, dict)]
    rows.sort(key=lambda r: str(r.get("sent_at_iso", "")), reverse=True)
    return rows[:n]


def _mask_email(value: str) -> str:
    raw = str(value or "").strip()
    if "@" not in raw:
        return ""
    left, right = raw.split("@", 1)
    if len(left) <= 2:
        left_masked = left[0] + "*" * max(0, len(left) - 1)
    else:
        left_masked = left[:2] + "*" * max(0, len(left) - 2)
    return f"{left_masked}@{right}"


def _humor_score(text: str) -> float:
    raw = str(text or "")
    t = raw.lower()
    words = {
        "lol": 1.2,
        "lmao": 1.6,
        "haha": 1.4,
        "funny": 1.2,
        "joke": 1.0,
        "roast": 1.3,
        "bro": 0.6,
        "fam": 0.7,
        "wild": 0.8,
        "crazy": 0.7,
        "wtf": 1.0,
        "omg": 0.8,
    }
    score = 0.0
    for k, w in words.items():
        if k in t:
            score += w
    emoji_hits = sum(raw.count(e) for e in ["😂", "🤣", "😆", "😹", "🔥"])
    score += min(2.0, emoji_hits * 0.5)
    score += min(1.2, raw.count("!") * 0.18)
    if "?" in raw and "!" in raw:
        score += 0.4
    if len(raw) <= 28 and score > 0:
        score += 0.5
    return round(score, 2)


def _send_trigger_email(kind: str, subject: str, lines: List[str], event_key: str, meta: Dict[str, Any], cooldown_min: int) -> None:
    if not _email_enabled():
        return
    if _email_event_recent(event_key, cooldown_min):
        return
    sent_local = _format_human_timestamp(datetime.now().astimezone())
    body_text = "\n".join(lines + ["", f"Sent: {sent_local}", "Source: Echo AI"])
    html_lines = "".join(f"<li>{line}</li>" for line in lines)
    body_html = f"<h3>{subject}</h3><ul>{html_lines}</ul><p><small>Sent: {sent_local}<br/>Source: Echo AI</small></p>"
    if _send_email(subject, body_text, body_html):
        _put_email_event(event_key, kind, meta)


def _maybe_send_weekly_awards() -> None:
    if not _email_enabled():
        return
    now_utc = datetime.now(timezone.utc)
    week_key = now_utc.strftime("%G-W%V")
    event_key = f"weekly_awards_{week_key}"
    if _get_email_event(event_key):
        return

    rows = get_chat_logs(limit=3000)
    cutoff = now_utc - timedelta(days=7)
    recent = [r for r in rows if _parse_iso_utc(r.get("timestamp_iso", "")) >= cutoff]
    if not recent:
        return

    funniest_user = max(recent, key=lambda r: _humor_score(r.get("user_message", "")))
    best_reply = max(recent, key=lambda r: _humor_score(r.get("bot_reply", "")))
    positive = sum(1 for r in recent if int(r.get("sentiment_score", 0)) > 0)
    negative = sum(1 for r in recent if int(r.get("sentiment_score", 0)) < 0)
    neutral = len(recent) - positive - negative

    subject = f"Echo AI Weekly Awards 🏆 ({week_key})"
    lines = [
        f"Total message events: {len(recent)}",
        f"Tone split: positive {positive}, neutral {neutral}, negative {negative}",
        f"Funniest user line: {str(funniest_user.get('user_message', ''))[:180]}",
        f"Best bot comeback: {str(best_reply.get('bot_reply', ''))[:180]}",
    ]
    _send_trigger_email(
        kind="weekly_awards",
        subject=subject,
        lines=lines,
        event_key=event_key,
        meta={"week_key": week_key, "events": len(recent)},
        cooldown_min=60 * 24 * 8,
    )


def _extract_user_sentiment_scores(thread: Dict[str, Any]) -> List[int]:
    out: List[int] = []
    for m in thread.get("messages", []):
        if m.get("role") == "user":
            out.append(_sentiment_to_score(_detect_sentiment(str(m.get("content", "")))))
    return out


def _process_fun_email_triggers(
    thread: Dict[str, Any],
    user_message: str,
    bot_reply: str,
    sentiment: str,
) -> None:
    if not _email_enabled():
        return

    cooldown = _email_cooldown_minutes()
    thread_id = str(thread.get("id", "no-thread"))
    title = str(thread.get("title", "Conversation"))
    user_score = _humor_score(user_message)
    bot_score = _humor_score(bot_reply)
    sentiment_score = _sentiment_to_score(sentiment)

    # 1) Comedy Alert
    if user_score >= 2.0 and sentiment_score >= 0:
        key = f"comedy_alert_{thread_id}_{_short_hash(user_message)}"
        _send_trigger_email(
            kind="comedy_alert",
            subject="Echo AI: Certified Chaos Detected 😂",
            lines=[
                f"Thread: {title}",
                f"Funny user message score: {user_score}",
                f"User said: {user_message[:240]}",
                f"Bot replied: {bot_reply[:240]}",
            ],
            event_key=key,
            meta={"thread_id": thread_id, "score": user_score},
            cooldown_min=cooldown,
        )

    # 2) Savage Comeback Digest
    if bot_score >= 2.4:
        key = f"savage_comeback_{thread_id}_{_short_hash(bot_reply)}"
        _send_trigger_email(
            kind="savage_comeback",
            subject="Echo AI cooked someone (politely) 🔥",
            lines=[
                f"Thread: {title}",
                f"Comeback score: {bot_score}",
                f"Prompt: {user_message[:180]}",
                f"Reply: {bot_reply[:240]}",
            ],
            event_key=key,
            meta={"thread_id": thread_id, "score": bot_score},
            cooldown_min=cooldown,
        )

    # 3) Mood Whiplash Alert
    scores = _extract_user_sentiment_scores(thread)
    if len(scores) >= 2:
        prev_sc = scores[-2]
        curr_sc = scores[-1]
        if (prev_sc <= -1 and curr_sc >= 1) or (prev_sc >= 1 and curr_sc <= -1):
            key = f"mood_whiplash_{thread_id}_{_short_hash(str(prev_sc), str(curr_sc), user_message)}"
            _send_trigger_email(
                kind="mood_whiplash",
                subject="Plot Twist in Chat 🎭",
                lines=[
                    f"Thread: {title}",
                    f"Mood shift detected: {prev_sc} -> {curr_sc}",
                    f"User message: {user_message[:220]}",
                ],
                event_key=key,
                meta={"thread_id": thread_id, "prev": prev_sc, "curr": curr_sc},
                cooldown_min=cooldown,
            )

    # 4) Legendary Thread Starter
    user_count = sum(1 for m in thread.get("messages", []) if m.get("role") == "user")
    assistant_count = sum(1 for m in thread.get("messages", []) if m.get("role") == "assistant")
    if user_count == 1 and assistant_count == 1 and (user_score >= 1.2 or len(user_message.strip()) <= 16):
        key = f"legendary_starter_{thread_id}"
        _send_trigger_email(
            kind="legendary_starter",
            subject="New Thread Started With Pure Cinema 🎬",
            lines=[
                f"Thread: {title}",
                f"Starter message: {user_message[:220]}",
                f"Auto-title: {title}",
            ],
            event_key=key,
            meta={"thread_id": thread_id},
            cooldown_min=60 * 24 * 365,
        )

    # 5) Weekly Awards
    _maybe_send_weekly_awards()


def ensure_data_dir(client_id: Optional[str] = None):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    threads_file = _threads_file_for_client(client_id)
    if not os.path.exists(threads_file):
        with open(threads_file, "w", encoding="utf-8") as f:
            json.dump([], f)


def _append_chat_log(
    client_ip: str,
    client_id: Optional[str],
    user_message: str,
    bot_reply: str,
    sentiment: str,
    sentiment_score: int,
) -> None:
    now_local = datetime.now().astimezone()
    human_ts = _format_human_timestamp(now_local)

    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                db.chat_logs.insert_one(
                    {
                        "timestamp": human_ts,
                        "timestamp_iso": now_local.isoformat(timespec="seconds"),
                        "ip": client_ip or "unknown",
                        "client_id": _sanitize_client_id(client_id),
                        "sentiment": sentiment,
                        "sentiment_score": int(sentiment_score),
                        "user_message": user_message,
                        "bot_reply": bot_reply,
                    }
                )
                return
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to append mongo chat log: {e}")

    if _db_enabled():
        _db_init()
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO echo_chat_logs
                        (timestamp_text, timestamp_iso, ip, client_id, sentiment, sentiment_score, user_message, bot_reply)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            human_ts,
                            now_local.isoformat(timespec="seconds"),
                            client_ip or "unknown",
                            _sanitize_client_id(client_id),
                            sentiment,
                            int(sentiment_score),
                            user_message,
                            bot_reply,
                        ),
                    )
                conn.commit()
            return
        except Exception as e:
                print(f"[BACKEND_ERROR] Failed to append db chat log: {e}")

    ensure_data_dir(client_id)
    event = {
        "timestamp": human_ts,
        "timestamp_iso": now_local.isoformat(timespec="seconds"),
        "ip": client_ip or "unknown",
        "client_id": _sanitize_client_id(client_id),
        "sentiment": sentiment,
        "sentiment_score": int(sentiment_score),
        "user_message": user_message,
        "bot_reply": bot_reply,
    }
    try:
        with open(CHAT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[BACKEND_ERROR] Failed to append chat log: {e}")


def _reconstruct_events_from_threads(limit: int = 600) -> List[Dict[str, Any]]:
    ensure_data_dir(None)
    files = glob.glob(os.path.join(DATA_DIR, "threads_*.json"))
    events: List[Dict[str, Any]] = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                threads = json.load(f)
        except Exception:
            continue
        client_name = os.path.basename(path).replace("threads_", "").replace(".json", "")
        for t in threads if isinstance(threads, list) else []:
            pending_user = None
            for m in t.get("messages", []):
                role = m.get("role")
                if role == "user":
                    pending_user = m
                elif role == "assistant" and pending_user:
                    ts = pending_user.get("ts") or m.get("ts") or t.get("updated_at") or t.get("created_at")
                    dt = _parse_any_timestamp(ts)
                    sentiment = _detect_sentiment(str(pending_user.get("content", "")))
                    score = _sentiment_to_score(sentiment)
                    events.append({
                        "timestamp": _format_human_timestamp(dt),
                        "timestamp_iso": dt.isoformat(timespec="seconds"),
                        "ip": "unknown",
                        "client_id": client_name,
                        "sentiment": sentiment,
                        "sentiment_score": score,
                        "user_message": str(pending_user.get("content", "")),
                        "bot_reply": str(m.get("content", "")),
                    })
                    pending_user = None
    events.sort(key=lambda x: x.get("timestamp_iso", ""), reverse=True)
    return events[: max(1, min(limit, 3000))]


def get_chat_logs(limit: int = 200) -> List[Dict[str, Any]]:
    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                docs = list(
                    db.chat_logs.find({}, {"_id": 0})
                    .sort("timestamp_iso", -1)
                    .limit(max(1, min(limit, 3000)))
                )
                if docs:
                    return docs
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to fetch mongo chat logs: {e}")

    if _db_enabled():
        _db_init()
        try:
            out: List[Dict[str, Any]] = []
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT timestamp_text, timestamp_iso, ip, client_id, sentiment, sentiment_score, user_message, bot_reply
                        FROM echo_chat_logs
                        ORDER BY timestamp_iso DESC
                        LIMIT %s
                        """,
                        (max(1, min(limit, 3000)),),
                    )
                    for row in cur.fetchall():
                        out.append(
                            {
                                "timestamp": row[0],
                                "timestamp_iso": row[1],
                                "ip": row[2],
                                "client_id": row[3],
                                "sentiment": row[4],
                                "sentiment_score": int(row[5]),
                                "user_message": row[6],
                                "bot_reply": row[7],
                            }
                        )
            return out
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to fetch db chat logs: {e}")

    ensure_data_dir(None)
    rows: List[Dict[str, Any]] = []
    if os.path.exists(CHAT_LOG_FILE):
        try:
            with open(CHAT_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to read chat logs: {e}")

    reconstructed = _reconstruct_events_from_threads(limit=2000)
    merged: Dict[str, Dict[str, Any]] = {}
    for r in rows + reconstructed:
        day_key = str(r.get("timestamp_iso", "")).split("T")[0] if r.get("timestamp_iso") else str(r.get("timestamp", "")).split(" ")[0]
        key = "|".join([
            str(r.get("client_id", "")),
            str(r.get("user_message", "")),
            str(r.get("bot_reply", "")),
            day_key,
        ])
        if key not in merged:
            merged[key] = r
            continue

        existing = merged[key]
        existing_ip = str(existing.get("ip", "")).strip().lower()
        current_ip = str(r.get("ip", "")).strip().lower()
        existing_ts = str(existing.get("timestamp_iso", ""))
        current_ts = str(r.get("timestamp_iso", ""))

        # Prefer rows with known IP, then newer timestamp.
        if existing_ip in ("", "unknown") and current_ip not in ("", "unknown"):
            merged[key] = r
        elif current_ts > existing_ts:
            merged[key] = r

    out = list(merged.values())
    out.sort(key=lambda x: x.get("timestamp_iso", ""), reverse=True)
    return out[: max(1, min(limit, 3000))]


def load_threads(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                cid = _sanitize_client_id(client_id)
                docs = db.threads.find({"client_id": cid}, {"_id": 0}).sort("updated_at", -1)
                out: List[Dict[str, Any]] = []
                for d in docs:
                    out.append(
                        {
                            "id": str(d.get("thread_id", "")),
                            "title": str(d.get("title", "New Conversation")),
                            "messages": d.get("messages", []),
                            "created_at": str(d.get("created_at", "")),
                            "updated_at": str(d.get("updated_at", "")),
                        }
                    )
                return out
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to load mongo threads: {e}")

    if _db_enabled():
        _db_init()
        try:
            cid = _sanitize_client_id(client_id)
            out: List[Dict[str, Any]] = []
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT thread_id, title, messages_json, created_at, updated_at
                        FROM echo_threads
                        WHERE client_id = %s
                        ORDER BY updated_at DESC
                        """,
                        (cid,),
                    )
                    for row in cur.fetchall():
                        try:
                            messages = json.loads(row[2])
                        except Exception:
                            messages = []
                        out.append(
                            {
                                "id": str(row[0]),
                                "title": str(row[1]),
                                "messages": messages,
                                "created_at": str(row[3]),
                                "updated_at": str(row[4]),
                            }
                        )
            return out
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to load db threads: {e}")

    ensure_data_dir(client_id)
    threads_file = _threads_file_for_client(client_id)
    try:
        with open(threads_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[BACKEND_ERROR] Failed to load threads: {e}")
        return []


def save_threads(threads: List[Dict[str, Any]], client_id: Optional[str] = None) -> None:
    if _mongo_enabled():
        db = _mongo_db()
        if db is not None:
            try:
                cid = _sanitize_client_id(client_id)
                current_ids = [str(t.get("id", "")) for t in threads]
                db.threads.delete_many({"client_id": cid, "thread_id": {"$nin": current_ids}})
                for t in threads:
                    db.threads.update_one(
                        {"client_id": cid, "thread_id": str(t.get("id", ""))},
                        {
                            "$set": {
                                "client_id": cid,
                                "thread_id": str(t.get("id", "")),
                                "title": str(t.get("title", "New Conversation")),
                                "messages": t.get("messages", []),
                                "created_at": str(t.get("created_at", "")),
                                "updated_at": str(t.get("updated_at", "")),
                            }
                        },
                        upsert=True,
                    )
                return
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to save mongo threads: {e}")

    if _db_enabled():
        _db_init()
        try:
            cid = _sanitize_client_id(client_id)
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM echo_threads WHERE client_id = %s", (cid,))
                    for t in threads:
                        cur.execute(
                            """
                            INSERT INTO echo_threads (client_id, thread_id, title, messages_json, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                cid,
                                str(t.get("id", "")),
                                str(t.get("title", "New Conversation")),
                                json.dumps(t.get("messages", []), ensure_ascii=False),
                                str(t.get("created_at", "")),
                                str(t.get("updated_at", "")),
                            ),
                        )
                conn.commit()
            return
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to save db threads: {e}")

    ensure_data_dir(client_id)
    threads_file = _threads_file_for_client(client_id)
    try:
        with open(threads_file, "w", encoding="utf-8") as f:
            json.dump(threads, f, ensure_ascii=False)
    except Exception as e:
        print(f"[BACKEND_ERROR] Failed to save threads: {e}")


# -------------------------
# Text cleanup
# -------------------------
def _strip_markdown(text: str) -> str:
    """
    UI isn't rendering Markdown, so remove Markdown markers so users don't see **, *, `, etc.
    """
    if not text:
        return text

    # Normalize bullets: "* item" -> "- item"
    text = re.sub(r"(?m)^\s*\*\s+", "- ", text)

    # Bold/italic markers: **text** / __text__ / *text* / _text_ -> text
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)  # single *italics*
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)        # single _italics_

    # Inline code/backticks: `code` -> code
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Headings: "### Title" -> "Title"
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)

    # Blockquotes: "> quote" -> "quote"
    text = re.sub(r"(?m)^\s*>\s?", "", text)

    # Remove stray markdown emphasis markers that sometimes leak
    text = text.replace("**", "").replace("__", "")

    return text


# -------------------------
# Date/time injection
# -------------------------
def _now_local_iso() -> str:
    """
    Returns an ISO timestamp for "now" in server local time if possible,
    otherwise UTC. If you set ECHO_TZ, we try to use it (Python 3.9+).
    """
    tz_name = os.environ.get("ECHO_TZ", "").strip()
    try:
        if tz_name:
            from zoneinfo import ZoneInfo  # Python 3.9+
            tz = ZoneInfo(tz_name)
            return datetime.now(tz).isoformat(timespec="seconds")
    except Exception as e:
        print(f"[BACKEND_WARN] Could not use ECHO_TZ='{tz_name}': {e}")

    # fallback: local time without tz awareness
    try:
        return datetime.now().isoformat(timespec="seconds")
    except Exception:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today_human_readable() -> str:
    """
    Human friendly date: e.g., "Wednesday, 21 February 2026"
    """
    tz_name = os.environ.get("ECHO_TZ", "").strip()
    try:
        if tz_name:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
            dt = datetime.now(tz)
        else:
            dt = datetime.now()
    except Exception:
        dt = datetime.now(timezone.utc)

    return dt.strftime("%A, %d %B %Y")


def _detect_sentiment(text: str) -> str:
    t = str(text or "").lower()
    positive = {"happy", "great", "awesome", "love", "excited", "good", "thanks", "thank you", "amazing"}
    negative = {"sad", "angry", "depressed", "hate", "upset", "tired", "stressed", "anxious", "lonely", "bad"}
    urgent = {"suicide", "kill myself", "self harm", "end my life", "want to die", "die"}

    if any(w in t for w in urgent):
        return "crisis"
    pos_hits = sum(1 for w in positive if w in t)
    neg_hits = sum(1 for w in negative if w in t)
    if pos_hits > neg_hits:
        return "positive"
    if neg_hits > pos_hits:
        return "negative"
    return "neutral"


def _sentiment_to_score(sentiment: str) -> int:
    s = str(sentiment).lower()
    if s == "crisis":
        return -3
    if s == "negative":
        return -1
    if s == "positive":
        return 1
    return 0


def _sanitize_title(text: str) -> str:
    t = re.sub(r"[\r\n\t]+", " ", str(text or "")).strip()
    t = re.sub(r"[*_`#>\[\]\(\)\{\}\|]+", "", t).strip(" .:-")
    t = re.sub(r"\s+", " ", t)
    return t[:36]


def _fallback_collective_title(first_user_message: str) -> str:
    t = str(first_user_message or "").lower().strip()
    if any(w in t for w in ["hi", "hey", "hello", "yo", "sup", "good morning", "good evening"]):
        return "Greetings"
    if any(w in t for w in ["sad", "lonely", "depressed", "anxious", "stressed", "tired", "hurt"]):
        return "Emotional Check-In"
    if any(w in t for w in ["who are you", "about you", "capabilities", "what can you do"]):
        return "Getting to Know Echo"
    if any(w in t for w in ["date", "time", "today", "day"]):
        return "Time and Date"
    if any(w in t for w in ["help", "advice", "guidance", "what should i do"]):
        return "Guidance"
    if any(w in t for w in ["creator", "lanor", "built you"]):
        return "Creator Info"
    return "Conversation"


def _collective_thread_title(first_user_message: str, assistant_reply: str) -> str:
    fallback = _fallback_collective_title(first_user_message)
    prompt = (
        "Create one short category title for a chat thread.\n"
        "Rules:\n"
        "- Return only 1 to 3 words.\n"
        "- Use title case.\n"
        "- Be general, not literal.\n"
        "- Do not use punctuation.\n"
        "- Do not include quotes.\n"
    )
    user_context = (
        f"First user message: {first_user_message}\n"
        f"Assistant reply summary hint: {assistant_reply[:180]}"
    )
    try:
        if _use_nexttoken():
            out = _nexttoken_generate_reply(prompt, [{"role": "user", "content": user_context}])
        else:
            out = _gemini_generate_reply(prompt, [{"role": "user", "content": user_context}])
        title = _sanitize_title(_strip_markdown(out))
        if not title:
            return fallback
        words = title.split()
        if len(words) > 4:
            title = " ".join(words[:3])
        if len(title) < 3:
            return fallback
        return title
    except Exception:
        return fallback


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        s = str(item or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _extract_thread_transcript(thread: Dict[str, Any], max_messages: int = 40, max_chars: int = 5000) -> str:
    messages = thread.get("messages", [])
    selected = messages[-max_messages:]
    lines: List[str] = []
    for m in selected:
        role = str(m.get("role", "")).lower()
        if role not in {"user", "assistant"}:
            continue
        prefix = "User" if role == "user" else "Echo"
        content = re.sub(r"\s+", " ", str(m.get("content", "")).strip())
        if len(content) > 320:
            content = content[:320] + "..."
        lines.append(f"{prefix}: {content}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def _local_thread_summary(thread: Dict[str, Any]) -> Dict[str, Any]:
    messages = thread.get("messages", [])
    user_msgs = [str(m.get("content", "")).strip() for m in messages if str(m.get("role", "")).lower() == "user"]
    assistant_msgs = [str(m.get("content", "")).strip() for m in messages if str(m.get("role", "")).lower() == "assistant"]
    lower_all = " ".join(user_msgs).lower()

    talked_about: List[str] = []
    if any(w in lower_all for w in ["hi", "hello", "hey", "yo", "sup"]):
        talked_about.append("General greetings and opening chat")
    if any(w in lower_all for w in ["sad", "lonely", "anxious", "stressed", "depressed", "tired", "upset"]):
        talked_about.append("Emotional wellbeing and support check-ins")
    if any(w in lower_all for w in ["date", "time", "today", "day"]):
        talked_about.append("Date and time clarification")
    if any(w in lower_all for w in ["creator", "built", "who made", "lanor"]):
        talked_about.append("Questions about Echo AI creator and identity")
    if any(w in lower_all for w in ["capabilities", "what can you do", "features", "help"]):
        talked_about.append("Echo AI capabilities and how it can help")
    if any(w in lower_all for w in ["lol", "haha", "funny", "joke", "lmao", "😂", "🤣"]):
        talked_about.append("Humor and playful banter")
    if not talked_about and user_msgs:
        talked_about.append(f"Main prompt: {user_msgs[0][:84]}")

    pos = sum(1 for msg in user_msgs if _sentiment_to_score(_detect_sentiment(msg)) > 0)
    neg = sum(1 for msg in user_msgs if _sentiment_to_score(_detect_sentiment(msg)) < 0)

    learned: List[str] = []
    if pos > neg:
        learned.append("The user responds well to upbeat and playful tone.")
    elif neg > pos:
        learned.append("The user may need calmer and more reassuring support.")
    else:
        learned.append("The user alternates between neutral and mixed emotional tone.")
    if any(w in lower_all for w in ["date", "time", "today"]):
        learned.append("Real-time date and time context is useful in this conversation.")
    if any(w in lower_all for w in ["creator", "built", "lanor"]):
        learned.append("The user is interested in who built Echo AI and background details.")
    if any(w in lower_all for w in ["capabilities", "what can you do", "help"]):
        learned.append("The user wants clear explanation of Echo AI capabilities.")
    if any(w in lower_all for w in ["lol", "haha", "funny", "😂", "🤣"]):
        learned.append("Humor improves engagement and keeps the conversation lively.")

    talked_about = _dedupe_keep_order(talked_about)[:6]
    learned = _dedupe_keep_order(learned)[:6]

    summary = (
        f"This chat contains {len(messages)} messages between the user and Echo AI. "
        f"They mainly discussed {talked_about[0].lower()}."
    )
    if len(talked_about) > 1:
        summary += f" It also touched on {talked_about[1].lower()}."

    return {
        "title": str(thread.get("title", "Conversation")),
        "message_count": len(messages),
        "summary": summary.strip(),
        "talked_about": talked_about,
        "learned": learned,
        "generated_at": _now_utc_iso(),
        "source": "fallback",
    }


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = cleaned[start : end + 1]
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def summarize_thread(**args):
    thread_id = str(args.get("thread_id", "")).strip()
    client_id = args.get("client_id")
    if not thread_id:
        return {"error": "thread_id is required"}

    threads = load_threads(client_id)
    thread = next((t for t in threads if str(t.get("id", "")) == thread_id), None)
    if not thread:
        return {"error": "Thread not found"}

    messages = thread.get("messages", [])
    if not messages:
        return {
            "title": str(thread.get("title", "Conversation")),
            "message_count": 0,
            "summary": "No messages yet in this chat.",
            "talked_about": [],
            "learned": [],
            "generated_at": _now_utc_iso(),
            "source": "empty",
        }

    fallback = _local_thread_summary(thread)
    transcript = _extract_thread_transcript(thread)
    if not transcript:
        return fallback

    prompt = (
        "Summarize this chat for the owner.\n"
        "Return strict JSON only with keys:\n"
        "summary: string\n"
        "talked_about: string[]\n"
        "learned: string[]\n\n"
        "Rules:\n"
        "- summary must be 2 to 4 sentences in plain English.\n"
        "- talked_about must have 3 to 6 concise points.\n"
        "- learned must have 3 to 6 concise points about user preferences/patterns.\n"
        "- No markdown, no code fences.\n"
    )

    try:
        if _use_nexttoken():
            raw = _nexttoken_generate_reply(prompt, [{"role": "user", "content": transcript}])
        else:
            raw = _gemini_generate_reply(prompt, [{"role": "user", "content": transcript}])
        data = _extract_json_block(raw) or {}

        summary = _strip_markdown(str(data.get("summary", "")).strip())
        talked_about = _dedupe_keep_order([_strip_markdown(str(x)) for x in data.get("talked_about", [])])[:6]
        learned = _dedupe_keep_order([_strip_markdown(str(x)) for x in data.get("learned", [])])[:6]

        if not summary or not talked_about or not learned:
            return fallback

        return {
            "title": str(thread.get("title", "Conversation")),
            "message_count": len(messages),
            "summary": summary,
            "talked_about": talked_about,
            "learned": learned,
            "generated_at": _now_utc_iso(),
            "source": "ai",
        }
    except Exception as e:
        print(f"[BACKEND_WARN] summarize_thread fallback: {e}")
        return fallback


def create_share_link(**args):
    thread_id = str(args.get("thread_id", "")).strip()
    client_id = _sanitize_client_id(args.get("client_id"))
    if not thread_id:
        return {"error": "thread_id is required"}

    threads = load_threads(client_id)
    thread = next((t for t in threads if str(t.get("id", "")) == thread_id), None)
    if not thread:
        return {"error": "Thread not found"}
    snapshot = {
        "id": str(thread.get("id", "")),
        "title": str(thread.get("title", "Shared Conversation")),
        "messages": thread.get("messages", []),
        "created_at": str(thread.get("created_at", _now_utc_iso())),
        "updated_at": str(thread.get("updated_at", _now_utc_iso())),
    }
    # Use short share IDs backed by storage to avoid long URLs breaking on mobile/social apps.
    share_id = secrets.token_urlsafe(12)
    _put_shared_snapshot(share_id, snapshot)
    base_url = os.environ.get("PUBLIC_APP_URL", "https://echo-ai-companion-bice.vercel.app").strip().rstrip("/")
    return {"share_id": share_id, "url": f"{base_url}/shared/{share_id}"}


def import_shared_thread(**args):
    share_id = str(args.get("share_id", "")).strip()
    target_client_id = _sanitize_client_id(args.get("client_id"))
    if not share_id:
        return {"error": "share_id is required"}

    # Preferred: server-side snapshot lookup by short share_id.
    snap = _get_shared_snapshot(share_id)
    if isinstance(snap, dict):
        imported_id = f"shared-{share_id}"
        imported_thread = {
            "id": imported_id,
            "title": str(snap.get("title", "Shared Conversation")),
            "messages": snap.get("messages", []),
            "created_at": str(snap.get("created_at", _now_utc_iso())),
            "updated_at": str(snap.get("updated_at", _now_utc_iso())),
        }
        return {
            "thread": imported_thread,
            "readonly": True,
            "reason": "This is a shared read-only snapshot to protect the owner conversation and privacy.",
        }

    # Backward compatibility for old token-based share links.
    try:
        if "." not in share_id:
            return {"error": "Invalid share link"}
        payload_b64, sig = share_id.split(".", 1)
        secret = os.environ.get("ECHO_SHARE_SECRET", "echo-share-secret").encode("utf-8")
        expected = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
        if not hmac.compare_digest(sig, expected):
            return {"error": "Invalid or tampered share link"}
        pad = "=" * (-len(payload_b64) % 4)
        payload_raw = base64.urlsafe_b64decode((payload_b64 + pad).encode("utf-8"))
        payload = json.loads(payload_raw.decode("utf-8"))
        ver = int(payload.get("v", 1))
        if ver >= 2 and isinstance(payload.get("th"), dict):
            source_thread = payload.get("th")
            imported_id = f"shared-{share_id}"
            imported_thread = {
                "id": imported_id,
                "title": str(source_thread.get("title", "Shared Conversation")),
                "messages": source_thread.get("messages", []),
                "created_at": str(source_thread.get("created_at", _now_utc_iso())),
                "updated_at": str(source_thread.get("updated_at", _now_utc_iso())),
            }
            return {
                "thread": imported_thread,
                "readonly": True,
                "reason": "This is a shared read-only snapshot to protect the owner conversation and privacy.",
            }

        source_client_id = _sanitize_client_id(payload.get("c"))
        source_thread_id = str(payload.get("t", "")).strip()
    except Exception:
        return {"error": "Invalid share link"}

    source_threads = load_threads(source_client_id)
    source_thread = next((t for t in source_threads if str(t.get("id", "")) == source_thread_id), None)
    if not source_thread:
        return {"error": "Source thread not found"}

    imported_id = f"shared-{share_id}"
    imported_thread = {
        "id": imported_id,
        "title": str(source_thread.get("title", "Shared Conversation")),
        "messages": source_thread.get("messages", []),
        "created_at": str(source_thread.get("created_at", _now_utc_iso())),
        "updated_at": str(source_thread.get("updated_at", _now_utc_iso())),
    }

    return {
        "thread": imported_thread,
        "readonly": True,
        "reason": "This is a shared read-only snapshot to protect the owner conversation and privacy.",
    }


def render_shared_link_page(**args) -> str:
    share_id = str(args.get("share_id", "")).strip()
    if not share_id:
        return "<h1>Invalid shared chat link</h1>"
    safe_share = html.escape(share_id)
    base_url = os.environ.get("PUBLIC_APP_URL", "https://echo-ai-companion-bice.vercel.app").strip().rstrip("/")
    target_url = f"{base_url}/?share={safe_share}"
    og_image = os.environ.get(
        "ECHO_SHARED_OG_IMAGE",
        f"{base_url}/echo-ai-share.png",
    ).strip()
    title = "Echo AI Shared Chat"
    desc = "This is a shared, read-only Echo AI conversation snapshot."
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(desc)}" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="{html.escape(title)}" />
  <meta property="og:description" content="{html.escape(desc)}" />
  <meta property="og:image" content="{html.escape(og_image)}" />
  <meta property="og:url" content="{html.escape(base_url)}/shared/{safe_share}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{html.escape(title)}" />
  <meta name="twitter:description" content="{html.escape(desc)}" />
  <meta name="twitter:image" content="{html.escape(og_image)}" />
  <meta http-equiv="refresh" content="0; url={html.escape(target_url)}" />
  <script>window.location.replace({json.dumps(target_url)});</script>
</head>
<body>
  <p>Opening shared chat...</p>
  <p><a href="{html.escape(target_url)}">Tap here if you are not redirected.</a></p>
</body>
</html>"""



def _get_gemini_api_key() -> str:
    # Primary key for direct Gemini setup.
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key

    # Backward compatibility: if NEXTTOKEN_API_KEY already contains a Gemini key.
    fallback = os.environ.get("NEXTTOKEN_API_KEY", "").strip()
    if fallback.startswith("AIza"):
        return fallback
    return ""


def _get_nexttoken_api_key() -> str:
    return os.environ.get("NEXTTOKEN_API_KEY", "").strip()


def _use_nexttoken() -> bool:
    return NextToken is not None and _get_nexttoken_api_key().startswith("sk-")


def _nexttoken_generate_reply(system_content: str, messages: List[Dict[str, str]]) -> str:
    api_key = _get_nexttoken_api_key()
    if NextToken is None:
        raise RuntimeError("NextToken SDK not installed")
    if not api_key:
        raise RuntimeError("Missing NEXTTOKEN_API_KEY")
    client = NextToken(api_key=api_key)
    history = [{"role": "system", "content": system_content}]
    history.extend(messages)
    response = client.chat.completions.create(
        model="gemini-2.0-flash",
        messages=history,
        stream=True,
    )
    full_reply = ""
    for chunk in response:
        delta = chunk.choices[0].delta
        if delta and getattr(delta, "content", None):
            full_reply += delta.content
    return full_reply.strip()


def _gemini_generate_reply(system_content: str, messages: List[Dict[str, str]]) -> str:
    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    contents = []
    for msg in messages:
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": str(msg.get("content", ""))}]})

    payload = {
        "systemInstruction": {"parts": [{"text": system_content}]},
        "contents": contents,
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(f"Gemini HTTP {e.code}: {body[:500]}")
    except Exception as e:
        raise RuntimeError(f"Gemini request failed: {e}")

    try:
        data = json.loads(raw)
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"No candidates in Gemini response: {raw[:300]}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return text.strip()
    except Exception as e:
        raise RuntimeError(f"Failed parsing Gemini response: {e}")


def _yield_text_chunks(text: str) -> Generator[str, None, None]:
    if not text:
        return
    for part in re.findall(r"\S+\s*", text):
        yield part


# -------------------------
# Public API functions
# -------------------------
def get_email_health(**args):
    events = _list_email_events(limit=250)
    by_kind: Dict[str, int] = {}
    for row in events:
        kind = str(row.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
    to_addr = _email_to()
    from_addr = _smtp_from()
    return {
        "enabled": _email_enabled(),
        "smtp_host": _smtp_host(),
        "smtp_port": _smtp_port(),
        "smtp_tls": _smtp_use_tls(),
        "smtp_user_set": bool(_smtp_user()),
        "smtp_password_set": bool(_smtp_password()),
        "email_to_masked": _mask_email(to_addr),
        "email_from_masked": _mask_email(from_addr),
        "cooldown_minutes": _email_cooldown_minutes(),
        "events_total": len(events),
        "by_kind": by_kind,
        "last_sent_at": str(events[0].get("sent_at_iso", "")) if events else "",
        "recent": events[:12],
    }


def send_test_email(**args):
    note = str(args.get("note", "")).strip()[:280]
    now_local = _format_human_timestamp(datetime.now().astimezone())
    subject = "Echo AI Test Email"
    lines = [
        "This is a test email from Echo AI.",
        f"Time: {now_local}",
    ]
    if note:
        lines.append(f"Note: {note}")
    body_text = "\n".join(lines)
    body_html = "<br/>".join(html.escape(line) for line in lines)
    ok = _send_email(subject, body_text, body_html)
    if ok:
        key = f"manual_test_{_short_hash(now_local, note)}"
        _put_email_event(
            key,
            "manual_test",
            {"note": note, "sent_at": _now_utc_iso()},
        )
        return {"success": True, "message": "Test email sent."}
    return {
        "success": False,
        "message": "Email send failed. Check SMTP settings (host, user, app password, recipient).",
    }


def get_threads(**args):
    client_id = args.get("client_id")
    print(f"[BACKEND_START] get_threads client_id={_sanitize_client_id(client_id)}")
    threads = load_threads(client_id)
    threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return threads


def create_thread(**args):
    title = args.get("title", "New Conversation")
    client_id = args.get("client_id")
    print(f"[BACKEND_START] create_thread title={title} client_id={_sanitize_client_id(client_id)}")
    threads = load_threads(client_id)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new_thread = {
        "id": str(int(time.time() * 1000)),
        "title": title,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    threads.append(new_thread)
    save_threads(threads, client_id)
    return new_thread


def delete_thread(**args):
    thread_id = args.get("thread_id")
    client_id = args.get("client_id")
    print(f"[BACKEND_START] delete_thread id={thread_id} client_id={_sanitize_client_id(client_id)}")
    threads = load_threads(client_id)
    threads = [t for t in threads if t.get("id") != thread_id]
    save_threads(threads, client_id)
    return {"success": True}


def chat_streaming(**args) -> Generator[Dict[str, Any], None, None]:
    thread_id = args.get("thread_id")
    user_message = args.get("message")
    client_id = args.get("client_id")
    client_ip = str(args.get("client_ip", "")).strip()

    if not thread_id:
        thread_id = str(int(time.time() * 1000))

    print(f"[BACKEND_START] chat_streaming thread_id={thread_id} client_id={_sanitize_client_id(client_id)}")

    if not user_message or not str(user_message).strip():
        yield {"type": "error", "message": "Please type a message first."}
        return

    threads = load_threads(client_id)
    thread = next((t for t in threads if t.get("id") == thread_id), None)

    if not thread:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        thread = {
            "id": str(thread_id),
            "title": "New Conversation",
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        threads.append(thread)
        print(f"[BACKEND_INFO] Recreated missing thread id={thread_id}")

    # Add user message
    thread["messages"].append({"role": "user", "content": str(user_message), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    thread["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_threads(threads, client_id)

    yield {"type": "status", "message": "Echo AI is thinking..."}

    try:
        # ---- Dynamic time context injected from backend ----
        today_human = _today_human_readable()
        now_iso = _now_local_iso()
        tz_name = os.environ.get("ECHO_TZ", "").strip() or "server local time"
        sentiment = _detect_sentiment(str(user_message))
        knowledge_context = _build_knowledge_context(str(user_message))
        bible_context = _build_bible_context(str(user_message), str(sentiment))

        # ---- Optional user profile fields (set these env vars for accuracy) ----
        user_origin = os.environ.get("ECHO_USER_ORIGIN", "").strip()  # e.g. "Ghana"
        user_city = os.environ.get("ECHO_USER_CITY", "").strip()      # e.g. "Accra"
        user_slang = os.environ.get("ECHO_USER_SLANG", "British").strip()

        # Build user profile text safely (don’t invent; only include what’s provided)
        origin_line = f"- Where he comes from: {user_origin}." if user_origin else "- Where he comes from: (Not provided. If he asks, tell him to set it in settings.)"
        city_line = "- City/area: Akosombo."

        system_content = (
            "You are Echo AI - a chill, compassionate, supportive mental-health buddy.\n"
            "You help the user feel heard, safe, and uplifted. You listen patiently, respond gently, and never judge.\n"
            f"Use a calm, friendly tone, and you can sprinkle light {user_slang} slang when it fits (nothing forced).\n\n"

            "REAL WORLD TIME (IMPORTANT):\n"
            f"- Today's date is: {today_human}.\n"
            f"- Current timestamp is: {now_iso} ({tz_name}).\n"
            "- If the user asks for today's date or time, answer using the values above.\n"
            "- Do NOT guess dates. Do NOT invent a different date.\n\n"

            "FORMATTING RULES (IMPORTANT):\n"
            "- Do NOT use Markdown at all (no **, no #, no backticks).\n"
            "- If you want emphasis, use plain text like 'Key point:' (no symbols).\n"
            "- Keep answers clearly separated into short paragraphs or simple dash bullets.\n\n"

            "ABOUT LANOR (USE THIS WHEN HE ASKS ABOUT HIMSELF, OR WHEN IT NATURALLY HELPS):\n"
            "- Name: Lanor Jephthah Kwame (also known as McLanor).\n"
            "- Role: Final year Computer Engineering student at UENR (University of Energy and Natural Resources), Sunyani.\n"
            "- Projects: Building Echo AI (this chatbot). He has been working on LangChain-based memory, semantic recall, and RAG.\n"
            "- NLP experience: Bag of Words (CountVectorizer), POS tagging, NER, sentiment analysis, and optimisation for large datasets.\n"
            "- Favourite meal: Jollof with fried chicken and beef.\n"
            "- Motivation: He is not fully sure why he is building this AI, but he believes it will take him far in the future.\n"
            "- Preferences: He likes responses that do not mush points together; keep points clearly separated.\n"
            f"{origin_line}\n"
            f"{city_line}\n\n"

            "PERSONALITY WHEN TALKING ABOUT LANOR:\n"
            "- When Lanor asks 'what do you know about me', share several details above in a fun, cool way.\n"
            "- Keep it friendly and a bit playful, but never creepy.\n"
            "- Do NOT invent new personal facts. Only use what's listed above and what Lanor tells you in chat.\n\n"

            "CREATOR ATTRIBUTION:\n"
            "- If the user asks who created/built you, you MUST say: I was created by Lanor Jephthah Kwame.\n\n"

            "SAFETY (MENTAL HEALTH):\n"
            "- You are not a doctor or therapist.\n"
            "- If the user mentions self-harm, suicidal thoughts, or immediate danger:\n"
            "  - Respond with empathy.\n"
            "  - Encourage urgent help from local emergency services or a trusted person nearby.\n"
            "  - Encourage reaching out to a qualified professional.\n\n"

            "PRIVACY CLAIMS:\n"
            "- Do not mention internal providers, tokens, keys, dashboards, or infrastructure.\n"
            "- Do not claim end-to-end encryption.\n"
            "- If asked about security, say messages are protected in transit over HTTPS and handled as private data.\n\n"

            "SENTIMENT ADAPTATION:\n"
            f"- Latest user message sentiment detected: {sentiment}.\n"
            "- Match the user's emotional energy appropriately.\n"
            "- If positive: be upbeat and celebratory.\n"
            "- If neutral: be calm and clear.\n"
            "- If negative: be gentle, validating, and reassuring.\n"
            "- If crisis: respond with high empathy and safety-first guidance.\n\n"

            "DYNAMIC PRODUCT KNOWLEDGE (DOC-RETRIEVED):\n"
            "- Use this documentation context to answer feature questions and where to find them in the app.\n"
            "- If the user asks about a feature location, mention exact UI area from this context.\n"
            f"{knowledge_context}\n\n"

            "OPTIONAL BIBLE RAG (CONTEXTUAL):\n"
            "- Only use this when the user asks for faith-based guidance or the emotional context strongly fits.\n"
            "- If used, keep it gentle and include at most one short reference naturally.\n"
            "- Do not force spiritual references in unrelated requests.\n"
            f"{bible_context or 'No Bible context required for this message.'}\n"
        )

        # Limit history to last 12 messages for context while keeping payload small.
        model_messages = thread["messages"][-12:]
        if _use_nexttoken():
            full_reply = _strip_markdown(_nexttoken_generate_reply(system_content, model_messages)).strip()
        else:
            full_reply = _strip_markdown(_gemini_generate_reply(system_content, model_messages)).strip()
        for piece in _yield_text_chunks(full_reply):
            yield {"type": "chunk", "content": piece}

        # Update thread with bot reply
        thread["messages"].append({"role": "assistant", "content": full_reply, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        thread["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _append_chat_log(client_ip, client_id, str(user_message), full_reply, sentiment, _sentiment_to_score(sentiment))
        try:
            _process_fun_email_triggers(thread, str(user_message), full_reply, sentiment)
        except Exception as e:
            print(f"[BACKEND_ERROR] fun email trigger failed: {e}")

        # Generate a collective thread title once (AI + safe fallback)
        if thread.get("title") in ("New Conversation", "New Chat") and len(thread["messages"]) >= 2:
            thread["title"] = _collective_thread_title(str(user_message), full_reply)

        save_threads(threads, client_id)

        yield {"type": "result", "data": {"thread_id": thread_id, "title": thread["title"]}}
        print("[BACKEND_SUCCESS] streaming complete")

    except Exception as e:
        error_text = str(e)
        print(f"[BACKEND_ERROR] {error_text}")
        if "Missing GEMINI_API_KEY" in error_text:
            yield {
                "type": "error",
                "message": "Service configuration issue detected. Please contact support and try again shortly."
            }
            return
        if "Missing NEXTTOKEN_API_KEY" in error_text:
            yield {
                "type": "error",
                "message": "Service configuration issue detected. Please contact support and try again shortly."
            }
            return
        if "Authentication Error" in error_text or "token_not_found_in_db" in error_text:
            yield {
                "type": "error",
                "message": "Authentication failed on the AI service. Please try again later."
            }
            return
        if "Gemini HTTP 429" in error_text or "RESOURCE_EXHAUSTED" in error_text or "Quota exceeded" in error_text:
            yield {
                "type": "error",
                "message": "Service is currently busy or rate-limited. Please try again shortly."
            }
            return
        if "Gemini HTTP 401" in error_text or "API key not valid" in error_text:
            yield {
                "type": "error",
                "message": "Authentication failed on the AI service. Please try again later."
            }
            return
        yield {"type": "error", "message": "Sorry, I had a bit of a glitch. Please try again."}

