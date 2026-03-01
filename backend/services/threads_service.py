from typing import Any, Dict, List
import core_engine as core


def get_threads(**args) -> List[Dict[str, Any]]:
    return core.get_threads(**args)


def create_thread(**args) -> Dict[str, Any]:
    return core.create_thread(**args)


def delete_thread(**args) -> Dict[str, Any]:
    return core.delete_thread(**args)
