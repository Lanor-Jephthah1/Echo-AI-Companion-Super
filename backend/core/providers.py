import json
import os
import urllib.error
import urllib.request
from typing import Dict, List

try:
    from nexttoken import NextToken
except Exception:
    NextToken = None


def get_gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    fallback = os.environ.get("NEXTTOKEN_API_KEY", "").strip()
    if fallback.startswith("AIza"):
        return fallback
    return ""


def get_nexttoken_api_key() -> str:
    return os.environ.get("NEXTTOKEN_API_KEY", "").strip()


def use_nexttoken() -> bool:
    return NextToken is not None and get_nexttoken_api_key().startswith("sk-")


def nexttoken_generate_reply(system_content: str, messages: List[Dict[str, str]]) -> str:
    api_key = get_nexttoken_api_key()
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


def gemini_generate_reply(system_content: str, messages: List[Dict[str, str]]) -> str:
    api_key = get_gemini_api_key()
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini HTTPError {e.code}: {detail[:260]}")
    except Exception as e:
        raise RuntimeError(f"Gemini request failed: {e}")

    cands = data.get("candidates", [])
    if not cands:
        raise RuntimeError("Gemini returned no candidates")
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text

