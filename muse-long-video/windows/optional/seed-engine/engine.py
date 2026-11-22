"""Local Seed-VC V1 speech inference, based on Plachtaa/seed-vc (GPL-3.0)."""

import math

import numpy as np
import torch
import torchaudio
import yaml
from safetensors.torch import load_file
from transformers import WhisperConfig, WhisperFeatureExtractor
from transformers.models.whisper.modeling_whisper import WhisperEncoder

from modules.audio import mel_spectrogram
from modules.bigvgan.bigvgan import BigVGAN, load_hparams_from_json
from modules.campplus.DTDNN import CAMPPlus
from modules.commons import build_model, recursive_munch

RATE = 22050
HOP = 256
OVERLAP_FRAMES = 16
PRESETS = {"quality": 50, "fast": 20}


class SeedVoice:
    def __init__(self, models, progress):
        torch.set_num_threads(4)
        torch.manual_seed(4109)
        self.device = torch.device("cuda")
        progress(14, "加载变声模型")
        seed = models / "seed"
        config = yaml.safe_load((seed / "config_dit_mel_seed_uvit_whisper_small_wavenet.yml").read_text("utf-8"))
        self.model = build_model(recursive_munch(config["model_params"]))
        checkpoint = torch.load(
            seed / "DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth",
            map_location="cpu", weights_only=True,
        )["net"]
        for key, module in self.model.items():
            state = {name.removeprefix("module."): value for name, value in checkpoint[key].items()}
            if key == "cfm":
                # The speech checkpoint predates the larger position buffer and stores an unused F0 embedding.
                state.pop("estimator.input_pos")
                state.pop("estimator.f0_embedder.weight")
                missing, unexpected = module.load_state_dict(state, strict=False)
                generated_buffers = {"estimator.input_pos", "estimator.t_embedder.freqs", "estimator.t_embedder2.freqs"}
                if set(missing) != generated_buffers or unexpected:
                    raise RuntimeError(f"Unexpected Seed-VC checkpoint keys: {missing}, {unexpected}")
            else:
                module.load_state_dict(state, strict=True)
            module.eval().to(self.device)
        del checkpoint, state
        self.model.cfm.estimator.setup_caches(max_batch_size=1, max_seq_length=8192)

        progress(21, "加载语音编码器")
        whisper = models / "whisper"
        whisper_config = WhisperConfig.from_json_file(str(whisper / "config.json"))
        self.encoder = WhisperEncoder(whisper_config).half()
        self.encoder.load_state_dict(load_file(str(whisper / "encoder.fp16.safetensors")), strict=True)
        self.encoder.eval().to(self.device)
        self.features = WhisperFeatureExtractor.from_pretrained(str(whisper), local_files_only=True)
        self.speaker = CAMPPlus(feat_dim=80, embedding_size=192)
        self.speaker.load_state_dict(torch.load(
            seed / "campplus_cn_common.bin", map_location="cpu", weights_only=True
        ))
        self.speaker.eval().to(self.device)

        progress(27, "加载音频合成模型")
        vocoder = models / "bigvgan"
        self.vocoder = BigVGAN(load_hparams_from_json(vocoder / "config.json"), use_cuda_kernel=False)
        self.vocoder.load_state_dict(torch.load(
            vocoder / "bigvgan_generator.pt", map_location="cpu", weights_only=True
        )["generator"], strict=True)
        self.vocoder.remove_weight_norm()
        self.vocoder.eval().to(self.device)

    def semantic_features(self, waveform):
        waveform = waveform.squeeze(0).cpu().numpy()
        window = 30 * 16000
        stride = 25 * 16000
        overlap = window - stride
        features = []
        for offset in range(0, len(waveform), stride):
            chunk = waveform[offset:offset + window]
            data = self.features([chunk], sampling_rate=16000, return_tensors="pt")
            encoded = self.encoder(data.input_features.to(self.device, dtype=torch.float16))
            skip = overlap // 320 if offset else 0
            features.append(encoded.last_hidden_state[:, skip:len(chunk) // 320 + 1].float())
            if offset + window >= len(waveform):
                break
        return torch.cat(features, dim=1)

    @staticmethod
    def mel(waveform):
        return mel_spectrogram(waveform, 1024, 80, RATE, HOP, 1024, 0, None, center=False)

    @torch.inference_mode()
    def convert(self, source, reference, steps, progress):
        progress(32, "提取源语音节奏和参考音色")
        source = torch.from_numpy(source.copy()).unsqueeze(0).to(self.device)
        reference = torch.from_numpy(reference.copy()).unsqueeze(0).to(self.device)
        source_16k = torchaudio.functional.resample(source, RATE, 16000)
        ref_16k = torchaudio.functional.resample(reference, RATE, 16000)
        src_features = self.semantic_features(source_16k)
        ref_features = self.semantic_features(ref_16k)
        prompt = self.mel(reference)
        frame_count = source.shape[-1] // HOP
        ref_frames = prompt.size(-1)
        fbank = torchaudio.compliance.kaldi.fbank(
            ref_16k, num_mel_bins=80, dither=0, sample_frequency=16000
        )
        style = self.speaker((fbank - fbank.mean(dim=0, keepdim=True)).unsqueeze(0))
        regulator = self.model.length_regulator
        condition = regulator(src_features, ylens=torch.tensor([frame_count], device=self.device), n_quantizers=3)[0]
        ref_condition = regulator(ref_features, ylens=torch.tensor([ref_frames], device=self.device), n_quantizers=3)[0]

        window = RATE // HOP * 30 - ref_frames
        stride = window - OVERLAP_FRAMES
        overlap = OVERLAP_FRAMES * HOP
        windows = 1 + max(0, math.ceil((frame_count - window) / stride))
        fade = np.sin(np.linspace(0, np.pi / 2, overlap, dtype=np.float32)) ** 2
        wave = np.empty(frame_count * HOP, dtype=np.float32)
        for chunk in range(windows):
            offset = chunk * stride
            cond = torch.cat([ref_condition, condition[:, offset:offset + window]], dim=1)

            def update(step):
                if step == 1 or step == steps or step % 5 == 0:
                    ratio = (chunk * steps + step) / (windows * steps)
                    progress(36 + int(44 * ratio), f"转换第 {chunk + 1}/{windows} 段 · 第 {step}/{steps} 步")

            with torch.autocast("cuda", dtype=torch.float16):
                target = self.model.cfm.inference(
                    cond, torch.tensor([cond.size(1)], device=self.device), prompt, style, None, steps,
                    inference_cfg_rate=1.0, progress=update,
                )[:, :, ref_frames:]
            values = self.vocoder(target.float()).flatten().cpu().numpy()
            start = offset * HOP
            if chunk:
                values[:overlap] = values[:overlap] * fade + wave[start:start + overlap] * (1 - fade)
            wave[start:start + len(values)] = values
        return wave
