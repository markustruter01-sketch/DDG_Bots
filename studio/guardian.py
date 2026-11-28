"""Guardian: the one place that starts the studio, checks it and heals it (28 Nov 2026).

Why: on 27-28 Nov the AI engine (Ollama) froze for ~17 hours and nothing noticed; then a restart started an Ollama
that could not find Qwen (it lives on F:, Ollama's default folder on C: is empty). The old watchdog only checked the
dashboard and the crypto bot.

    python -m studio.guardian start [--browser]   start whatever is not running (AI engine first)
    python -m studio.guardian check               every 5 minutes: heal whatever is down or frozen
    python -m studio.guardian stop                stop the dashboard, crypto bot, video watcher and AI engine
    python -m studio.guardian restart-ai          stop and start the AI engine only

Everything it does is written to logs/watchdog.log. The dashboard, crypto bot and AI engine write their own output to
logs/server.log, logs/crypto.log and logs/ollama.log, so a crash leaves a trace.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
SETTINGS = ROOT / "config" / "settings.json"
CRYPTO_STATE = ROOT / "data" / "crypto" / "state.json"
GUARD_STATE = LOGS / "guardian_state.json"
AEST = timezone(timedelta(hours=10))

DEFAULT_MODELS_DIR = r"F:\DDG_Video_Studio\models\ollama"
CRYPTO_STALE_S = 180          # the crypto bot writes its state every few seconds
AI_RECENT_S = 20 * 60         # a good crypto decision this recent proves the AI engine works: no test needed
PROBE_TIMEOUT_S = 150         # a cold load took ~28 s on 26 Nov; give a busy PC room before calling it frozen
PROBE_FAILS_TO_RESTART = 2    # two failed tests in a row (5 minutes apart) before restarting the engine
LOG_MAX_BYTES = 5 * 1024 * 1024


def settings() -> Dict[str, Any]:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ollama_conf() -> Dict[str, Any]:
    o = settings().get("ollama", {})
    return {"base_url": o.get("base_url", "http://127.0.0.1:11434").rstrip("/"),
            "model": o.get("text_model", "qwen3:8b"),
            "models_dir": o.get("models_dir", DEFAULT_MODELS_DIR),
            "host": o.get("base_url", "http://127.0.0.1:11434").split("://", 1)[-1].rstrip("/")}


def studio_url() -> str:
    d = settings().get("dashboard", {})
    return f"http://{d.get('host', '127.0.0.1')}:{d.get('port', 8765)}"


def log(msg: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(AEST).strftime('%d/%m/%Y %H:%M:%S')}  {msg}"
    with open(LOGS / "watchdog.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line, flush=True)
    except (OSError, ValueError):      # pythonw has no console
        pass


# ── talking to things over HTTP (swapped out in tests) ──────────────────────────────────────────────────────────────
def http_json(url: str, body: Optional[dict] = None, timeout: float = 10) -> Tuple[Optional[int], Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None, None


# ── running programs (swapped out in tests) ──────────────────────────────────────────────────────────────────────────
WIN = os.name == "nt"
DETACHED = (0x00000008 | 0x00000200 | 0x08000000) if WIN else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW


def run(cmd: List[str], timeout: float = 30) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=0x08000000 if WIN else 0).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def spawn(cmd: List[str], log_name: str, env: Optional[Dict[str, str]] = None) -> bool:
    """Start a program in the background, its output going to logs/<log_name>; it keeps running after we exit."""
    LOGS.mkdir(parents=True, exist_ok=True)
    rotate(LOGS / log_name)
    try:
        with open(LOGS / log_name, "a", encoding="utf-8", errors="replace") as out:   # the program keeps its own copy
            out.write(f"\n===== started {datetime.now(AEST).isoformat(timespec='seconds')}: {' '.join(cmd)}\n")
            out.flush()
            subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=DETACHED, close_fds=True, start_new_session=not WIN)
        return True
    except OSError as e:
        log(f"could not start {cmd[0]}: {e}")
        return False


def rotate(path: Path) -> None:
    """Keep each log under 5 MB: the old one becomes .1 (replacing the previous .1). Skipped if the file is in use."""
    try:
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def python_exe(console: bool = False) -> str:
    scripts = ROOT / ".venv" / ("Scripts" if WIN else "bin")
    for name in (["python.exe"] if console else ["pythonw.exe", "python.exe"]) if WIN else ["python3", "python"]:
        if (scripts / name).exists():
            return str(scripts / name)
    return sys.executable


def ollama_exe() -> str:
    if WIN:
        p = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if p.exists():
            return str(p)
    return "ollama"


class System:
    """Everything that touches the PC, in one place so tests can replace it."""
    http = staticmethod(http_json)
    run = staticmethod(run)
    spawn = staticmethod(spawn)
    sleep = staticmethod(time.sleep)
    code_version = staticmethod(lambda: code_version())   # defined further down
    now = staticmethod(lambda: datetime.now(AEST))

    @staticmethod
    def gaming() -> Tuple[bool, str]:
        """A game or Unreal from the settings list is running (graphics memory alone doesn't count: a browser can
        use plenty, and that must not stop a frozen engine being fixed)."""
        try:
            from studio.vram_baton import get_running_processes
            running = get_running_processes()
            for name in settings().get("gpu", {}).get("pause_on_processes", []):
                if name.lower() in running:
                    return True, f"{name} is running"
        except Exception:
            pass
        return False, ""

    @staticmethod
    def crypto_state() -> Optional[Dict[str, Any]]:
        try:
            return json.loads(CRYPTO_STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def crypto_age_s() -> Optional[float]:
        try:
            return time.time() - CRYPTO_STATE.stat().st_mtime
        except OSError:
            return None


# ── the AI engine ───────────────────────────────────────────────────────────────────────────────────────────────────
def ollama_env() -> Dict[str, str]:
    c = ollama_conf()
    env = dict(os.environ)
    env.update(OLLAMA_HOST=c["host"], OLLAMA_MODELS=c["models_dir"], OLLAMA_KEEP_ALIVE="30m")
    return env


def remember_model_folder(sysm: System = System) -> None:
    """Save the model folder as a Windows setting, so an Ollama started any other way (its tray app, a manual start)
    still finds Qwen. Only writes when the value differs."""
    if not WIN:
        return
    c = ollama_conf()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            current = winreg.QueryValueEx(k, "OLLAMA_MODELS")[0]
    except OSError:
        current = None
    if current != c["models_dir"]:
        sysm.run(["setx", "OLLAMA_MODELS", c["models_dir"]])
        sysm.run(["setx", "OLLAMA_HOST", c["host"]])
        log(f"saved the AI model folder as a Windows setting: OLLAMA_MODELS={c['models_dir']}")


def ollama_models(sysm: System = System) -> Optional[List[str]]:
    """Models the engine says it has, or None if it doesn't answer within 10 s."""
    code, data = sysm.http(ollama_conf()["base_url"] + "/api/tags", None, 10)
    if code != 200 or not isinstance(data, dict):
        return None
    return [m.get("name", "") for m in data.get("models", [])]


