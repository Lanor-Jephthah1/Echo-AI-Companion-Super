from typing import Any, Dict, List
import core_engine as core


def get_chat_logs(limit: int = 200) -> List[Dict[str, Any]]:
    return core.get_chat_logs(limit=limit)


def get_email_health(**args) -> Dict[str, Any]:
    return core.get_email_health(**args)


def send_test_email(**args) -> Dict[str, Any]:
    return core.send_test_email(**args)
