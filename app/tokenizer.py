"""Audio -> YuE2 semantic tokens using Mothersuperior Realaudio Tokenizer v4.

Uses MERT-v2-FullSong (layer 20, 25 Hz) with rotary embedding fix +
tokenizer_head_joint_v9.safetensors (8-layer TransformerEncoder, 32768 vocab).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

# Constants matching Mothersuperior v4 specification
VOCAB = 32768
WIN = 512
D = 512
L = 8
H = 8
SAMPLE_RATE = 24000
TOKEN_RATE_HZ = 25


def load_audio(filepath: str | Path, target_sr: int = SAMPLE_RATE):
    """Loads audio as float32 mono array at target_sr using PyAV or torchaudio."""
    import numpy as np

    path_str = str(filepath)
    try:
        import av

        container = av.open(path_str)
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=target_sr)
        chunks = []
        for frame in container.decode(audio=0):
            for r in resampler.resample(frame):
                chunks.append(r.to_ndarray()[0])
        for r in resampler.resample(None):
            chunks.append(r.to_ndarray()[0])
        if chunks:
            return np.concatenate(chunks), target_sr
    except Exception:
        pass

    import torchaudio

    wav, sr = torchaudio.load(path_str)
    if wav.dim() == 2:
        wav = wav.mean(0)
    if sr != target_sr:
        wav = torchaudio.functional.resample(wav.float(), sr, target_sr)
    return wav.float().numpy(), target_sr


def build_tok_model(din: int = 1024):
    """Instantiates the 8-layer TransformerEncoder tokenizer head."""
    import torch
    import torch.nn as nn

    class Tok(nn.Module):
        def __init__(self, din_dim=din):
            super().__init__()
            self.inp = nn.Linear(din_dim, D)
            self.pos = nn.Parameter(torch.zeros(1, WIN, D))
            layer = nn.TransformerEncoderLayer(
                D, H, 4 * D, dropout=0.1, batch_first=True, norm_first=True, activation="gelu"
            )
            self.enc = nn.TransformerEncoder(layer, L)
            self.norm = nn.LayerNorm(D)
            self.head = nn.Linear(D, VOCAB)

        def forward(self, x):
            # x: [batch, time, din]
            return self.head(self.norm(self.enc(self.inp(x) + self.pos[:, : x.shape[1]])))

    return Tok(din)


def rebuild_rotary(model: Any) -> int:
    """Fixes MERT2 rotary embedding inv_freq buffers when loaded in modern transformers.

    MERT2's RotaryEmbedding keeps inv_freq as a non-persistent buffer; newer
    transformers load through a meta device leaving it uninitialized (near-zero garbage),
    which degrades token matching to ~37%. Recomputing inv_freq restores 100% fidelity.
    """
    import torch

    rebuilt = 0
    for m in model.modules():
        if hasattr(m, "inv_freq") and hasattr(m, "head_dim") and hasattr(m, "base"):
            inv = 1.0 / (m.base ** (torch.arange(0, m.head_dim, 2, dtype=torch.float32) / m.head_dim))
            m.inv_freq = inv.to(device=m.inv_freq.device)
            for attr, val in (("_cos", None), ("_sin", None), ("_sequence_length", 0), ("_cache_device", None)):
                if hasattr(m, attr):
                    setattr(m, attr, val)
            rebuilt += 1
    return rebuilt


class AudioTokenizer:
    """Tokenizes raw audio waveforms into YuE2 semantic token sequences at 25 Hz."""

    def __init__(
        self,
        head_path: str | Path,
        cache_dir: str | Path | None = None,
        device: str = "cuda",
    ) -> None:
        import torch
        from safetensors.torch import load_file
        from transformers import AutoFeatureExtractor, AutoModel

        self.device = device if torch.cuda.is_available() and device == "cuda" else "cpu"
        self.cache_dir = str(cache_dir) if cache_dir else None

        self.proc = AutoFeatureExtractor.from_pretrained(
            "m-a-p/MERT-v2-FullSong", trust_remote_code=True, cache_dir=self.cache_dir
        )
        self.mert = AutoModel.from_pretrained(
            "m-a-p/MERT-v2-FullSong", trust_remote_code=True, cache_dir=self.cache_dir
        ).to(self.device).eval()
        rebuild_rotary(self.mert)

        self.head = build_tok_model().to(self.device).eval()
        sd = load_file(str(head_path))
        if isinstance(sd, dict) and "model" in sd:
            sd = sd["model"]
        self.head.load_state_dict(sd)

    def extract_features(self, wav: Any, sr: int = SAMPLE_RATE):
        """Extracts 25 Hz layer-20 MERT features interpolated across time."""
        import numpy as np
        import torch
        import torch.nn.functional as F
        import torchaudio

        if isinstance(wav, (str, Path)):
            wav_24k, _ = load_audio(wav, target_sr=SAMPLE_RATE)
        else:
            if not isinstance(wav, torch.Tensor):
                wav = torch.tensor(wav, dtype=torch.float32)

            if wav.dim() == 2:
                wav_mono = wav.mean(0)
            else:
                wav_mono = wav

            if sr != SAMPLE_RATE:
                wav_24k = torchaudio.functional.resample(wav_mono.float(), sr, SAMPLE_RATE).numpy()
            else:
                wav_24k = wav_mono.float().numpy()

        chunk_size = SAMPLE_RATE * 30  # 30-second windows
        chunks = [wav_24k[s : s + chunk_size] for s in range(0, len(wav_24k), chunk_size)]
        chunks = [c for c in chunks if len(c) >= SAMPLE_RATE]
        if not chunks:
            chunks = [wav_24k]

        full_chunks = [c for c in chunks if len(c) == chunk_size]
        tail_chunks = [c for c in chunks if len(c) < chunk_size]

        feats = []
        amp_ctx = (
            torch.autocast(self.device, dtype=torch.bfloat16)
            if self.device == "cuda"
            else torch.no_grad()
        )
        with torch.no_grad():
            with amp_ctx:
                for group in ([full_chunks] if full_chunks else []) + [[c] for c in tail_chunks]:
                    inp = {
                        k: v.to(self.device)
                        for k, v in self.proc(group, sampling_rate=SAMPLE_RATE, return_tensors="pt").items()
                    }
                    out = self.mert(**inp, output_hidden_states=True)
                    feats.append(out.hidden_states[20].reshape(-1, 1024))

        hh = torch.cat(feats, 0).float()
        t25 = int(round(len(wav_24k) / SAMPLE_RATE * TOKEN_RATE_HZ))
        interpolated = F.interpolate(hh.T[None], size=t25, mode="linear", align_corners=False)[0].T
        return interpolated.cpu().numpy()

    def tokenize(self, wav: Any, sr: int = SAMPLE_RATE) -> Sequence[int]:
        """Runs full tokenization: features -> instance norm -> sliding window Tok head -> 25 Hz tokens."""
        import numpy as np
        import torch

        features = self.extract_features(wav, sr)
        # Per-track instance norm
        normed = (features - features.mean(0)) / (features.std(0) + 1e-5)
        total_len = len(normed)
        out = np.zeros(total_len, dtype=np.int64)

        starts = list(range(0, max(1, total_len - WIN + 1), WIN // 2))
        if starts[-1] + WIN < total_len:
            starts.append(max(0, total_len - WIN))

        amp_ctx = (
            torch.autocast(self.device, dtype=torch.bfloat16)
            if self.device == "cuda"
            else torch.no_grad()
        )
        with torch.no_grad():
            for s0 in starts:
                window = normed[s0 : s0 + WIN]
                n = len(window)
                if n < WIN:
                    window = np.pad(window, ((0, WIN - n), (0, 0)))
                inp_t = torch.tensor(window[None], dtype=torch.float32, device=self.device)
                with amp_ctx:
                    pred = self.head(inp_t)[0, :n].float().argmax(-1).cpu().numpy()
                lo = s0 + (0 if s0 == 0 else WIN // 4)
                hi = s0 + n - (0 if s0 + n >= total_len else WIN // 4)
                out[lo:hi] = pred[lo - s0 : hi - s0]

        return out.astype(np.int32)
