"""Install optional audio modules in a dedicated environment and verify models before enabling."""
import os, subprocess, sys, json
from pathlib import Path
from uuid import uuid4
root=Path(__file__).resolve().parent
settings=root/"studio/settings.local.json"
cfg=json.loads(settings.read_text(encoding="utf-8-sig"))
cache=Path(cfg["workspace"])/"Cache"
env=dict(os.environ,PIP_CACHE_DIR=str(cache/"pip"),HF_HOME=str(cache/"huggingface"),PYTHONUTF8="1")
py=Path(sys.executable)
def run(*args): subprocess.run(list(map(str,args)),env=env,check=True)
full="--full" in sys.argv
existing_dbs=Path(cfg.get("dbs") or cache/"missing-dbs")
existing_packages=Path(cfg.get("audio_packages") or cache/"missing-packages")
if (not full and cfg.get("audio") and (existing_dbs/"config.json").is_file()
        and (existing_dbs/"model.safetensors").is_file() and (cache/"MuseAudio/dbs-code/dbs").is_dir()
        and all((existing_packages/name).is_dir() for name in ("torch","scipy","numpy"))):
    print("去配乐组件已安装。")
    sys.exit(0)
index="cu130" if full else "cpu"
packages=cache/("muse-audio-"+index)
args=[py,"-m","pip","install","--disable-pip-version-check","--target",packages,"--extra-index-url","https://download.pytorch.org/whl/"+index,"torch==2.9.1+"+index,"torchaudio==2.9.1+"+index,"numpy<2.4","scipy","soundfile","einops","huggingface-hub<1","safetensors","rotary-embedding-torch","omegaconf"]
if full:
    args.extend(["munch","qwen-tts==0.1.1","onnxruntime","librosa"])
    args.extend(sorted((root/"optional/wheels").glob("*.whl")))
run(*args)
import shutil
code=cache/"MuseAudio/dbs-code"
shutil.copytree(root/"optional/dbs-code",code,dirs_exist_ok=True)
run(py,root/"audio-assets.py",settings,str(int(full)),packages)
