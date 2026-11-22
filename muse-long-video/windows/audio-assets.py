import json,sys,os
from pathlib import Path
import site
site.addsitedir(sys.argv[3])
from huggingface_hub import snapshot_download
settings=Path(sys.argv[1]);cfg=json.loads(settings.read_text(encoding="utf-8-sig"))
sys.path.insert(0,str(settings.parent))
from settings_io import merge_settings
cache=Path(cfg["workspace"])/"Cache"
dbs=snapshot_download("JusperLee/DBS-TIGER-DnR",revision="22da7d4cd3ea63f9365181008bff1c0d2ab6fb2b",allow_patterns=["config.json","model.safetensors"])
sys.path.insert(0,str(cache/"MuseAudio/dbs-code"))
from dbs.models import DBSTIGER
DBSTIGER.from_pretrained(dbs,local_files_only=True)
audio_settings=dict(cache=str(cache),dbs=str(dbs),audio=True,dub=False,audio_python=sys.executable,audio_packages=sys.argv[3])
if sys.argv[2]=="1":
    import whisper, torch, qwen_tts,onnxruntime
    if not torch.cuda.is_available():raise RuntimeError("对白重配需要支持此 PyTorch 的 NVIDIA 显卡。")
    q=os.environ.get("MUSE_QWEN_MODEL") or snapshot_download("Qwen/Qwen3-TTS-12Hz-1.7B-Base",allow_patterns=["*.json","*.safetensors","*.txt","*.model"])
    if not (Path(q)/"model.safetensors").exists() and not (Path(q)/"model.safetensors.index.json").exists():raise RuntimeError("Qwen 权重不完整")
    wh=cache/"whisper";wh.mkdir(exist_ok=True)
    whisper_path=os.environ.get("MUSE_WHISPER_MODEL") or str(wh/"base.pt")
    whisper.load_model(whisper_path if Path(whisper_path).exists() else "base",device="cpu",download_root=str(wh))
    yam=cache/"MuseAudio/yamnet"
    snapshot_download("zeropointnine/yamnet-onnx",local_dir=str(yam),allow_patterns=["yamnet.onnx","yamnet_class_map.csv"])
    onnxruntime.InferenceSession(str(yam/"yamnet.onnx"),providers=["CPUExecutionProvider"])
    from huggingface_hub import hf_hub_download
    from safetensors import safe_open
    from safetensors.torch import save_file
    import hashlib,shutil
    models=cache/"seed-voice-models"
    spec=json.loads((settings.parent.parent/"optional/seed-engine/model-lock.json").read_text(encoding="utf8"))
    for asset in spec["assets"]:
        group={"Plachta/Seed-VC":"seed","funasr/campplus":"seed","openai/whisper-small":"whisper"}.get(asset["repo"],"bigvgan")
        dest=models/group/asset["path"]
        dest.parent.mkdir(parents=True,exist_ok=True)
        if asset.get("encoder_fp16_sha256"):dest=dest.with_name("encoder.fp16.safetensors")
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest()==asset.get("encoder_fp16_sha256",asset["sha256"]):continue
        downloaded=Path(hf_hub_download(asset["repo"],asset["path"],revision=asset["revision"]))
        if hashlib.sha256(downloaded.read_bytes()).hexdigest()!=asset["sha256"]:raise RuntimeError("声音模型下载校验失败")
        if asset.get("encoder_fp16_sha256"):
            with safe_open(str(downloaded),framework="pt",device="cpu") as f:
                enc={k.removeprefix("model.encoder."):f.get_tensor(k).half() for k in f.keys() if k.startswith("model.encoder.")}
            if len(enc)!=187:raise RuntimeError("语音编码器结构异常")
            save_file(enc,str(dest),metadata={"format":"pt"})
        else:shutil.copyfile(downloaded,dest)
    audio_settings.update(dub=True,qwen=q,whisper=whisper_path,seed_models=str(models))
merge_settings(settings,audio_settings)
print("声音组件就绪，请重启审片台服务。")
