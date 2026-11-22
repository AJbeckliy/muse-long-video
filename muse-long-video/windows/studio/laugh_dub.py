"""Replace detected nonverbal laughter without shifting scene cues or dubbed lines."""
from pathlib import Path
import re
import numpy as np
from scipy import signal, ndimage
from audio_post import CACHE, RATE, convert_voice

def replace_laughs(original,speech,dub,reference,work,dialogue,asr):
    import onnxruntime as ort
    directory=CACHE/"MuseAudio/yamnet"
    detector=ort.InferenceSession(str(directory/"yamnet.onnx"),providers=["CPUExecutionProvider"])
    def scores(x):
        return detector.run(["output_0"],{"waveform":signal.resample_poly(x.mean(1),1,3).astype("float32")})[0]
    y=scores(original)
    ys=scores(speech)
    hits=[]
    for i,score in enumerate(np.maximum(y[:,13:19].max(1),ys[:,13:19].max(1))):
        if score>=.07:
            hits.append((i*.48,i*.48+.96))
    words=asr.transcribe(signal.resample_poly(original.mean(1),1,3),language="zh",fp16=False,
                         temperature=0,word_timestamps=True,condition_on_previous_text=False)
    for seg in words["segments"]:
        for w in seg["words"]:
            if re.fullmatch(r"[哈呵嘿]{2,}[，。！？!?,.]*",w["word"].strip()) and w["end"]>w["start"]:
                hits.append((w["start"],w["end"]))
    mask=np.zeros(len(original),dtype=bool)
    for start,end in hits:
        mask[max(0,round(start*RATE)):min(len(mask),round(end*RATE))]=True
    for line in dialogue:
        mask[max(0,line["start_sample"]-960):line["end_sample"]+960]=False
    # Nonverbal voice may leak into the effects stem. Keep sharp impacts in the
    # scene bed, recovering sustained voiced components only inside the windows.
    mono=speech.mean(1)
    residual=original.mean(1)-mono
    _,_,z=signal.stft(residual,fs=RATE,nperseg=1024,noverlap=768)
    amp=np.abs(z)
    h=ndimage.median_filter(amp,size=(1,11))
    per=ndimage.median_filter(amp,size=(15,1))
    _,harm=signal.istft(z*h**2/(h**2+1.7*per**2+1e-12),fs=RATE,nperseg=1024,noverlap=768)
    voice=mono+harm[:len(mono)]
    energy=np.sqrt(np.maximum(0,ndimage.uniform_filter1d(voice.astype("float64")**2,1440)))
    mask &= energy>.0018
    edges=np.flatnonzero(np.diff(mask.astype(int),prepend=0,append=0)).reshape(-1,2)
    intervals=[(int(a),int(b)) for a,b in edges if b-a>RATE*.09]
    if not intervals:return dub,[]
    weight=np.zeros(len(mono))
    for a,b in intervals:
        weight[a:b]=1
        n=min(480,(b-a)//2)
        weight[a:a+n]=np.linspace(0,1,n)
        weight[b-n:b]=np.linspace(1,0,n)
    # Give the converter the source performance in context, then use only
    # confirmed laugh windows. This preserves individual laugh pulses.
    converted=convert_voice(voice[:,None],reference,work/"laugh-vc")
    fixed=dub+((converted-voice)*weight)[:,None]
    return fixed,[dict(start_sample=a,end_sample=b) for a,b in intervals]
