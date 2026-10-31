import json
import os
from pathlib import Path


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "PDF2MIDI"
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def default_root() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "PDF2MIDI"


def load() -> dict:
    root = default_root()
    cfg = {"entrada": str(root / "Entrada"), "salida": str(root / "Salida"),
           "misma": False, "bpm": 90, "pedal": False, "musicxml": True, "rehacer": False}
    try:
        cfg.update(json.loads(config_path().read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save(cfg: dict) -> None:
    try:
        config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
