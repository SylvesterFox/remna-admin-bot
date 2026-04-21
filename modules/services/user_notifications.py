from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _resolve_data_dir() -> Path:
    """Pick a writable directory for local bot state."""
    candidates = []

    env_dir = os.getenv("BOT_DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    candidates.extend([
        Path("/app/logs"),
        Path("/tmp/remna-admin-bot"),
    ])

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            test_file = candidate / ".write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return candidate
        except Exception as exc:
            logger.warning("Data dir %s is not writable: %s", candidate, exc)

    raise RuntimeError("No writable directory available for bot local state")


_DATA_DIR = _resolve_data_dir()
_SETTINGS_PATH = _DATA_DIR / "user_notifications.json"


def _ensure_storage() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _SETTINGS_PATH.exists():
        _SETTINGS_PATH.write_text("{}", encoding="utf-8")


def _load_data() -> Dict[str, Any]:
    _ensure_storage()
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to load user notification settings: %s", exc)
        return {}


def _save_data(data: Dict[str, Any]) -> None:
    _ensure_storage()
    _SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def notifications_enabled(telegram_id: int) -> bool:
    data = _load_data()
    return bool(data.get(str(telegram_id), {}).get("enabled", False))


def set_notifications_enabled(telegram_id: int, enabled: bool) -> None:
    data = _load_data()
    record = data.setdefault(str(telegram_id), {})
    record["enabled"] = enabled
    _save_data(data)


def get_last_notification_marker(telegram_id: int) -> str | None:
    data = _load_data()
    return data.get(str(telegram_id), {}).get("last_notification_marker")


def set_last_notification_marker(telegram_id: int, marker: str) -> None:
    data = _load_data()
    record = data.setdefault(str(telegram_id), {})
    record["last_notification_marker"] = marker
    record["last_notification_at"] = datetime.now(timezone.utc).isoformat()
    _save_data(data)


def get_enabled_notification_user_ids() -> list[int]:
    data = _load_data()
    result = []
    for key, value in data.items():
        if value.get("enabled"):
            try:
                result.append(int(key))
            except ValueError:
                continue
    return result
