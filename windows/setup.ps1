# YuE2 Studio for Windows: checks this PC, then fetches and sets up everything the
# installer does not carry.  Every part comes from its own publisher, pinned to a
# version and checked by sha256 where the publisher gives one.  Safe to run again:
# whatever is already in place is kept, and an interrupted download carries on.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -InstallDir <folder> [-NoLyrics]
#   ... -CheckOnly        only the system check
#   ... -SkipModels       everything but the 18 GB of models (for testing)

param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [switch]$NoLyrics,
    [switch]$CheckOnly,
    [switch]$SkipModels
)

# 32-bit PowerShell sees SysWOW64 where System32 should be, so it cannot find
# nvidia-smi, among other things.  Start again in the 64-bit one.
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    $native = Join-Path $env:WINDIR 'Sysnative\WindowsPowerShell\v1.0\powershell.exe'
    $again = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-InstallDir', $InstallDir)
    foreach ($flag in @('NoLyrics', 'CheckOnly', 'SkipModels')) { if ($PSBoundParameters[$flag]) { $again += "-$flag" } }
    & $native @again
    exit $LASTEXITCODE
}

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest's bar is very slow in 5.1
$Host.UI.RawUI.WindowTitle = 'Setting up YuE2 Studio'

$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$Downloads = Join-Path $InstallDir 'downloads'
$Tools = Join-Path $InstallDir 'tools'
$Engine = Join-Path $InstallDir 'engine'
$ComfyDir = Join-Path $Engine 'ComfyUI'
$Models = Join-Path $ComfyDir 'models'
$Logs = Join-Path $InstallDir 'logs'
$State = Join-Path $InstallDir 'state'
foreach ($d in @($InstallDir, $Downloads, $Tools, $Logs, $State)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
Start-Transcript -Path (Join-Path $Logs 'install.log') -Append | Out-Null

# ------------------------------------------------------------------------ pins
# What was tested together.  Change one deliberately, and test again.
$Pins = @{
    ComfyCommit   = '36da3ff763687eab86a35e1019995dd1fb369b0d'   # the commit engine/Dockerfile builds
    FsAudioCommit = '26fe2e91d20ebf3531cf053c0c654fd3b849e5de'
    AppPython     = '3.13'
}
# ComfyUI's own Windows build: its embedded Python and CUDA torch.  The default wants
# an NVIDIA driver of 580 or later (CUDA 13.0); the cu126 build serves older ones.
$Portables = @{
    cu130 = @{ Url = 'https://github.com/Comfy-Org/ComfyUI/releases/download/v0.37.0/ComfyUI_windows_portable_nvidia.7z'
               Sha = '7805f634fab51f63a238aaf0cfe2a9833bb7c86ddfc8400a60919f44460d7d65'; Size = 1925204508 }
    cu126 = @{ Url = 'https://github.com/Comfy-Org/ComfyUI/releases/download/v0.37.0/ComfyUI_windows_portable_nvidia_cu126.7z'
               Sha = '4f8c587c8319a3595dcdc6b8fbfc7234d2d02fa6b1a328c1ab3e819c97d95fb8'; Size = 1867201814 }
}
$Files = @{
    SevenZip = @{ Url = 'https://github.com/ip7z/7zip/releases/download/26.03/7zr.exe'
                  Sha = 'ad4c82fadcbdf93c03b4fc440f300509c7d60c5c2f4d183e35d9d70d6957037d'; Size = 602624 }
    Uv       = @{ Url = 'https://github.com/astral-sh/uv/releases/download/0.12.18/uv-x86_64-pc-windows-msvc.zip'
                  Sha = 'cae6a3bc25239f83dffb467a4b180508d9da23986c04639ebfa44e43e6a84bff'; Size = 17891221 }
    Ffmpeg   = @{ Url = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
                  Sha = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'; Size = 114768076 }
}
$HF = 'https://huggingface.co'
$ModelFiles = @(
    @{ Name = 'YuE2 (plans and renders)'; Dir = 'checkpoints'; File = 'yue2_3b_bf16.safetensors'
       Url = "$HF/Comfy-Org/YuE2/resolve/main/checkpoints/yue2_3b_bf16.safetensors"
       Sha = '33765adbf9813c9a50318218760b2fd819a319862460a04884607581961c6fee'; Size = 7799983228 }
    @{ Name = 'SheetSage2 (transcription)'; Dir = 'audio_encoders'; File = 'sheetsage2_bf16.safetensors'
       Url = "$HF/Comfy-Org/YuE2/resolve/main/audio_encoders/sheetsage2_bf16.safetensors"
       Sha = '5fd960ce3df281e3f3a889d174584d88f96247711480cf96377b12d7e8b6adc5'; Size = 1386868122 }
    @{ Name = 'Gemma 4 (lyric drafts, song analysis)'; Dir = 'text_encoders'; File = 'gemma4_e4b_it_int8_convrot.safetensors'; Lyrics = $true
       Url = "$HF/Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_int8_convrot.safetensors"
       Sha = '974d0c838ef4ac1a989b06ccb4e57691c21b6270dd8e345ffa7531f9388f117c'; Size = 8090965702 }
    @{ Name = 'Instrumental LoRA'; Dir = 'loras'; File = 'ar_lora_inst_v3abc_comfyui.safetensors'
       Url = "$HF/Mothersuperior/YuE2-instrumental-cot-full-loras/resolve/main/ar_lora_inst_v3abc_comfyui.safetensors"
       Sha = 'de6a11d5701df103a191c87dc73115266e2420f3834739319dec5c24d2119f31'; Size = 212891736 }
    @{ Name = 'Production polish LoRA'; Dir = 'loras'; File = 'nar_lora_joint_v9_comfyui.safetensors'
       Url = "$HF/Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4/resolve/main/nar_lora_joint_v9_comfyui.safetensors"
       Sha = 'cd2bf0d3ce4bf68697daa016671da7d70e34e2f5545617ab9094c96b14a581db'; Size = 107518800 }
    @{ Name = 'Realaudio tokenizer head'; Dir = 'audio_encoders'; File = 'tokenizer_head_joint_v9.safetensors'
       Url = "$HF/Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4/resolve/main/tokenizer_head_joint_v9.safetensors"
       Sha = '06440f25605c6c12c4e517ef033d7b70b8d9e961b3b06aa3848b1f8028fd7eb8'; Size = 171278808 }
    @{ Name = 'Training regularizer pack'; Dir = 'fs_audio'; File = 'minted_regularizer_pack_v2.pt'
       Url = "$HF/Mothersuperior/YuE2-hum-to-song/resolve/main/minted_regularizer_pack_v2.pt"
       Sha = '587631eec5946f9f87d4b422abcda7e35dee43299efb7b7d2fcba4cd8752c475'; Size = 296098847 }
)
if ($NoLyrics) { $ModelFiles = @($ModelFiles | Where-Object { -not $_.Lyrics }) }

# ------------------------------------------------------------------- helpers
function Say([string]$text, [string]$colour = 'Gray') { Write-Host $text -ForegroundColor $colour }
function Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Done([string]$name) { Set-Content -Path (Join-Path $State "$name.done") -Value (Get-Date -Format s) }
function IsDone([string]$name) { Test-Path (Join-Path $State "$name.done") }

function Stop-Setup([string]$why) {
    Write-Host ''
    Write-Host "Setup stopped: $why" -ForegroundColor Red
    Write-Host "The details are in $(Join-Path $Logs 'install.log')."
    Write-Host 'Run the installer again to carry on from here.'
    Stop-Transcript | Out-Null
    Read-Host 'Press Enter to close this window' | Out-Null
    exit 1
}

# A file from its publisher.  curl (built into Windows) resumes a broken download;
# the sha256 is checked once and remembered, so a second run does not read 8 GB again.
function Get-Verified($spec, [string]$dest) {
    $ok = "$dest.sha256ok"
    if ((Test-Path $dest) -and (Test-Path $ok)) { return }
    $part = "$dest.part"
    if (-not (Test-Path $dest)) {
        Say ("Downloading {0} ({1:N0} MB)" -f (Split-Path $dest -Leaf), ($spec.Size / 1e6))
        for ($try = 1; $try -le 6; $try++) {
            & curl.exe -L --fail --retry 5 -C - -# -o $part $spec.Url
            if ($LASTEXITCODE -eq 0) { break }
            if ($try -eq 6) { Stop-Setup "could not download $($spec.Url)" }
            Say "  the download broke off; trying again ($try of 5)" 'Yellow'
            Start-Sleep -Seconds (5 * $try)
        }
        Move-Item -Force $part $dest
    }
    if ($spec.Size -and (Get-Item $dest).Length -ne $spec.Size) {
        Remove-Item -Force $dest
        Stop-Setup "$(Split-Path $dest -Leaf) came down the wrong size; it has been removed, so the next run fetches it again"
    }
    if ($spec.Sha) {
        Say "  checking $(Split-Path $dest -Leaf)"
        $hash = (Get-FileHash -Algorithm SHA256 $dest).Hash.ToLower()
        if ($hash -ne $spec.Sha) {
            Remove-Item -Force $dest
            Stop-Setup "$(Split-Path $dest -Leaf) did not match its published checksum; it has been removed, so the next run fetches it again"
        }
    }
    Set-Content -Path $ok -Value (Get-Date -Format s)
}

function Expand-Zip([string]$zip, [string]$to) {
    if (Test-Path $to) { Remove-Item -Recurse -Force $to }
    Expand-Archive -Path $zip -DestinationPath $to -Force
}

# An archive of one commit from GitHub.  GitHub builds these on request, so they have
# no fixed checksum; the commit id pins the contents.
function Get-Commit([string]$repo, [string]$commit, [string]$dest) {
    $zip = Join-Path $Downloads "$($repo.Replace('/', '_'))-$($commit.Substring(0, 8)).zip"
    if (-not (Test-Path $zip)) {
        Say "Downloading $repo at $($commit.Substring(0, 8))"
        & curl.exe -L --fail --retry 5 -# -o "$zip.part" "https://codeload.github.com/$repo/zip/$commit"
        if ($LASTEXITCODE -ne 0) { Stop-Setup "could not download $repo" }
        Move-Item -Force "$zip.part" $zip
    }
    $tmp = Join-Path $Downloads 'unpack'
    Expand-Zip $zip $tmp
    $inner = Get-ChildItem $tmp | Select-Object -First 1
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Move-Item $inner.FullName $dest
    Remove-Item -Recurse -Force $tmp
}

function Invoke-Checked([string]$what, [string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { Stop-Setup "$what failed (exit code $LASTEXITCODE)" }
}

function Test-Port([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $port); return $true } catch { return $false } finally { $client.Close() }
}

# Anything unforeseen stops here too, with the window left open to read, rather
# than closing on the error.
trap {
    $where = $_.InvocationInfo.ScriptLineNumber
    Stop-Setup "an unexpected error at line ${where}: $($_.Exception.Message)"
}

# -------------------------------------------------------------- system check
Step 'Checking this PC'
$problems = New-Object System.Collections.ArrayList
$warnings = New-Object System.Collections.ArrayList

$os = [Environment]::OSVersion.Version
if (-not [Environment]::Is64BitOperatingSystem) { [void]$problems.Add('Windows must be 64-bit.') }
if ($os.Build -lt 19045) { [void]$problems.Add("Windows 10 22H2 or Windows 11 is needed (this is build $($os.Build)).") }
Say ("Windows build {0}, PowerShell {1}, {2}-bit" -f $os.Build, $PSVersionTable.PSVersion, $(if ([Environment]::Is64BitProcess) { 64 } else { 32 }))

$variant = $null
$smi = Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'
if (-not (Test-Path $smi)) { $cmd = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue; if ($cmd) { $smi = $cmd.Source } }
if (-not (Test-Path $smi)) {
    [void]$problems.Add('No NVIDIA graphics card was found (nvidia-smi is missing). YuE2 Studio needs an NVIDIA card, RTX 30-series or newer, with its driver installed.')
} else {
    $line = (& $smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    if (-not $line) {
        [void]$problems.Add('The NVIDIA driver did not answer. Install or update it from nvidia.com, then run the installer again.')
    } else {
        $f = $line.Split(',') | ForEach-Object { $_.Trim() }
        $gpu = $f[0]; $vramGB = [math]::Round([double]$f[1] / 1024, 1); $driver = $f[2]; $cap = $f[3]
        Say ("Graphics card: {0}, {1} GB, driver {2}, compute {3}" -f $gpu, $vramGB, $driver, $cap)
        $major = [int]($driver.Split('.')[0])
        if ($major -ge 580) { $variant = 'cu130' }
        elseif ($major -ge 528) { $variant = 'cu126' }
        else { [void]$problems.Add("The NVIDIA driver ($driver) is too old. Update it from nvidia.com, then run the installer again.") }
        if ($cap -and [double]$cap -lt 8.0) {
            [void]$problems.Add("$gpu is too old for YuE2, which needs an RTX 30-series card or newer (bf16).")
        }
        if ($vramGB -lt 7.5) { [void]$problems.Add("$gpu has $vramGB GB of video memory; YuE2 needs 8 GB, and 12 GB or more is recommended.") }
        elseif ($vramGB -lt 11.5) { [void]$warnings.Add("$vramGB GB of video memory works, but lyric drafts on this PC will be slow. 12 GB or more is recommended.") }
    }
}

$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
Say "Memory: $ramGB GB"
if ($ramGB -lt 15) { [void]$warnings.Add("This PC has $ramGB GB of memory; 16 GB is recommended.") }

# Room for what is still to come: the missing models, plus about 12 GB for the engine,
# the app and the downloads while they unpack.
# Sizes are shown in thousands, as the installer's own pages and download sites count.
$needBytes = 14e9   # the engine, the app, Whisper and demucs, and room to unpack
foreach ($m in $ModelFiles) { if (-not (Test-Path (Join-Path (Join-Path $Models $m.Dir) $m.File))) { $needBytes += $m.Size } }
if ($SkipModels) { $needBytes = 12e9 }
$drive = (Get-Item $InstallDir).PSDrive
$freeGB = [math]::Round($drive.Free / 1e9, 1)
Say ("Free space on {0}: {1} GB (needed: about {2} GB)" -f $drive.Name, $freeGB, [math]::Ceiling($needBytes / 1e9))
if ($drive.Free -lt $needBytes) { [void]$problems.Add("Not enough free space on $($drive.Name): about $([math]::Ceiling($needBytes / 1e9)) GB is needed.") }

if ($InstallDir.Length -gt 60) { [void]$warnings.Add("The install folder's path is long ($($InstallDir.Length) characters); a shorter one avoids Windows' path length limit.") }

foreach ($port in @(8090, 8188)) {
    if (Test-Port $port) { [void]$warnings.Add("Something is already using port $port (Docker Desktop, or another copy of YuE2 Studio or ComfyUI?). Stop it before starting YuE2 Studio.") }
}

foreach ($site in @('https://huggingface.co', 'https://github.com', 'https://pypi.org', 'https://download.pytorch.org')) {
    & curl.exe -s -o NUL -I --max-time 15 $site
    if ($LASTEXITCODE -ne 0) { [void]$problems.Add("Cannot reach $site. Check the internet connection, or a firewall or proxy.") }
}

foreach ($w in $warnings) { Say "  note: $w" 'Yellow' }
if ($problems.Count) {
    foreach ($p in $problems) { Say "  problem: $p" 'Red' }
    Stop-Setup 'this PC does not meet the requirements above'
}
Say 'This PC is suitable.' 'Green'
if ($CheckOnly) { Stop-Transcript | Out-Null; exit 0 }

# ------------------------------------------------------------------- tools
Step 'Tools'
Get-Verified $Files.SevenZip (Join-Path $Tools '7zr.exe')
$uvZip = Join-Path $Downloads 'uv.zip'
Get-Verified $Files.Uv $uvZip
if (-not (Test-Path (Join-Path $Tools 'uv\uv.exe'))) { Expand-Zip $uvZip (Join-Path $Tools 'uv') }
$ffZip = Join-Path $Downloads 'ffmpeg.zip'
Get-Verified $Files.Ffmpeg $ffZip
if (-not (Test-Path (Join-Path $Tools 'ffmpeg\bin\ffmpeg.exe'))) {
    $tmp = Join-Path $Downloads 'ffmpeg-unpack'
    Expand-Zip $ffZip $tmp
    if (Test-Path (Join-Path $Tools 'ffmpeg')) { Remove-Item -Recurse -Force (Join-Path $Tools 'ffmpeg') }
    Move-Item (Get-ChildItem $tmp | Select-Object -First 1).FullName (Join-Path $Tools 'ffmpeg')
    Remove-Item -Recurse -Force $tmp
}
$uv = Join-Path $Tools 'uv\uv.exe'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $InstallDir 'python'
$env:UV_CACHE_DIR = Join-Path $Downloads 'uv-cache'

# ------------------------------------------------------------------- engine
Step 'The engine (ComfyUI)'
$engineMark = "engine-$variant-$($Pins.ComfyCommit.Substring(0, 8))"
if (-not (IsDone $engineMark)) {
    $portable = $Portables[$variant]
    $archive = Join-Path $Downloads (Split-Path $portable.Url -Leaf)
    Get-Verified $portable $archive
    Say 'Unpacking the engine (a few minutes)'
    $tmp = Join-Path $InstallDir 'engine-unpack'
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Invoke-Checked 'Unpacking the engine' (Join-Path $Tools '7zr.exe') @('x', $archive, "-o$tmp", '-y', '-bso0', '-bsp1')
    $unpacked = Get-ChildItem $tmp -Directory | Select-Object -First 1
    # Keep the models and anything made with the engine when it is replaced.
    $keep = Join-Path $InstallDir 'engine-keep'
    if (Test-Path $ComfyDir) {
        New-Item -ItemType Directory -Force -Path $keep | Out-Null
        foreach ($sub in @('models', 'input', 'output', 'user')) {
            if (Test-Path (Join-Path $ComfyDir $sub)) { Move-Item (Join-Path $ComfyDir $sub) (Join-Path $keep $sub) }
        }
    }
    if (Test-Path $Engine) { Remove-Item -Recurse -Force $Engine }
    Move-Item $unpacked.FullName $Engine
    Remove-Item -Recurse -Force $tmp

    # The portable build brings a newer ComfyUI than the one tested here; that one is
    # put in its place, over the same Python.
    Get-Commit 'Comfy-Org/ComfyUI' $Pins.ComfyCommit $ComfyDir
    if (Test-Path $keep) {
        foreach ($sub in @('models', 'input', 'output', 'user')) {
            $saved = Join-Path $keep $sub
            if (Test-Path $saved) {
                if (Test-Path (Join-Path $ComfyDir $sub)) { Remove-Item -Recurse -Force (Join-Path $ComfyDir $sub) }
                Move-Item $saved (Join-Path $ComfyDir $sub)
            }
        }
        Remove-Item -Recurse -Force $keep
    }
    $py = Join-Path $Engine 'python_embeded\python.exe'
    Say "Installing the engine's packages"
    Invoke-Checked "The engine's packages" $py @('-s', '-m', 'pip', 'install', '--no-warn-script-location', '-r', (Join-Path $ComfyDir 'requirements.txt'))
    Done $engineMark
    # Unpacked and working: the 1.8 GB archive is not needed again.
    Remove-Item -Force -ErrorAction SilentlyContinue $archive, "$archive.sha256ok"
}
$py = Join-Path $Engine 'python_embeded\python.exe'

$nodes = Join-Path $ComfyDir 'custom_nodes'
if (-not (IsDone "fs_audio-$($Pins.FsAudioCommit.Substring(0, 8))") -or -not (Test-Path (Join-Path $nodes 'ComfyUI-FS_Audio_Suite'))) {
    Get-Commit 'KytraScript/ComfyUI-FS_Audio_Suite' $Pins.FsAudioCommit (Join-Path $nodes 'ComfyUI-FS_Audio_Suite')
    Invoke-Checked "The trainer's packages" $py @('-s', '-m', 'pip', 'install', '--no-warn-script-location', 'soundfile>=0.12', 'librosa>=0.10', 'scipy')
    Done "fs_audio-$($Pins.FsAudioCommit.Substring(0, 8))"
}
# Our own node, carried by the installer.
$harmony = Join-Path $nodes 'yue2_harmony'
if (Test-Path $harmony) { Remove-Item -Recurse -Force $harmony }
Copy-Item -Recurse (Join-Path $InstallDir 'studio\engine-nodes\yue2_harmony') $harmony
foreach ($sub in @('checkpoints', 'audio_encoders', 'text_encoders', 'loras', 'fs_audio')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Models $sub) | Out-Null
}
# Models kept by an uninstall come back, with the LoRAs trained here.
$kept = Join-Path $InstallDir 'models-kept'
if (Test-Path $kept) {
    Say 'Putting back the models kept by the last uninstall'
    Get-ChildItem $kept -Recurse -File | ForEach-Object {
        $target = Join-Path $Models $_.FullName.Substring($kept.Length + 1)
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        if (-not (Test-Path $target)) { Move-Item $_.FullName $target }
    }
    Remove-Item -Recurse -Force $kept
}

# ---------------------------------------------------------------------- app
Step 'The app'
$venv = Join-Path $InstallDir 'venv'
$appPy = Join-Path $venv 'Scripts\python.exe'
$reqs = Join-Path $InstallDir 'studio\requirements.txt'
$appMark = 'app-' + (Get-FileHash -Algorithm SHA256 $reqs).Hash.Substring(0, 12).ToLower()
if (-not (IsDone $appMark) -or -not (Test-Path $appPy)) {
    Invoke-Checked 'Python for the app' $uv @('python', 'install', $Pins.AppPython)
    if (-not (Test-Path $appPy)) { Invoke-Checked 'The app environment' $uv @('venv', '--python', $Pins.AppPython, $venv) }
    Invoke-Checked "The app's packages" $uv @('pip', 'install', '--python', $appPy, '-r', $reqs)
    # Stems run on the CPU, as in the app container: the GPU belongs to YuE2.
    Invoke-Checked 'Torch for stems' $uv @('pip', 'install', '--python', $appPy, 'torch==2.9.1', 'torchaudio==2.9.1', '--index-url', 'https://download.pytorch.org/whl/cpu')
    Invoke-Checked 'demucs' $uv @('pip', 'install', '--python', $appPy, 'demucs==4.1.0')
    Done $appMark
}
New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'data') | Out-Null

# ------------------------------------------------------------------- models
if (-not $SkipModels) {
    Step 'The models (the long part)'
    $total = 0
    foreach ($m in $ModelFiles) { $total += $m.Size }
    Say ("{0} files, {1:N1} GB in all. Downloads resume if they break off." -f $ModelFiles.Count, ($total / 1e9))
    foreach ($m in $ModelFiles) {
        Say ''
        Say $m.Name 'White'
        Get-Verified $m (Join-Path (Join-Path $Models $m.Dir) $m.File)
    }
}

# ------------------------------------------------------ the app's own models
# Whisper (times the lyric lines of a cover) and demucs (separates the vocal) would
# otherwise download the first time a cover or stems are made, and leave that first
# go sitting on a 1.6 GB download.  Fetched with the app's own Python, by the same
# calls the app makes, so they land where it looks.
if (-not $SkipModels -and -not (IsDone 'app-models')) {
    Step "The app's own models (lyric timing and stems)"
    $dataDir = Join-Path $InstallDir 'data'
    $ini = Join-Path $InstallDir 'settings.ini'
    if (Test-Path $ini) {
        $line = Get-Content $ini | Where-Object { $_ -match '^\s*data_dir\s*=\s*(.+?)\s*$' } | Select-Object -First 1
        if ($line -and $Matches[1]) { $dataDir = $Matches[1] }
    }
    # As the launcher sets them for the app: demucs 4.1 fetches from Hugging Face, so
    # its model goes where HF_HOME says, and Whisper is given its folder directly.
    $env:TORCH_HOME = Join-Path $dataDir 'models\torch'
    $env:HF_HOME = Join-Path $dataDir 'models\whisper'
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
    Say 'Whisper large-v3-turbo (about 1.6 GB)'
    $whisperDir = Join-Path $dataDir 'models\whisper'
    Invoke-Checked 'Whisper' $appPy @('-c', "from faster_whisper import download_model; download_model('large-v3-turbo', cache_dir=r'$whisperDir')")
    Say 'demucs htdemucs (about 80 MB)'
    Invoke-Checked 'demucs' $appPy @('-c', "from demucs.pretrained import get_model; get_model('htdemucs')")
    Done 'app-models'
}

# -------------------------------------------------------------------- done
# uv's download cache is only needed while installing.
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $env:UV_CACHE_DIR
Step 'Finished'
Say 'YuE2 Studio is set up. Start it from the Start menu or the desktop.' 'Green'
Stop-Transcript | Out-Null
exit 0
