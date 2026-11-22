"""Re-synthesize each spoken line and align it on the source take before cutting."""
from pathlib import Path
import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from uuid import uuid4
import numpy as np
import soundfile as sf
from scipy import signal
from paths import WHISPER
from audio_post import GPU, RATE, ff, key, split
from studio import ReviewError, write_json

def letters(t):
    return re.sub(r"[^\w]", "", t)

def voiced_edges(x,rate):
    hop=max(1,rate//100)
    power=np.sqrt(np.mean(np.pad(x,(0,(-len(x))%hop)).reshape(-1,hop)**2,axis=1))
    hot=np.flatnonzero(power>max(.0008,np.percentile(power,95)*.04))
    if not len(hot):
        raise ReviewError("台词时间段中没有可定位的人声。")
    return int(max(0,(hot[0]-2)*hop)),int(min(len(x),(hot[-1]+3)*hop))

def recognise(model,speech,prompt):
    # Nonverbal pauses and laughs stay in the original scene mix.
    quotes=[q for q in re.findall('“([^”]+)”',prompt) if len(letters(q))>=5]
    if not quotes and any(s in prompt for s in ("没有对白","无对白","没有台词")):
        return []
    wave=signal.resample_poly(speech,1,3)
    result=model.transcribe(wave,language="zh",fp16=False,temperature=0,word_timestamps=True,condition_on_previous_text=False)
    spans=[s for s in result["segments"] if len(letters(s["text"]).strip("哈哈嘿嗯啊"))>=2 and s["end"]>s["start"]]
    if not quotes:
        return [dict(text=s["text"].strip(),start=s["start"],end=s["end"]) for s in spans]
    chars=[]
    for s in spans:
        for w in s["words"]:
            word=letters(w["word"])
            for i,ch in enumerate(word):
                dur=(w["end"]-w["start"])/len(word)
                chars.append((ch,w["start"]+i*dur,w["start"]+(i+1)*dur))
    transcript="".join(c[0] for c in chars)
    lines=[]
    offset=0
    for q in quotes:
        expected=letters(q)
        blocks=SequenceMatcher(None,expected,transcript[offset:],autojunk=False).get_matching_blocks()[:-1]
        if not blocks or sum(b.size for b in blocks)<len(expected)*.55:
            raise ReviewError("实际对白与提示词匹配不足，请核对本段后重新配音。")
        a=max(offset,offset+blocks[0].b-blocks[0].a)
        last=blocks[-1]
        b=min(len(chars),offset+last.b+len(expected)-last.a)
        lines.append(dict(text=q,start=chars[a][1],end=chars[b-1][2]))
        offset=b
    return lines

def anchors(model,tokenizer,wave,text):
    import torch,whisper
    from whisper.timing import find_alignment
    a=signal.resample_poly(wave,2,3).astype("float32")
    mel=whisper.log_mel_spectrogram(torch.from_numpy(a))
    words=find_alignment(model,tokenizer,tokenizer.encode(letters(text)),whisper.pad_or_trim(mel,3000),mel.shape[-1])
    return [float(w.start) for w in words[1:]]

def fit(x,src,dst):
    rate=24000
    hop=384
    radius=160
    pad=2048
    padded=np.pad(x,(pad,pad))
    n=int(dst[-1])
    total=np.zeros(n+4*hop)
    weights=np.zeros_like(total)
    window=np.hanning(2*hop)
    for i in range(-hop,n,hop):
        expected=pad+int(np.interp(i+hop,dst,src))-hop
        k=i+2*hop
        start=expected
        if i>=0:
            prev=total[k:k+hop]/np.maximum(weights[k:k+hop],1e-7)
            sample=padded[expected-radius:expected+radius+hop]
            score=signal.correlate(sample,prev,mode="valid")/np.sqrt(np.maximum(np.convolve(sample**2,np.ones(hop),"valid"),1e-9))
            start+=int(np.argmax(score))-radius
        total[k:k+2*hop]+=window*padded[start:start+2*hop]
        weights[k:k+2*hop]+=window
    out=total[2*hop:2*hop+n]/np.maximum(weights[2*hop:2*hop+n],1e-7)
    fade=min(160,n//2)
    if fade:
        out[:fade]*=np.linspace(0,1,fade)
        out[-fade:]*=np.linspace(1,0,fade)
    return out

def prepare(studio,pid,part,take,ref):
    import torch,whisper
    tmp=studio.temp/pid/"audio"
    reference=tmp/f"ref-{ref}.wav"
    if not re.fullmatch("[a-f0-9]{16}",ref) or not reference.is_file():
        raise ReviewError("请上传参考音频。")
    identity=key("qwen-dub-laugh-v1",take["id"],ref,part["prompt"])
    dest=studio.projects/pid/"对白轨"/identity
    final=dest/"配音版.mp4"
    with GPU:
        if final.is_file(): return str(final)
        dest.mkdir(parents=True,exist_ok=True)
        work=dest/uuid4().hex
        work.mkdir()
        stems=tmp/key("stems",take["id"])
        split(Path(take["path"]),stems)
        clean,_=sf.read(stems/"clean.wav",dtype="float32",always_2d=True)
        speech,_=sf.read(stems/"speech.wav",dtype="float32",always_2d=True)
        mono=speech.mean(1)
        torch.set_num_threads(4)
        model=whisper.load_model(str(WHISPER),device="cpu")
        lines=recognise(model,mono,part["prompt"])
        write_json(work/"lines.json",lines)
        cache=tmp/"qwen-lines"
        cache.mkdir(exist_ok=True)
        cached=[cache/(key(ref,line["text"],"qwen-base-61473")+".wav") for line in lines]
        if any(not path.is_file() for path in cached):
            with (work/"生成.log").open("wb") as log:
                subprocess.run([sys.executable,"-B",str(Path(__file__).with_name("dub_synth.py")),str(work),str(reference)],stdout=log,stderr=log,check=True)
            for i,path in enumerate(cached):
                (work/f"line-{i}.wav").replace(path)
        tok=whisper.tokenizer.get_tokenizer(True,language="zh",task="transcribe")
        report=[]
        for i,line in enumerate(lines):
            lo=max(0,round((line["start"]-.10)*RATE))
            hi=min(len(mono),round((line["end"]+.10)*RATE))
            if i: lo=max(lo,report[-1]["end_sample"])
            if hi<=lo: raise ReviewError("台词时间窗口重叠。")
            u,v=voiced_edges(mono[lo:hi],RATE)
            end=lo+v
            begin=lo+u
            orig=signal.resample_poly(mono[begin:end],1,2)
            generated,sr=sf.read(cached[i],dtype="float32")
            assert sr==24000
            l,r=voiced_edges(generated,sr)
            x=generated[l:r]
            # Endpoints carry the original opening/closing times. Interior word
            # anchors align the tempo locally, including pauses within a line.
            src,dst=[0],[0]
            target_times=anchors(model,tok,orig,line["text"])
            for s,t in zip(anchors(model,tok,x,line["text"]),target_times):
                p,q=round(s*sr),round(t*sr)
                if src[-1]+1200<p<len(x)-1200 and dst[-1]+1200<q<len(orig)-1200:
                    src.append(p);dst.append(q)
            src.append(len(x));dst.append(len(orig))
            fitted=fit(x,src,dst).astype("float32")
            bed=signal.resample_poly((clean[begin:end]-speech[begin:end]).mean(1),1,2)
            def measure(voice):
                level=np.sqrt(np.mean(orig**2)/max(np.mean(voice**2),1e-12))
                actual=anchors(model,tok,(voice*level+bed).astype("float32"),line["text"])
                error=max((abs(a-b) for a,b in zip(actual,target_times)),default=0.)
                return actual,error
            measured,error=measure(fitted)
            for _ in range(3):
                if error<.07: break
                before,after=[0],[0]
                for actual,wanted in zip(measured,target_times):
                    a,b=round(actual*sr),round(wanted*sr)
                    if before[-1]+480<a<len(fitted)-480 and after[-1]+480<b<len(orig)-480:
                        before.append(a);after.append(b)
                candidate=fit(fitted,before+[len(fitted)],after+[len(orig)]).astype("float32")
                updated,new_error=measure(candidate)
                if new_error>=error: break
                fitted,measured,error=candidate,updated,new_error
            y=signal.resample_poly(fitted,2,1)[:end-begin]
            gain=min(np.sqrt(np.mean(orig**2)/max(np.mean(y**2),1e-12)),.95/max(np.max(np.abs(y)),.01))
            clean[begin:end]+=y[:,None]*gain-speech[begin:end]
            report.append(dict(text=line["text"],start_sample=begin,end_sample=end,max_word_error_ms=round(error*1000),anchors_sec=[round((begin/RATE+t/sr),3) for t in dst]))
        from laugh_dub import replace_laughs
        original,_=sf.read(stems/"clean.wav",dtype="float32",always_2d=True)
        clean,laughs=replace_laughs(original,speech,clean,reference,work,report,model)
        audio=dest/"对齐对白与现场声.wav"
        sf.write(audio,clean/max(1.,np.max(np.abs(clean))/.98),RATE,subtype="FLOAT")
        write_json(dest/"对齐记录.json",dict(rate=RATE,source=take["id"],ref=ref,lines=report,laughs=laughs))
        staged=work/"render.mp4"
        ff("-i",take["path"],"-i",audio,"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","256k",staged)
        staged.replace(final)
        return str(final)
