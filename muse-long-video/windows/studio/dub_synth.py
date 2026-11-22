"""Generate new dialogue with the local Qwen voice-cloning model."""
import json
import os
import sys
from pathlib import Path
from paths import QWEN, QWEN_LIB
import numpy as np
import soundfile as sf
import torch


def main():
    sys.path.insert(0,os.environ.get("MUSE_QWEN_LIB",str(QWEN_LIB)))
    from qwen_tts import Qwen3TTSModel
    folder, reference = map(Path,sys.argv[1:])
    model=Qwen3TTSModel.from_pretrained(os.environ.get("MUSE_QWEN_MODEL",str(QWEN)),device_map="cuda:0",dtype=torch.bfloat16,attn_implementation="sdpa",local_files_only=True)
    prompt=model.create_voice_clone_prompt(ref_audio=str(reference),x_vector_only_mode=True)
    torch.manual_seed(61473)
    with torch.inference_mode():
        for i,line in enumerate(json.loads((folder/"lines.json").read_text(encoding="utf8"))):
            audio,sr=model.generate_voice_clone(text=line["text"],language="Chinese",voice_clone_prompt=prompt,do_sample=False,subtalker_dosample=False,max_new_tokens=max(150,len(line["text"])*14))
            wave=np.ravel(audio[0]).astype("float32")
            if not np.isfinite(wave).all() or len(wave)<sr*.15:
                raise ValueError("无有效配音")
            sf.write(folder/f"line-{i}.wav",wave,sr,subtype="FLOAT")

if __name__=="__main__":
    main()
