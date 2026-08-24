import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class Config:
    tg_token: str
    lm_base_url: str
    lm_model: str
    lm_api_key: str
    db_path: Path
    checkpoint_path: Path
    backup_dir: Path
    backup_keep: int
    whisper_bin: str
    whisper_model: str
    default_currency: str
    nbrb_url: str
    log_level: str


def load_config() -> Config:
    return Config(
        tg_token=os.environ.get("TG_TOKEN", ""),
        lm_base_url=os.environ.get("LM_BASE_URL", "http://localhost:1234/v1"),
        lm_model=os.environ.get("LM_MODEL", "qwen3-vl-8b-instruct-mlx"),
        lm_api_key=os.environ.get("LM_API_KEY", "lm-studio"),
        db_path=_resolve(os.environ.get("DB_PATH", "expenses.sqlite")),
        checkpoint_path=_resolve(os.environ.get("CHECKPOINT_PATH", "checkpoints.sqlite")),
        backup_dir=_resolve(os.environ.get("BACKUP_DIR", "backups")),
        backup_keep=int(os.environ.get("BACKUP_KEEP", "20")),
        whisper_bin=os.environ.get("WHISPER_BIN", "whisper"),
        whisper_model=os.environ.get("WHISPER_MODEL", "medium"),
        default_currency=os.environ.get("DEFAULT_CURRENCY", "BYN"),
        nbrb_url=os.environ.get(
            "NBRB_URL", "https://api.nbrb.by/exrates/rates/{cur}?parammode=2"
        ),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )


config = load_config()
