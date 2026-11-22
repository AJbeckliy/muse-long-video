"""Per-install paths. Installer writes settings outside the shareable payload."""
import json
import os
from importlib.util import find_spec
from pathlib import Path
HERE = Path(__file__).resolve().parent
FILE = Path(os.environ.get("MUSE_STUDIO_SETTINGS", HERE/"settings.local.json"))
SETTINGS = json.loads(FILE.read_text(encoding="utf-8-sig")) if FILE.is_file() else {}
if SETTINGS.get("audio_packages"):
    import site
    site.addsitedir(SETTINGS["audio_packages"])
HOME = Path(os.environ.get("CODEX_HOME", Path.home()/".codex"))
def location(name, fallback):
    return Path(SETTINGS.get(name) or fallback).expanduser().resolve()
WORKSPACE = location("workspace",Path.home()/"Videos"/"Muse工作台")
CACHE = location("cache",WORKSPACE/"Cache")
SKILL = location("skill", HOME/"skills/muse-long-video")
BUNDLE = location("seedvc",CACHE/"SeedVC-Portable")
QWEN = location("qwen",CACHE/"huggingface/CN-Voice-Qwen3-1.7B-Base")
QWEN_LIB = location("qwen_lib", CACHE/"qwen-lib")
WHISPER = location("whisper",CACHE/"whisper/base.pt")
DBS = location("dbs",CACHE/"huggingface/hub/models--JusperLee--DBS-TIGER-DnR/snapshots/22da7d4cd3ea63f9365181008bff1c0d2ab6fb2b")
AUDIO = bool(SETTINGS.get("audio",False)) and (DBS/"model.safetensors").is_file() and (DBS/"config.json").is_file() and (CACHE/"MuseAudio/dbs-code/dbs").is_dir() and all(find_spec(n) for n in ("torch","numpy","scipy","soundfile"))
seed_ready = (Path(SETTINGS["seed_models"])/"whisper/encoder.fp16.safetensors").is_file() if SETTINGS.get("seed_models") else (BUNDLE/"app/worker.py").is_file() and (BUNDLE/"runtime/python.exe").is_file()
DUB = bool(AUDIO and SETTINGS.get("dub",True) and (QWEN/"config.json").is_file() and WHISPER.is_file()
           and (CACHE/"MuseAudio/yamnet/yamnet.onnx").is_file() and seed_ready
           and (find_spec("qwen_tts") or (QWEN_LIB/"qwen_tts").is_dir()) and find_spec("whisper") and find_spec("onnxruntime"))
PORT = int(os.environ.get("MUSE_STUDIO_PORT",SETTINGS.get("port",8786)))
