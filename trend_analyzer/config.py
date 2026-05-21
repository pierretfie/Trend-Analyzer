import os
from pathlib import Path

DATA_DIR_NAME = ".Trend_analyzer"
DB_FILENAME = "trend_analyzer.db"
# Override with absolute path if you cannot use ~/ (defaults to ~/.Trend_analyzer/).
_ENV_DIR = os.environ.get("TREND_ANALYZER_DATA_DIR") or os.environ.get("TA_DATA_DIR")


def data_dir() -> Path:
    if _ENV_DIR:
        p = Path(_ENV_DIR).expanduser().resolve()
    else:
        p = (Path.home() / DATA_DIR_NAME).resolve()
    p.mkdir(parents=True, mode=0o700, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / DB_FILENAME
