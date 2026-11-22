"""Local video soundtrack processing. All offsets use the source timeline."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from uuid import uuid4

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from studio import ReviewError
from edit_video import find_ffmpeg

GPU = threading.Lock()
RATE = 48000
from paths import CACHE, BUNDLE, DBS


def key(*parts):
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:16]


def ff(*args):
    subprocess.run([find_ffmpeg(), "-nostdin", "-v", "error", "-n", *map(str, args)], check=True, capture_output=True)


def split(source, directory):
    import torch
    if not (directory / "ready").exists():
        sys.path.insert(0, str(CACHE / "MuseAudio/dbs-code"))
        from dbs.engine import separate
        from dbs.models import DBSTIGER
        path = DBS
        directory.mkdir(parents=True, exist_ok=True)
        mix = directory / ("mix-" + uuid4().hex + ".wav")
        ff("-i", source, "-map", "0:a:0", "-ar", RATE, "-ac", 2, "-c:a", "pcm_f32le", mix)
        x, _ = sf.read(mix, dtype="float32", always_2d=True)
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = DBSTIGER.from_pretrained(str(path), local_files_only=True).eval().to(dev)
        # Preserve true stereo. Dual-mono sources need only one model pass.
        same = np.max(np.abs(x[:, 0] - x[:, 1])) < .001
        music, speech = [], []
        for channel in range(1 if same else 2):
            native = resample_poly(x[:,channel], 147, 160)
            batch = torch.from_numpy(native).view(1,1,-1).to(dev)
            with torch.inference_mode():
                result = separate(model, batch, {"mode":"chunked","chunk_seconds":6.0,"hop_seconds":3.0}, sample_rate=44100)[0].cpu().numpy()
            for target, idx in [(music,0),(speech,2)]:
                target.append(resample_poly(result[idx].reshape(-1),160,147)[:len(x)])
        clean = x - np.stack(music,axis=1)
        sf.write(directory/"clean.wav",clean,RATE,subtype="FLOAT")
        sf.write(directory/"speech.wav",np.stack(speech,axis=1),RATE,subtype="FLOAT")
        (directory/"ready").touch()


def convert_voice(speech, reference, work):
    work.mkdir(parents=True)
    src = work / "speech.wav"
    sf.write(src,speech,RATE,subtype="FLOAT")
    from paths import SETTINGS,HERE
    if SETTINGS.get("seed_models"):
        sys.path.insert(0,str(HERE.parent/"optional/seed-engine"))
        from engine import SeedVoice,PRESETS,RATE as sr
        rr,rrate=sf.read(reference,dtype="float32",always_2d=True)
        from math import gcd
        g=gcd(rrate,sr)
        ref=resample_poly(rr.mean(1),sr//g,rrate//g)
        x=resample_poly(speech.mean(1),147,320).astype("float32")
        progress=lambda *args: None
        model=SeedVoice(Path(SETTINGS["seed_models"]),progress)
        v=model.convert(x,ref,PRESETS["quality"],progress)
        if not 0<=len(x)-len(v)<256:raise ReviewError("笑声音色转换时长不匹配。")
        data=np.pad(v,(0,len(x)-len(v)))[:,None]
    else:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PATH=str(BUNDLE/"runtime")+os.pathsep+os.environ["PATH"])
        result = subprocess.run([str(BUNDLE/"runtime/python.exe"),"-I","-S","-B","-u",str(BUNDLE/"app/worker.py"),
            "convert","--source",str(src),"--reference",str(reference),"--output-dir",str(work),"--preset","quality"],
            env=env,capture_output=True,encoding="utf8",errors="replace")
        events = [json.loads(line[8:]) for line in result.stdout.splitlines() if line.startswith("@seedvc ")]
        if result.returncode or not events or events[-1].get("event") != "done":
            raise ReviewError(events[-1].get("message","本地换声未完成。") if events else "本地换声工具启动失败。")
        data,sr=sf.read(events[-1]["output"],dtype="float32",always_2d=True)
    from math import gcd
    g=gcd(sr,RATE)
    wave=resample_poly(data.mean(1),RATE//g,sr//g)
    n=len(speech)
    if abs(len(wave)-n)>RATE*.05:
        raise ReviewError("换声前后时长不匹配。")
    wave=np.pad(wave[:n],(0,max(0,n-len(wave))))
    original=speech.mean(1)
    # Match local dialogue level, suppress synthesized sounds during speech pauses.
    pos=np.arange(0,n,960)
    def rms(a):
        return np.sqrt(np.add.reduceat(a.astype("float64")**2,pos)/np.minimum(960,n-pos))
    levels=rms(original)
    gain=np.clip(levels/(rms(wave)+.0001),0,3)
    gain[levels<.0008]=0
    return wave*np.interp(np.arange(n),pos+480,gain)


def process(studio, pid, data):
    project=studio.load(pid)
    kind, item, mode = (data.get(k) for k in ("kind","id","mode"))
    if not isinstance(item,str) or not re.fullmatch("[0-9a-f]{16}",item) or mode not in ("clean","sample","voice"):
        raise ReviewError("音频请求有误。")
    tmp=studio.temp/pid/"audio"
    tmp.mkdir(parents=True,exist_ok=True)
    output=None
    if kind=="take":
        if project.get("dub_ref") and mode=="clean":
            from dialogue_dub import prepare
            for part in project["segments"]:
                for t in part["takes"]:
                    if t["id"]==item:
                        dubbed=Path(prepare(studio,pid,part,t,project["dub_ref"]))
                        return {"url":f"/api/projects/{pid}/dub-files/{dubbed.parent.name}","id":item}
        source=next((Path(t["path"]) for p in project["segments"] for t in p["takes"] if t["id"]==item),None)
    elif kind=="seam":
        source=studio.temp/pid/f"接缝-{item}.mp4"
    elif kind=="output":
        output=next((o for o in project["outputs"] if o["id"]==item),None)
        source=Path(output["output"]) if output else None
    else:
        source=None
    if not source or not source.is_file() or (mode!="clean" and not output):
        raise ReviewError("请先选择可用的成片或片段。")
    with GPU:
        stems=tmp/key("stems",item)
        ref=data.get("ref","")
        start=float(data.get("start",0))
        if not np.isfinite(start) or start<0:
            raise ReviewError("试听起点无效。")
        if mode!="clean" and (not isinstance(ref,str) or not re.fullmatch("[a-f0-9]{16}",ref) or not (tmp/f"ref-{ref}.wav").is_file()):
            raise ReviewError("请先选择参考音频。")
        ident=key(item,mode,ref if mode!="clean" else "",start if mode=="sample" else 0)
        preview=tmp/(ident+".mp4")
        base=studio.outputs/pid if output and mode!="sample" else tmp
        dest=base/(ident+".mp4")
        if mode=="voice" and not (tmp/(key(item,"sample",ref,start)+".mp4")).exists():
            raise ReviewError("请先试听该参考音色。")
        if not dest.exists():
            split(source,stems)
            work=tmp/uuid4().hex
            work.mkdir()
            audio=stems/"clean.wav"
            offset=[]
            if mode!="clean":
                clean,_=sf.read(audio,dtype="float32",always_2d=True)
                speech,_=sf.read(stems/"speech.wav",dtype="float32",always_2d=True)
                a=round(start*RATE) if mode=="sample" else 0
                b=min(len(clean),a+5*RATE) if mode=="sample" else len(clean)
                if b-a<RATE:
                    raise ReviewError("试听起点太靠近片尾。")
                clean,speech=clean[a:b],speech[a:b]
                if np.max(np.abs(speech)) < .008:
                    raise ReviewError("所选范围人声太轻，请改选有对白的位置。")
                voice=convert_voice(speech,tmp/f"ref-{ref}.wav",work/"vc")
                mixed=clean-speech+voice[:,None]
                audio=work/"remix.wav"
                sf.write(audio,mixed/max(1.,np.abs(mixed).max()/.96),RATE,subtype="FLOAT")
                if mode=="sample":
                    offset=["-ss",str(start)]
            staged=work/"finished.mp4"
            ff(*offset,"-i",source,"-i",audio,"-map","0:v:0","-map","1:a:0",
               "-c:v","libx264" if mode=="sample" else "copy","-c:a","aac","-b:a","256k",
               *(["-t",str((b-a)/RATE)] if mode=="sample" else []),"-movflags","+faststart",staged)
            os.replace(staged,dest)
        if output and mode!="sample":
            with studio.lock:
                p=studio.load(pid)
                if not any(o["id"]==ident for o in p["outputs"]):
                    p["outputs"].append({**output,"id":ident,"output":str(dest),"audio_label":"去配乐" if mode=="clean" else "换音色 · 去配乐","audio_base":item})
                    studio.save(p)
            return {"url":f"/api/projects/{pid}/outputs/{ident}","id":ident}
        return {"url":f"/api/projects/{pid}/audio-files/{ident}","id":ident}


def upload_reference(studio,pid,body):
    studio.load(pid)
    tmp=studio.temp/pid/"audio"
    tmp.mkdir(parents=True,exist_ok=True)
    ref=hashlib.sha256(body).hexdigest()[:16]
    dest=tmp/f"ref-{ref}.wav"
    if not dest.exists():
        folder=tmp/uuid4().hex
        folder.mkdir()
        src=folder/"reference"
        src.write_bytes(body)
        staged=folder/"reference.wav"
        try:
            ff("-protocol_whitelist","file,pipe","-format_whitelist","wav,mp3","-i",src,"-map","0:a:0","-t",25,"-ac",1,"-ar",24000,staged)
        except subprocess.CalledProcessError as exc:
            raise ReviewError("请选可解码的 WAV 或 MP3 参考人声。") from exc
        os.replace(staged,dest)
    return {"ref":ref}

