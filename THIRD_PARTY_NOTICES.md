# Third-party notices

YuE2 Studio's own code is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)). It runs
models and software made by others, and each of those keeps its own terms. None of the model
weights are part of this repository: `scripts/fetch-models.sh` downloads them from their
publishers, and by using them you accept their terms.

This page is a summary for convenience, not legal advice. Where it and a publisher's own terms
differ, the publisher's terms apply.

## Models

### YuE2-3B (plans and renders)

- By HKUST M-A-P. Weights: **CC BY-NC 4.0, with an additional creator permission**.
  Source: [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B), repackaged for ComfyUI as
  [Comfy-Org/YuE2](https://huggingface.co/Comfy-Org/YuE2).
- The authors' terms, from the [YuE2 repository](https://github.com/multimodal-art-projection/YuE#license):
  - **Personal users, content creators and musicians** may use YuE2 and monetise the music they
    generate, with no fees or royalties payable to the authors.
  - **Academic research and education**: free for non-commercial use.
  - **Commercial companies**: contact the authors for a commercial licence for the weights.
  - The permission excludes illegal, harmful, deceptive or unethical use.
  - Attribution such as "YuE2" or "#YuE2" is encouraged, not required.
  - YuE2 is provided as is, without warranties, and users are responsible for their inputs,
    outputs and use.
- Official licence: [YuE2 MODEL_LICENSE](https://github.com/multimodal-art-projection/YuE/blob/main/MODEL_LICENSE),
  the weights licence with the creator permission. (The repository's `LICENSE` file is Apache 2.0
  and covers YuE2's code, not the weights.)

### SheetSage2 (transcription)

- By HKUST M-A-P. Weights: **CC BY-NC 4.0**.
  Source: [m-a-p/SheetSage2](https://huggingface.co/m-a-p/SheetSage2), repackaged in
  [Comfy-Org/YuE2](https://huggingface.co/Comfy-Org/YuE2).
- Official licence: [SheetSage2 LICENSE](https://huggingface.co/m-a-p/SheetSage2/blob/main/LICENSE)

### YuE2 instrumental LoRA (Instrumental mode)

- By Mothersuperior. **CC BY-NC 4.0**, inherited from YuE2-3B.
  Source: [Mothersuperior/YuE2-instrumental-cot-full-loras](https://huggingface.co/Mothersuperior/YuE2-instrumental-cot-full-loras).
- Its model card says nothing about monetising generated music. The YuE2 creator permission above
  comes from the YuE2 authors; check with the LoRA's author before relying on it for music made in
  Instrumental mode.
- Official licence: as declared on its [model card](https://huggingface.co/Mothersuperior/YuE2-instrumental-cot-full-loras).

### YuE2 Realaudio Tokenizer & Production LoRA (Realaudio polish & vocal persona)

- By Mothersuperior. **CC BY-NC 4.0**, inherited from YuE2-3B.
  Source: [Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4](https://huggingface.co/Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4).
- Production LoRA (`nar_lora_joint_v9_comfyui.safetensors`) enhances rendering fidelity and frequency separation.
- Audio Tokenizer head (`tokenizer_head_joint_v9.safetensors`) enables vocal token extraction in conjunction with MERT-v2.
- User consent: only use audio recordings that are your own voice or with explicit written consent from the performer.

### Gemma 4 E4B (lyric drafts)

- By Google. **Apache 2.0**.
  Source: [google/gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it), repackaged for
  ComfyUI as [Comfy-Org/gemma-4](https://huggingface.co/Comfy-Org/gemma-4).
- Official licence: [Google's Gemma 4 licence page](https://ai.google.dev/gemma/docs/gemma_4_license)

### Demucs (stems)

- By Meta. Code and weights: **MIT**. Source: [facebookresearch/demucs](https://github.com/facebookresearch/demucs).
  Installed in the app image; the weights are downloaded on first use.
- Official licence: [Demucs LICENSE](https://github.com/facebookresearch/demucs/blob/main/LICENSE)

## Software

### ComfyUI (the engine)

- **GPL-3.0**. Source: [comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI).
- It is not part of this repository. `engine/Dockerfile` builds it from its upstream source, and
  it runs as a separate container that the app talks to over HTTP.
- Official licence: [ComfyUI LICENSE](https://github.com/comfyanonymous/ComfyUI/blob/master/LICENSE)

### abcjs (staff notation)

- By Paul Rosen and Gregory Dyke. **MIT**. Source: [paulrosen/abcjs](https://github.com/paulrosen/abcjs).
- Vendored in `app/static/abcjs-basic-min.js`, with its licence in
  [app/static/abcjs.LICENSE.md](app/static/abcjs.LICENSE.md).

### Python packages

- The app's packages are listed, with pinned versions, in `requirements.txt`. Each is used under
  its own licence, installed from PyPI when the image is built.
