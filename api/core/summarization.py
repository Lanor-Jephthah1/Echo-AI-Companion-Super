import json
import re
from typing import Any, Callable, Dict, List, Optional


def strip_markdown(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"(?m)^\s*\*\s+", "- ", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = text.replace("**", "").replace("__", "")
    return text


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


def collective_thread_title(
    first_user_message: str,
    assistant_reply: str,
    *,
    use_nexttoken: Callable[[], bool],
    nexttoken_generate_reply: Callable[[str, List[Dict[str, str]]], str],
    gemini_generate_reply: Callable[[str, List[Dict[str, str]]], str],
) -> str:
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
        if use_nexttoken():
            out = nexttoken_generate_reply(prompt, [{"role": "user", "content": user_context}])
        else:
            out = gemini_generate_reply(prompt, [{"role": "user", "content": user_context}])
        title = _sanitize_title(strip_markdown(out))
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


def _local_thread_summary(thread: Dict[str, Any], *, now_utc_iso: Callable[[], str]) -> Dict[str, Any]:
    messages = thread.get("messages", [])
    user_msgs = [str(m.get("content", "")).strip() for m in messages if str(m.get("role", "")).lower() == "user"]
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
    if any(w in lower_all for w in ["lol", "haha", "funny", "joke", "lmao"]):
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
    if any(w in lower_all for w in ["lol", "haha", "funny"]):
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
        "generated_at": now_utc_iso(),
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


def summarize_thread(
    *,
    thread_id: str,
    client_id: Any,
    load_threads: Callable[[Any], List[Dict[str, Any]]],
    now_utc_iso: Callable[[], str],
    use_nexttoken: Callable[[], bool],
    nexttoken_generate_reply: Callable[[str, List[Dict[str, str]]], str],
    gemini_generate_reply: Callable[[str, List[Dict[str, str]]], str],
) -> Dict[str, Any]:
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
            "generated_at": now_utc_iso(),
            "source": "empty",
        }

    fallback = _local_thread_summary(thread, now_utc_iso=now_utc_iso)
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
        if use_nexttoken():
            raw = nexttoken_generate_reply(prompt, [{"role": "user", "content": transcript}])
        else:
            raw = gemini_generate_reply(prompt, [{"role": "user", "content": transcript}])
        data = _extract_json_block(raw) or {}

        summary = strip_markdown(str(data.get("summary", "")).strip())
        talked_about = _dedupe_keep_order([strip_markdown(str(x)) for x in data.get("talked_about", [])])[:6]
        learned = _dedupe_keep_order([strip_markdown(str(x)) for x in data.get("learned", [])])[:6]

        if not summary or not talked_about or not learned:
            return fallback

        return {
            "title": str(thread.get("title", "Conversation")),
            "message_count": len(messages),
            "summary": summary,
            "talked_about": talked_about,
            "learned": learned,
            "generated_at": now_utc_iso(),
            "source": "ai",
        }
    except Exception:
        return fallback

