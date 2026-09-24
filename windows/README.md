# The Windows installer

A small installer (under 1 MB) for people who would rather not use Docker. It runs natively
on Windows: no Docker, no WSL and no administrator prompt. **First pass: being tested.**

## What it does

1. **Shows the terms** of each part (`terms.txt`) and asks whether to include Gemma, for lyric
   drafts on this PC (8 GB).
2. **Copies our own files** into `%LOCALAPPDATA%\Programs\YuE2Studio`: the app, our engine node,
   `setup.ps1`, `launcher.py` and the notices.
3. **Runs `setup.ps1`** in a window that shows its progress.
   - It checks the PC: Windows 10 22H2 or 11, an NVIDIA card of compute capability 8.0 or
     higher (RTX 30-series or newer, for bf16), video memory, driver, RAM, disk space, ports and
     network.
   - It then fetches the rest from each publisher, pinned, checking each file's sha256 where
     the publisher gives one:
     - ComfyUI's own Windows portable build, for its Python and CUDA torch. It takes the CUDA
       13.0 build with driver 580 or later, and the CUDA 12.6 build otherwise.
     - The ComfyUI commit `engine/Dockerfile` pins, in place of the portable's newer one.
     - FS_Audio Suite.
     - uv, which installs a Python for the app and its packages (CPU torch and demucs, as in
       the app image).
     - ffmpeg and 7-Zip's `7zr.exe`.
     - The models from Hugging Face.
   - Downloads resume. A second run keeps whatever is already in place, which is also what
     **Repair** in the Start menu does.
4. **Adds shortcuts** to the Start menu and the desktop, and an uninstaller. The uninstaller
   offers to keep the library and the models; a reinstall puts the models back.

**The launcher** (`launcher.py`, run by the shortcut) starts the engine and the app, waits for
both, and opens the browser. Both run in a Windows job tied to its window, so closing the window
stops them. Their output goes to `logs\engine.log` and `logs\app.log`, and the install's own log
to `logs\install.log`. Ports and the library folder can be changed in `settings.ini`:

```ini
[yue2]
app_port = 8090
engine_port = 8188
data_dir = D:\YuE2 library
```

## Building

```bash
sh windows/build.sh
```

The installer lands in `windows/dist/`.
- **On Linux or in CI**, it uses `makensis` (`apt install nsis`).
- **From WSL**, it uses the Windows NSIS zip, unpacked, with nothing installed. Set `NSIS_DIR`
  to its folder; the default is `C:\Users\Public\yue2-build\nsis-3.12`.

## Testing without the 18 GB of models

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -InstallDir C:\somewhere -SkipModels
powershell -ExecutionPolicy Bypass -File setup.ps1 -InstallDir C:\somewhere -CheckOnly
```

## Not done yet

- **Signing.** Until the installer is signed, Windows shows *Windows protected your PC*; choose
  *More info*, then *Run anyway*. SignPath Foundation signs open-source projects for free (see
  IDEAS.md).
- **Tested on one PC only** so far. It has not been tried on a clean machine, on the CUDA 12.6
  build, or with a card below 16 GB.
- **An app already on ports 8090 and 8188** (the Docker version, say) has to be stopped first.
  The installer and the launcher both check for this.
