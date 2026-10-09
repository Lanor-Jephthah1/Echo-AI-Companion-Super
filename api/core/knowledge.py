import json
import os
import re
from typing import Any, Dict, List

_KB_CACHE = {"sig": "", "sections": []}
_BIBLE_RAG_CACHE = {"mtime": 0.0, "chunks": []}


def _knowledge_file_paths() -> List[str]:
    env_paths = os.environ.get("ECHO_KB_FILES", "").strip()
    base_dir = os.path.dirname(os.path.dirname(__file__))
    if env_paths:
        out = []
        for p in env_paths.split(","):
            raw = p.strip()
            if not raw:
                continue
            out.append(raw if os.path.isabs(raw) else os.path.join(base_dir, raw))
        if out:
            return out
    return [os.path.join(base_dir, "echo_knowledge.md")]


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
                    "Echo AI supports multi-thread chat, chat summary, emotion pulse, "
                    "share links, theme toggle, emoji picker, copy reply, and social links."
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
    ranked = sorted(sections, key=lambda s: _kb_relevance(user_message, s), reverse=True)
    chosen = [s for s in ranked if _kb_relevance(user_message, s) > 0][:max_sections]
    if not chosen:
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
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "bible_rag.json")


def _default_bible_chunks() -> List[Dict[str, Any]]:
    return [
        {"ref": "Psalm 34:18", "text": "The Lord is close to the brokenhearted and saves those who are crushed in spirit.", "tags": ["sad", "grief", "comfort"]},
        {"ref": "Isaiah 41:10", "text": "Do not fear, for I am with you; do not be dismayed, for I am your God.", "tags": ["fear", "anxiety", "courage"]},
        {"ref": "Philippians 4:6-7", "text": "Do not be anxious about anything; in every situation, by prayer and petition, present your requests to God.", "tags": ["anxiety", "worry", "prayer"]},
        {"ref": "Matthew 11:28", "text": "Come to me, all you who are weary and burdened, and I will give you rest.", "tags": ["stress", "tired", "rest"]},
        {"ref": "Romans 8:28", "text": "In all things God works for the good of those who love him.", "tags": ["hope", "purpose"]},
        {"ref": "Jeremiah 29:11", "text": "For I know the plans I have for you, plans to prosper you and not to harm you, plans to give you hope and a future.", "tags": ["future", "hope"]},
        {"ref": "Proverbs 3:5-6", "text": "Trust in the Lord with all your heart and lean not on your own understanding.", "tags": ["guidance", "decision"]},
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
    direct = ["bible", "scripture", "verse", "god", "jesus", "christ", "faith", "pray", "prayer", "church", "holy spirit"]
    emotional = ["hopeless", "anxious", "anxiety", "afraid", "scared", "depressed", "sad", "broken", "hurt", "lonely", "grief", "discouraged", "overwhelmed"]
    if any(k in t for k in direct):
        return True
    if any(k in t for k in emotional):
        return True
    return str(sentiment or "").lower() in {"negative", "crisis"}


def _bible_relevance(query: str, chunk: Dict[str, Any]) -> int:
    q_tokens = set(_tokenize_words(query))
    if not q_tokens:
        return 0
    text_tokens = set(_tokenize_words(chunk.get("text", "")))
    ref_tokens = set(_tokenize_words(chunk.get("ref", "")))
    tags_tokens = set(_tokenize_words(" ".join(chunk.get("tags", []))))
    score = len(q_tokens.intersection(text_tokens))
    score += 2 * len(q_tokens.intersection(tags_tokens))
    score += 3 * len(q_tokens.intersection(ref_tokens))
    return score


def _build_bible_context(user_message: str, sentiment: str, max_chunks: int = 2) -> str:
    if not _needs_bible_context(user_message, sentiment):
        return ""
    chunks = _load_bible_chunks()
    ranked = sorted(chunks, key=lambda c: _bible_relevance(user_message, c), reverse=True)
    selected = [c for c in ranked if _bible_relevance(user_message, c) > 0][:max_chunks] or chunks[:max_chunks]
    lines: List[str] = []
    for idx, c in enumerate(selected, start=1):
        lines.append(f"{idx}. {c.get('ref', '')}")
        lines.append(f"   {c.get('text', '')}")
    return "\n".join(lines).strip()

