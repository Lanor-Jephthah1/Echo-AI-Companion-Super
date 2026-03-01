from typing import Any, Dict
import core_engine as core


def create_share_link(**args) -> Dict[str, Any]:
    return core.create_share_link(**args)


def import_shared_thread(**args) -> Dict[str, Any]:
    return core.import_shared_thread(**args)


def render_shared_link_page(**args) -> str:
    return core.render_shared_link_page(**args)
