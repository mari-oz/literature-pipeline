from __future__ import annotations

import os
from pathlib import Path
import yaml


def load_config() -> dict:
    config_path = Path(os.environ.get("CONFIG_PATH", "/config/config.yaml"))
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    return cfg


def get_db_path(cfg: dict) -> Path:
    db_path = cfg.get("paths", {}).get("db") or os.environ.get("DB_PATH", "/data/pipeline.db")
    return Path(db_path)
