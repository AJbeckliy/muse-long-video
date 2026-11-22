"""Start or reopen the local Muse review studio on this computer."""

import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import os
import socket

HERE = Path(__file__).resolve().parent
from paths import WORKSPACE, PORT, SETTINGS, FILE
URL = f"http://127.0.0.1:{PORT}"
DEMO = Path(SETTINGS["demo_plan"]) if SETTINGS.get("demo_plan") else None


def listening():
    try:
        with urllib.request.urlopen(f"{URL}/api/projects", timeout=1) as response:
            data = json.load(response)
            if data.get("service")=="muse-review":
                return Path(data["workspace"])==WORKSPACE
            if SETTINGS.get("legacy_projects") and "starcanvas" in data:
                return any(item.get("id") in SETTINGS["legacy_projects"] for item in data.get("projects",[]))
            return False
    except (OSError, ValueError):
        return False


def main():
    global PORT, URL
    if not listening():
        try:
            with socket.create_connection(("127.0.0.1",PORT),timeout=.3):
                occupied=True
        except OSError:
            occupied=False
        if occupied:
            if "MUSE_STUDIO_PORT" in os.environ: raise SystemExit("指定端口已被占用。")
            with socket.socket() as listener:
                listener.bind(("127.0.0.1",0))
                PORT=listener.getsockname()[1]
            URL=f"http://127.0.0.1:{PORT}"
            SETTINGS["port"]=PORT
            pending=FILE.with_name("port-"+str(os.getpid())+".tmp")
            pending.write_text(json.dumps(SETTINGS,ensure_ascii=False,indent=2),encoding="utf8")
            pending.replace(FILE)
    if not listening():
        temp = WORKSPACE / "Temp" / "Muse审片台"
        temp.mkdir(parents=True, exist_ok=True)
        log = temp / "启动.log"
        runner = SETTINGS.get("audio_python") if SETTINGS.get("audio") else sys.executable
        command = [runner or sys.executable, "-B", str(HERE / "server.py"), "--port", str(PORT), "--workspace", str(WORKSPACE)]
        if SETTINGS.get('starcanvas',False):
            command.append('--starcanvas')
        if DEMO and DEMO.is_file():
            command.extend(["--demo-plan", str(DEMO)])
        with log.open("ab") as destination:
            env=dict(os.environ, PYTHONUTF8="1", MUSE_STUDIO_SETTINGS=str(FILE))
            process = subprocess.Popen(command, cwd=HERE, stdout=destination, stderr=destination, env=env,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(80):
            if listening():
                break
            if process.poll() is not None:
                raise SystemExit(f"审片台启动失败，查看 {log}")
            time.sleep(.2)
        else:
            raise SystemExit(f"审片台没有响应，查看 {log}")
    if "--no-browser" not in sys.argv[1:]:
        webbrowser.open(f"{URL}/")
    print(f"{URL}/")


if __name__ == "__main__":
    main()
