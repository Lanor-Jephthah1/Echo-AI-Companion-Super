import os
import json
import time
import re
from typing import Generator, Any, Dict, List, Optional
from datetime import datetime, timezone

from nexttoken import NextToken

# Path for persistent storage
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
THREADS_FILE = os.path.join(DATA_DIR, "threads.json")


# -------------------------
# Storage helpers
# -------------------------
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(THREADS_FILE):
        with open(THREADS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def load_threads() -> List[Dict[str, Any]]:
    ensure_data_dir()
    try:
        with open(THREADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[BACKEND_ERROR] Failed to load threads: {e}")
        return []


def save_threads(threads: List[Dict[str, Any]]) -> None:
    ensure_data_dir()
    try:
        with open(THREADS_FILE, "w", encoding="utf-8") as f:
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


# -------------------------
# Public API functions
# -------------------------
def get_threads(**args):
    print("[BACKEND_START] get_threads")
    threads = load_threads()
    threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return threads


def create_thread(**args):
    title = args.get("title", "New Conversation")
    print(f"[BACKEND_START] create_thread title={title}")
    threads = load_threads()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new_thread = {
        "id": str(int(time.time() * 1000)),
        "title": title,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    threads.append(new_thread)
    save_threads(threads)
    return new_thread


def delete_thread(**args):
    thread_id = args.get("thread_id")
    print(f"[BACKEND_START] delete_thread id={thread_id}")
    threads = load_threads()
    threads = [t for t in threads if t.get("id") != thread_id]
    save_threads(threads)
    return {"success": True}


def chat_streaming(**args) -> Generator[Dict[str, Any], None, None]:
    thread_id = args.get("thread_id")
    user_message = args.get("message")

    print(f"[BACKEND_START] chat_streaming thread_id={thread_id}")

    if not thread_id:
        yield {"type": "error", "message": "Missing thread_id"}
        return

    if not user_message or not str(user_message).strip():
        yield {"type": "error", "message": "Please type a message first."}
        return

    threads = load_threads()
    thread = next((t for t in threads if t.get("id") == thread_id), None)

    if not thread:
        yield {"type": "error", "message": "Thread not found"}
        return

    # Add user message
    thread["messages"].append({"role": "user", "content": str(user_message)})
    thread["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_threads(threads)

    yield {"type": "status", "message": "Echo AI is thinking..."}

    try:
        client = NextToken()

        # ---- Dynamic time context injected from backend ----
        today_human = _today_human_readable()
        now_iso = _now_local_iso()
        tz_name = os.environ.get("ECHO_TZ", "").strip() or "server local time"

        # ---- Optional user profile fields (set these env vars for accuracy) ----
        user_origin = os.environ.get("ECHO_USER_ORIGIN", "").strip()  # e.g. "Ghana"
        user_city = os.environ.get("ECHO_USER_CITY", "").strip()      # e.g. "Accra"
        user_slang = os.environ.get("ECHO_USER_SLANG", "British").strip()

        # Build user profile text safely (don’t invent; only include what’s provided)
        origin_line = f"- Where he comes from: {user_origin}." if user_origin else "- Where he comes from: (Not provided. If he asks, tell him to set it in settings.)"
        city_line = f"- City/area: {user_city}." if user_city else "- City/area: (Not provided.)"

        system_content = (
            "You are Echo AI — a chill, compassionate, supportive mental-health buddy.\n"
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
            "- Role: Engineer and Level 300 Computer Engineering student.\n"
            "- Projects: Building Echo AI (this chatbot). He’s been working on LangChain-based memory, semantic recall, and RAG.\n"
            "- NLP experience: Bag of Words (CountVectorizer), POS tagging, NER, sentiment analysis, and optimisation for large datasets.\n"
            "- Preferences: He likes responses that don’t mush points together; keep points clearly separated.\n"
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
            "  - Encourage reaching out to a qualified professional.\n"
        )

        # Build message history for context
        history = [{"role": "system", "content": system_content}]

        # Limit history to last 12 messages for better context but still efficient
        for msg in thread["messages"][-12:]:
            history.append({"role": msg["role"], "content": msg["content"]})

        response = client.chat.completions.create(
            model="gemini-2.0-flash",
            messages=history,
            stream=True,
        )

        full_reply = ""
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and getattr(delta, "content", None):
                content = _strip_markdown(delta.content)
                if content:
                    full_reply += content
                    yield {"type": "chunk", "content": content}

        full_reply = _strip_markdown(full_reply).strip()

        # Update thread with bot reply
        thread["messages"].append({"role": "assistant", "content": full_reply})
        thread["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Generate a title if it was default
        if thread.get("title") in ("New Conversation", "New Chat") and len(thread["messages"]) >= 2:
            um = str(user_message).strip()
            thread["title"] = um[:30] + ("..." if len(um) > 30 else "")

        save_threads(threads)

        yield {"type": "result", "data": {"thread_id": thread_id, "title": thread["title"]}}
        print("[BACKEND_SUCCESS] streaming complete")

    except Exception as e:
        print(f"[BACKEND_ERROR] {str(e)}")
        yield {"type": "error", "message": f"Sorry, I had a bit of a glitch. Error: {str(e)}"}