from typing import Any, Dict, Generator
import core_engine as core


def chat_streaming(**args) -> Generator[Dict[str, Any], None, None]:
    return core.chat_streaming(**args)


def summarize_thread(**args) -> Dict[str, Any]:
    return core.summarize_thread(**args)
