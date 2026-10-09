import base64
import hashlib
import hmac
import html
import json
import os
import secrets
from typing import Any, Callable, Dict, List, Optional


def create_share_link(
    *,
    thread_id: str,
    client_id: str,
    load_threads: Callable[[Any], List[Dict[str, Any]]],
    now_utc_iso: Callable[[], str],
    put_shared_snapshot: Callable[[str, Dict[str, Any]], None],
) -> Dict[str, Any]:
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
        "created_at": str(thread.get("created_at", now_utc_iso())),
        "updated_at": str(thread.get("updated_at", now_utc_iso())),
    }
    share_id = secrets.token_urlsafe(12)
    put_shared_snapshot(share_id, snapshot)
    base_url = os.environ.get("PUBLIC_APP_URL", "https://echo-ai-companion-bice.vercel.app").strip().rstrip("/")
    return {"share_id": share_id, "url": f"{base_url}/shared/{share_id}"}


def import_shared_thread(
    *,
    share_id: str,
    sanitize_client_id: Callable[[Any], str],
    get_shared_snapshot: Callable[[str], Optional[Dict[str, Any]]],
    load_threads: Callable[[Any], List[Dict[str, Any]]],
    now_utc_iso: Callable[[], str],
) -> Dict[str, Any]:
    if not share_id:
        return {"error": "share_id is required"}

    snap = get_shared_snapshot(share_id)
    if isinstance(snap, dict):
        imported_id = f"shared-{share_id}"
        imported_thread = {
            "id": imported_id,
            "title": str(snap.get("title", "Shared Conversation")),
            "messages": snap.get("messages", []),
            "created_at": str(snap.get("created_at", now_utc_iso())),
            "updated_at": str(snap.get("updated_at", now_utc_iso())),
        }
        return {
            "thread": imported_thread,
            "readonly": True,
            "reason": "This is a shared read-only snapshot to protect the owner conversation and privacy.",
        }

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
                "created_at": str(source_thread.get("created_at", now_utc_iso())),
                "updated_at": str(source_thread.get("updated_at", now_utc_iso())),
            }
            return {
                "thread": imported_thread,
                "readonly": True,
                "reason": "This is a shared read-only snapshot to protect the owner conversation and privacy.",
            }
        source_client_id = sanitize_client_id(payload.get("c"))
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
        "created_at": str(source_thread.get("created_at", now_utc_iso())),
        "updated_at": str(source_thread.get("updated_at", now_utc_iso())),
    }
    return {
        "thread": imported_thread,
        "readonly": True,
        "reason": "This is a shared read-only snapshot to protect the owner conversation and privacy.",
    }


def render_shared_link_page(
    *,
    share_id: str,
    get_shared_snapshot: Callable[[str], Optional[Dict[str, Any]]],
) -> str:
    if not share_id:
        return "<h1>Invalid shared chat link</h1>"
    safe_share = html.escape(share_id)
    base_url = os.environ.get("PUBLIC_APP_URL", "https://echo-ai-companion-bice.vercel.app").strip().rstrip("/")
    target_url = f"{base_url}/?share={safe_share}"
    snap = get_shared_snapshot(share_id) or {}
    thread_title = str(snap.get("title", "Shared Chat")).strip() or "Shared Chat"
    messages = snap.get("messages", []) if isinstance(snap.get("messages"), list) else []
    first_user = ""
    for m in messages:
        if isinstance(m, dict) and str(m.get("role", "")) == "user":
            first_user = str(m.get("content", "")).strip()
            if first_user:
                break

    og_image = os.environ.get(
        "ECHO_SHARED_OG_IMAGE",
        f"{base_url}/echo-ai-shared-link.png?v=20260227",
    ).strip()
    title = f"Echo AI Shared Chat - {thread_title}"
    desc = (
        f"Read-only shared conversation: {first_user[:120]}"
        if first_user
        else "This is a shared, read-only Echo AI conversation snapshot."
    )
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
  <meta property="og:image:secure_url" content="{html.escape(og_image)}" />
  <meta property="og:image:type" content="image/png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:site_name" content="Echo AI" />
  <meta property="og:url" content="{html.escape(base_url)}/shared/{safe_share}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{html.escape(title)}" />
  <meta name="twitter:description" content="{html.escape(desc)}" />
  <meta name="twitter:image" content="{html.escape(og_image)}" />
  <meta name="twitter:url" content="{html.escape(base_url)}/shared/{safe_share}" />
  <meta http-equiv="refresh" content="0; url={html.escape(target_url)}" />
  <script>window.location.replace({json.dumps(target_url)});</script>
</head>
<body>
  <p>Opening shared chat...</p>
  <p><a href="{html.escape(target_url)}">Tap here if you are not redirected.</a></p>
</body>
</html>"""

