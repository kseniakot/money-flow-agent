from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    tg_token: str
    lm_base_url: str
    lm_model: str
    lm_api_key: str
    db_path: Path
    whisper_bin: str
    whisper_model: str
    default_currency: str
    nbrb_url: str


def load_config() -> Config:
    return Config(
        tg_token=os.environ.get("TG_TOKEN", ""),
        lm_base_url=os.environ.get("LM_BASE_URL", "http://localhost:1234/v1"),
        lm_model=os.environ.get("LM_MODEL", "qwen3-vl-8b-instruct-mlx"),
        lm_api_key=os.environ.get("LM_API_KEY", "lm-studio"),
        db_path=Path(os.environ.get("DB_PATH", str(ROOT / "expenses.sqlite"))),
        whisper_bin=os.environ.get("WHISPER_BIN", "whisper"),
        whisper_model=os.environ.get("WHISPER_MODEL", "medium"),
        default_currency=os.environ.get("DEFAULT_CURRENCY", "BYN"),
        nbrb_url=os.environ.get(
            "NBRB_URL", "https://api.nbrb.by/exrates/rates/{cur}?parammode=2"
        ),
    )


config = load_config()