def has_model(names: List[str], model: str) -> bool:
    want = model if ":" in model else model + ":latest"
    return any(n == want for n in names)


def ollama_answers(sysm: System = System) -> Tuple[bool, str]:
    """A one-word question to Qwen. Uses the same window and keep-alive as everything else, so nothing reloads."""
    from crypto_paper import rules as R
    c = ollama_conf()
    t0 = time.time()
    code, data = sysm.http(c["base_url"] + "/api/generate",
                           {"model": c["model"], "prompt": "Reply with OK.", "stream": False, "think": False,
                            "keep_alive": R.KEEP_ALIVE, "options": {"num_predict": 2, "num_ctx": R.NUM_CTX}},
                           PROBE_TIMEOUT_S)
    secs = round(time.time() - t0, 1)
    if code == 200:
        return True, f"answered in {secs} s"
    return False, (f"HTTP {code}" if code else f"no answer in {secs} s")


def stop_ollama(sysm: System = System) -> None:
    if WIN:
        sysm.run(["taskkill", "/F", "/IM", "ollama app.exe"])
        sysm.run(["taskkill", "/F", "/IM", "ollama.exe"])
    else:
        sysm.run(["pkill", "-f", "ollama serve"])


def start_ollama(sysm: System = System, wait_s: int = 20) -> bool:
    sysm.spawn([ollama_exe(), "serve"], "ollama.log", ollama_env())
    for _ in range(wait_s):
        sysm.sleep(1)
        if ollama_models(sysm) is not None:
            return True
    return False


