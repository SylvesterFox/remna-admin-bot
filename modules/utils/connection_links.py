from __future__ import annotations

from typing import Any


def extract_vless_links(payload: Any) -> list[str]:
    """Collect unique vless:// links from nested API payloads."""
    links: list[str] = []
    seen_links: set[str] = set()
    visited: set[int] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("vless://") and text not in seen_links:
                seen_links.add(text)
                links.append(text)
            return

        if isinstance(value, dict):
            value_id = id(value)
            if value_id in visited:
                return
            visited.add(value_id)
            for nested in value.values():
                visit(nested)
            return

        if isinstance(value, (list, tuple, set)):
            value_id = id(value)
            if value_id in visited:
                return
            visited.add(value_id)
            for nested in value:
                visit(nested)

    visit(payload)
    return links
