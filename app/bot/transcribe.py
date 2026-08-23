import json
import subprocess
import tempfile
from pathlib import Path

from app.config import config


def transcribe(audio_path: str) -> str:
    out_dir = tempfile.mkdtemp()
    subprocess.run(
        [
            config.whisper_bin,
            audio_path,
            "--language",
            "Russian",
            "--task",
            "transcribe",
            "--model",
            config.whisper_model,
            "--output_format",
            "json",
            "--output_dir",
            out_dir,
        ],
        check=True,
        capture_output=True,
    )
    stem = Path(audio_path).stem
    data = json.loads(Path(out_dir, f"{stem}.json").read_text())
    return data["text"].strip()
