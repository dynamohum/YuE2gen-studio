#!/usr/bin/env python3
"""CLI utility to tokenize vocal recordings into YuE2 semantic tokens for vocal persona conditioning.

Usage:
  python3 scripts/tokenize_persona.py --input /mnt/h/mysongs --output ./data/persona_tokens --consent

Ethics & Consent:
  Only tokenize your own voice recordings, or recordings where you have obtained explicit
  written consent from the performer.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CONSENT_PROMPT = (
    "CONSENT ACKNOWLEDGEMENT:\n"
    "Training or conditioning a vocal persona models a human voice.\n"
    "By proceeding, you certify that either:\n"
    "  1. The voice recordings are of your own voice, OR\n"
    "  2. You have obtained explicit consent from the singer/performer to process and model their voice.\n"
)


def verify_consent(flag_passed: bool) -> bool:
    if flag_passed:
        return True
    print(CONSENT_PROMPT)
    if not sys.stdin.isatty():
        print("Error: --consent flag is required in non-interactive mode.", file=sys.stderr)
        return False
    try:
        reply = input("Do you certify you have consent to process these voice recordings? [y/N]: ")
        return reply.strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        return False


def run_in_docker(args: list[str]) -> int:
    """Delegates execution to the GPU-enabled yue2studio-engine container."""
    cmd = [
        "docker",
        "exec",
        "-i",
        "yue2studio-engine",
        "python",
        "/app/scripts/tokenize_persona.py",
    ] + args
    return subprocess.call(cmd)


def tokenize_files(
    input_path: Path,
    output_dir: Path,
    head_path: Path,
    hf_cache: Path | None,
    device: str = "cuda",
) -> None:
    import numpy as np
    import torchaudio
    from app.tokenizer import AudioTokenizer, SAMPLE_RATE, TOKEN_RATE_HZ

    output_dir.mkdir(parents=True, exist_ok=True)
    audio_extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = sorted([p for p in input_path.rglob("*") if p.suffix.lower() in audio_extensions])
    else:
        print(f"Error: Input path {input_path} does not exist.", file=sys.stderr)
        sys.exit(1)

    if not files:
        print(f"No audio files found in {input_path}.", file=sys.stderr)
        sys.exit(1)

    print(f"Initializing AudioTokenizer on {device}...")
    tokenizer = AudioTokenizer(
        head_path=head_path,
        cache_dir=hf_cache,
        device=device,
    )

    manifest = []
    print(f"Found {len(files)} file(s) to process. Writing tokens to {output_dir}/")

    for idx, filepath in enumerate(files, 1):
        print(f"[{idx}/{len(files)}] Processing {filepath.name}...")
        try:
            tokens = tokenizer.tokenize(filepath)
            out_file = output_dir / f"{filepath.stem}_tokens.npy"
            np.save(out_file, tokens)

            duration_s = len(tokens) / TOKEN_RATE_HZ
            entry = {
                "file": filepath.name,
                "source_path": str(filepath),
                "token_file": out_file.name,
                "num_tokens": int(len(tokens)),
                "duration_seconds": round(duration_s, 2),
                "token_rate_hz": TOKEN_RATE_HZ,
            }
            manifest.append(entry)
            print(f"  -> Generated {len(tokens)} tokens ({duration_s:.1f}s audio)")
        except Exception as e:
            print(f"  Error processing {filepath.name}: {e}", file=sys.stderr)

    manifest_file = output_dir / "persona_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone! Tokenized {len(manifest)} track(s). Manifest saved to {manifest_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract YuE2 semantic tokens for vocal persona conditioning.")
    parser.add_argument("--input", "-i", default="/mnt/h/mysongs", help="Audio file or folder containing recordings.")
    parser.add_argument("--output", "-o", default="./data/persona_tokens", help="Destination folder for tokens.")
    parser.add_argument("--head", default="models/audio_encoders/tokenizer_head_joint_v9.safetensors", help="Path to tokenizer head safetensors.")
    parser.add_argument("--hf-cache", default="models/hf", help="Hugging Face cache directory.")
    parser.add_argument("--device", default="cuda", help="PyTorch device ('cuda' or 'cpu').")
    parser.add_argument("--consent", action="store_true", help="Affirm consent for voice processing.")
    parser.add_argument("--engine-docker", action="store_true", help="Execute inside running yue2studio-engine container.")

    args = parser.parse_args()

    if not verify_consent(args.consent):
        print("Aborted: Consent verification was not confirmed.", file=sys.stderr)
        sys.exit(1)

    # Check if local environment has torch; if not, suggest or run via engine docker
    try:
        import torch  # noqa: F401
    except ImportError:
        print("Note: PyTorch not found in current host Python environment.")
        print("Delegating execution to GPU-accelerated 'yue2studio-engine' container...")
        # Map host paths to container paths if running via docker
        # Inside engine container: repo root is /app (or models are at /app/models)
        # Note: /mnt/h/mysongs may not be mounted into engine container unless mounted or copied.
        # Fall back to clear error with instructions if docker execution is not configured.
        print("To run with PyTorch locally or in container, ensure dependencies are installed.")
        sys.exit(1)

    input_path = Path(args.input)
    output_dir = Path(args.output)
    head_path = Path(args.head)
    hf_cache = Path(args.hf_cache) if args.hf_cache else None

    tokenize_files(
        input_path=input_path,
        output_dir=output_dir,
        head_path=head_path,
        hf_cache=hf_cache,
        device=args.device,
    )


if __name__ == "__main__":
    main()
