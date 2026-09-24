"""Start YuE2 Studio on Windows: the engine (ComfyUI) and the app, then the browser.

Run by the Start menu shortcut with the app's own Python.  Both programs belong to
a Windows job that ends when this window does, so closing the window stops them,
however it is closed.  Their output goes to logs\\engine.log and logs\\app.log.

Ports and folders can be changed in settings.ini beside this file.
"""
from __future__ import annotations

import configparser
import ctypes
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "engine"
COMFY = ENGINE / "ComfyUI"
LOGS = HERE / "logs"


def settings() -> dict:
    """Ports and the folder the library lives in.  settings.ini overrides the defaults."""
    values = {"app_port": "8090", "engine_port": "8188", "data_dir": str(HERE / "data"),
              "import_roots": str(Path.home()), "open_browser": "yes"}
    ini = HERE / "settings.ini"
    if ini.exists():
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        if parser.has_section("yue2"):
            values.update({k: v for k, v in parser.items("yue2") if v.strip()})
    return values


# ------------------------------------------------------------------ the job
# A job with KILL_ON_JOB_CLOSE ends every process in it when its last handle
# closes, which is when this process ends, even if the window is closed abruptly.
class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def join_a_job() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        print("  (could not tie the programs to this window; stop them from Task Manager if they linger)")
    join_a_job.handle = job   # kept open for as long as this process lives


# ---------------------------------------------------------------- helpers
def answering(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as reply:
            return reply.status == 200
    except OSError:
        return False


def port_taken(port: int) -> bool:
    import socket
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def wait_for(name: str, url: str, process: subprocess.Popen, log: Path, seconds: int) -> None:
    started = time.time()
    while time.time() - started < seconds:
        if answering(url):
            return
        if process.poll() is not None:
            fail(f"The {name} stopped while starting.", log)
        time.sleep(1)
    fail(f"The {name} did not start within {seconds // 60} minutes.", log)


def fail(message: str, log: Path | None = None) -> None:
    print()
    print(message)
    if log:
        print(f"The last lines of {log}:")
        print(tail(log))
    print()
    input("Press Enter to close this window.")
    sys.exit(1)


# ------------------------------------------------------------------- main
def main() -> None:
    os.system("title YuE2 Studio")
    cfg = settings()
    app_port, engine_port = int(cfg["app_port"]), int(cfg["engine_port"])
    url = f"http://localhost:{app_port}"
    print("YuE2 Studio")
    print()

    # Already running (a second click on the shortcut): just open the page.
    if answering(f"http://127.0.0.1:{app_port}/api/health"):
        print(f"YuE2 Studio is already running. Opening {url}")
        webbrowser.open(url)
        time.sleep(3)
        return
    for port, what in ((app_port, "the app"), (engine_port, "the engine")):
        if port_taken(port):
            fail(f"Port {port}, which {what} uses, is taken by another program. If Docker Desktop is "
                 f"running YuE2 Studio or ComfyUI, stop it first. The ports can be changed in "
                 f"{HERE / 'settings.ini'}.")

    engine_python = ENGINE / "python_embeded" / "python.exe"
    if not engine_python.exists() or not (COMFY / "main.py").exists():
        fail("The engine is not installed. Run the installer again.")

    join_a_job()
    LOGS.mkdir(exist_ok=True)
    data = Path(cfg["data_dir"])
    data.mkdir(parents=True, exist_ok=True)
    no_window = subprocess.CREATE_NO_WINDOW

    print("Starting the engine (ComfyUI)...")
    engine_log = LOGS / "engine.log"
    engine = subprocess.Popen(
        [str(engine_python), "-s", str(COMFY / "main.py"), "--windows-standalone-build",
         "--disable-auto-launch", "--listen", "127.0.0.1", "--port", str(engine_port)],
        cwd=str(COMFY), stdout=engine_log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
        creationflags=no_window)
    wait_for("engine", f"http://127.0.0.1:{engine_port}/system_stats", engine, engine_log, 600)

    print("Starting the app...")
    env = dict(os.environ)
    tools = HERE / "tools"
    env.update({
        "PATH": os.pathsep.join([str(HERE / "venv" / "Scripts"), str(tools / "ffmpeg" / "bin"), env.get("PATH", "")]),
        "DATA_DIR": str(data),
        "MODELS_DIR": str(COMFY / "models"),
        "VERSION_FILE": str(HERE / "studio" / "VERSION"),
        "ENGINE_URL": f"http://127.0.0.1:{engine_port}",
        "ENGINE_INPUT_DIR": str(COMFY / "input"),
        "ENGINE_OUTPUT_DIR": str(COMFY / "output"),
        "IMPORT_ROOTS": cfg["import_roots"],
        "TORCH_HOME": str(data / "models" / "torch"),
        "HF_HOME": str(data / "models" / "whisper"),
        "TRAINING_ENABLED": "1",
        "PYTHONUTF8": "1",
        # Windows without Developer Mode cannot make symlinks; the library copies instead
        # and says so every time.
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
    })
    app_log = LOGS / "app.log"
    app = subprocess.Popen(
        [str(HERE / "venv" / "Scripts" / "python.exe"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(app_port), "--no-access-log"],
        cwd=str(HERE / "studio"), env=env, stdout=app_log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT, creationflags=no_window)
    wait_for("app", f"http://127.0.0.1:{app_port}/api/health", app, app_log, 180)

    print()
    print(f"YuE2 Studio is running at {url}")
    print("Close this window to stop it.")
    if cfg["open_browser"].lower() not in ("no", "false", "0"):
        webbrowser.open(url)

    try:
        while True:
            time.sleep(2)
            for name, process, log in (("engine", engine, engine_log), ("app", app, app_log)):
                if process.poll() is not None:
                    fail(f"The {name} has stopped unexpectedly.", log)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