def restart_ollama(reason: str, sysm: System = System) -> bool:
    log(f"AI engine: {reason} - restarting it")
    remember_model_folder(sysm)
    stop_ollama(sysm)
    sysm.sleep(2)
    ok = start_ollama(sysm)
    names = ollama_models(sysm) if ok else None
    model = ollama_conf()["model"]
    if names is None:
        log("AI engine: still not answering after the restart (see logs/ollama.log)")
        return False
    if not has_model(names, model):
        log(f"AI engine: running, but {model} is not in {ollama_conf()['models_dir']} - is the F: drive connected?")
        return False
    log("AI engine: back up")
    _guard_state_update(probe_fails=0)
    return True


def recent_ai_success(sysm: System = System) -> bool:
    """True if the crypto bot got a good answer from Qwen in the last 20 minutes (no need to test it again)."""
    st = sysm.crypto_state() or {}
    best = None
    for d in (st.get("last_decision"), (st.get("journal_brain") or {}).get("last_decision")):
        if isinstance(d, dict) and not d.get("missed") and d.get("at"):
            try:
                t = datetime.fromisoformat(d["at"])
                best = t if best is None or t > best else best
            except ValueError:
                pass
    return best is not None and (sysm.now() - best).total_seconds() < AI_RECENT_S


def _guard_state() -> Dict[str, Any]:
    try:
        return json.loads(GUARD_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guard_state_update(**kw: Any) -> None:
    s = _guard_state()
    s.update(kw)
    LOGS.mkdir(parents=True, exist_ok=True)
    GUARD_STATE.write_text(json.dumps(s), encoding="utf-8")


def check_ai(sysm: System = System) -> str:
    c = ollama_conf()
    names = ollama_models(sysm)
    if names is None:
        restart_ollama("not answering", sysm)
        return "restarted (not answering)"
    if not has_model(names, c["model"]):
        restart_ollama(f"running but can't find {c['model']} (wrong model folder)", sysm)
        return "restarted (model missing)"
    if recent_ai_success(sysm):
        _guard_state_update(probe_fails=0)
        return "ok (crypto bot got an answer recently)"
    busy, why = sysm.gaming()
    if busy:
        return f"not tested ({why})"
    ok, detail = ollama_answers(sysm)
    if ok:
        _guard_state_update(probe_fails=0)
        return f"ok ({detail})"
    fails = int(_guard_state().get("probe_fails", 0)) + 1
    _guard_state_update(probe_fails=fails)
    if fails >= PROBE_FAILS_TO_RESTART:
        restart_ollama(f"frozen: {detail}, {fails} checks in a row", sysm)
        return "restarted (frozen)"
    log(f"AI engine: {detail}; will restart it if the next check fails too")
    return f"slow ({detail})"


# ── the dashboard and the crypto bot ───────────────────────────────────────────────────────────────────────────────
def studio_health(sysm: System = System) -> Optional[Dict[str, Any]]:
    code, data = sysm.http(studio_url() + "/api/health", None, 8)
    return data if code == 200 and isinstance(data, dict) and data.get("ok") else None


def studio_ok(sysm: System = System) -> bool:
    return studio_health(sysm) is not None


def code_version() -> Optional[str]:
    """The STUDIO_VERSION in dashboard/server.py on disk (what a fresh start would run)."""
    import re
    try:
        m = re.search(r'^STUDIO_VERSION = "([^"]+)"', (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def port_owner_pids(port: int, sysm: System = System) -> List[str]:
    if not WIN:
        return []
    pids = []
    for line in sysm.run(["netstat", "-ano", "-p", "TCP"]).splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            pids.append(parts[4])
    return sorted(set(pids))


def stop_studio(sysm: System = System) -> None:
    port = int(settings().get("dashboard", {}).get("port", 8765))
    for pid in port_owner_pids(port, sysm):
        sysm.run(["taskkill", "/F", "/PID", pid])


def stop_python_jobs(sysm: System = System) -> None:
    """The crypto bot and the separate video watcher (matched by their command line)."""
    if WIN:
        sysm.run(["powershell", "-NoProfile", "-Command",
                  "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
                  "($_.CommandLine -like '*crypto_paper.runner*' -or $_.CommandLine -like '*studio.pipeline watch*') }"
                  " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"])
    else:
        sysm.run(["pkill", "-f", "crypto_paper.runner"])


def start_studio(sysm: System = System, wait_s: int = 20) -> bool:
    stop_studio(sysm)                           # a hung server still holds the port; clear it first
    sysm.spawn([python_exe(), str(ROOT / "dashboard" / "server.py")], "server.log", ollama_env())
    for _ in range(wait_s):
        sysm.sleep(1)
        if studio_ok(sysm):
            return True
    return False


def start_crypto(sysm: System = System) -> None:
    sysm.spawn([python_exe(), "-m", "crypto_paper.runner"], "crypto.log", ollama_env())


def crypto_running(sysm: System = System) -> bool:
    age = sysm.crypto_age_s()
    return age is not None and age < CRYPTO_STALE_S


# ── the three jobs ───────────────────────────────────────────────────────────────────────────────────────────────────
def start(sysm: System = System, browser: bool = False) -> bool:
    remember_model_folder(sysm)
    names = ollama_models(sysm)
    if names is None:
        log("starting the AI engine")
        if not start_ollama(sysm):
            restart_ollama("did not come up", sysm)
    elif not has_model(names, ollama_conf()["model"]):
        restart_ollama("running but can't find the model", sysm)
    if not studio_ok(sysm):
        log("starting the dashboard")
        if not start_studio(sysm):
            log("dashboard did not answer within 20 s (see logs/server.log)")
    if not crypto_running(sysm):
        log("starting the crypto paper bot")
        start_crypto(sysm)
    ok = studio_ok(sysm)
    if browser and ok and WIN:
        os.startfile(studio_url())           # type: ignore[attr-defined]
    return ok


def check(sysm: System = System) -> Dict[str, str]:
    remember_model_folder(sysm)               # cheap (one registry read); fixes the tray app's Ollama for next time
    out = {"ai": check_ai(sysm)}
    health = studio_health(sysm)
    on_disk = sysm.code_version()
    if health and on_disk and health.get("version") and health["version"] != on_disk:
        log(f"dashboard is running {health['version']} but {on_disk} is installed - restarting it into the new version")
        out["studio"] = "updated" if start_studio(sysm) else "failed (see logs/server.log)"
    elif health:
        out["studio"] = "ok"
    else:
        log("dashboard not answering - restarting it")
        out["studio"] = "restarted" if start_studio(sysm) else "failed (see logs/server.log)"
    if crypto_running(sysm):
        out["crypto"] = "ok"
    else:
        log("crypto paper bot not updating - starting it")
        start_crypto(sysm)
        out["crypto"] = "started"
    _guard_state_update(last_check=sysm.now().isoformat(timespec="seconds"), last_result=out)
    return out


def stop(sysm: System = System) -> None:
    log("stopping the dashboard, crypto bot, video watcher and AI engine")
    stop_studio(sysm)
    stop_python_jobs(sysm)
    stop_ollama(sysm)


def _single_instance() -> Any:
    """Only one guardian at a time (the 5-minute check and a manual restart could overlap)."""
    LOGS.mkdir(parents=True, exist_ok=True)
    fh = open(LOGS / "guardian.lock", "a+")
    try:
        if WIN:
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def main(argv: List[str]) -> int:
    cmd = argv[0] if argv else "check"
    lock = _single_instance()
    if lock is None:
        print("Another guardian is already working; leaving it to finish.")
        return 0
    try:
        rotate(LOGS / "watchdog.log")
        if cmd == "start":
            return 0 if start(browser="--browser" in argv) else 1
        if cmd == "stop":
            stop()
            return 0
        if cmd == "restart-ai":
            return 0 if restart_ollama("restart asked for") else 1
        result = check()
        if any(v != "ok" and not v.startswith("ok ") for v in result.values()):
            log("check: " + ", ".join(f"{k} {v}" for k, v in result.items()))
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
