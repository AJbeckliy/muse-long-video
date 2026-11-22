"""Loopback HTTP server for the Muse review studio."""

import argparse
import json
import mimetypes
import re
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from paths import WORKSPACE, AUDIO, DUB, HERE
from studio import Conflict, PlanError, ReviewError, Studio, exact_frame, part_at, pick_take

WEB = Path(__file__).resolve().parent / "web"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def reply(self, data, status=200, mime="application/json; charset=utf-8", cache="no-store"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; media-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def media(self, path):
        size = path.stat().st_size
        left, right = 0, size - 1
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d{0,16})-(\d{0,16})", requested)
            if match and match[1]:
                left = int(match[1])
                right = min(right, int(match[2])) if match[2] else right
            elif match and match[2]:
                left = max(0, size - int(match[2]))
            if not match or not (match[1] or match[2]) or left > right:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        if requested:
            self.send_header("Content-Range", f"bytes {left}-{right}/{size}")
        remaining = right - left + 1
        self.send_header("Content-Length", str(remaining))
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as source:
            source.seek(left)
            while remaining:
                chunk = source.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def body(self, limit=256_000):
        size = int(self.headers.get("Content-Length", 0))
        if not 0 < size <= limit:
            raise ReviewError("请求内容为空或超过大小限制。")
        return self.rfile.read(size)

    def json_body(self):
        if self.headers.get_content_type() != "application/json":
            raise ReviewError("请求格式有误。")
        data = json.loads(self.body())
        if not isinstance(data, dict):
            raise ReviewError("请求格式有误。")
        return data

    def get_route(self, route, params):
        studio = self.server.studio
        if route in ("/", "/app.js", "/sound.js", "/onboarding.js", "/style.css"):
            file = WEB / ("index.html" if route == "/" else route[1:])
            return self.reply(file.read_bytes(), mime=mimetypes.guess_type(file.name)[0] or "text/plain")
        if route == "/api/projects":
            return self.reply({**studio.summary(), "setup_available":(HERE.parent/"Configure-Starcanvas.cmd").is_file(), "token": self.server.token})
        if route in ("/api/starcanvas","/api/connection"):
            if studio.bridge is None:
                return self.reply({"ready": False, "message": "星幕连接尚未启用。"})
            return self.reply(studio.bridge.health())
        match = re.fullmatch(r"/api/projects/([a-z0-9-]+)(?:/(.*))?", route)
        if not match:
            raise FileNotFoundError
        project_id, action = match.groups()
        project = studio.load(project_id)
        dub_asset=re.fullmatch(r"dub-files/([0-9a-f]{16})",action or "")
        if dub_asset:
            return self.media(studio.projects/project_id/"对白轨"/dub_asset[1]/"配音版.mp4")
        audio_match = re.fullmatch(r"audio-files/([a-f0-9]{16})", action or "")
        if audio_match:
            return self.media(studio.temp / project_id / "audio" / (audio_match[1] + ".mp4"))
        if not action:
            return self.reply(studio.public(project))
        if action == "original" and project.get("original"):
            return self.media(Path(project["original"]))
        result = re.fullmatch(r"(outputs|seams)/([a-f0-9]{16})", action)
        if result:
            kind, file_id = result.groups()
            if kind == "seams":
                return self.media(studio.temp / project_id / f"接缝-{file_id}.mp4")
            for output in project["outputs"]:
                if output["id"] == file_id:
                    return self.media(Path(output["output"]))
            raise FileNotFoundError
        asset = re.fullmatch(r"segments/(\d+)/(opening|takes/([a-f0-9]{16})/(video|frame))", action)
        if asset:
            index, item, take_id, method = asset.groups()
            part = part_at(project, int(index))
            if item == "opening" and part["opening"]:
                return self.reply(Path(part["opening"]).read_bytes(), mime="image/png")
            take = pick_take(part, take_id)
            if method == "video":
                return self.media(Path(take["path"]))
            frame = int(params.get("index", [""])[0])
            small = params.get("size", [""])[0] == "thumb"
            return self.reply(exact_frame(take, frame, thumbnail=small), mime="image/jpeg" if small else "image/png",
                              cache="private, max-age=3600")
        raise FileNotFoundError

    def post_route(self, route, params):
        studio = self.server.studio
        if route == "/api/onboard-dismiss":
            self.json_body()
            studio.bridge.persist(sound_decided=True)
            return self.reply({"ok":True})
        if route == "/api/provider":
            data=self.json_body()
            sound=data.get("audio","")
            if sound not in ("","clean","dub"):raise ReviewError("声音模块选项无效。")
            result=studio.bridge.select(data)
            studio.bridge.persist(sound_decided=True)
            pair=result["provider"]=="starcanvas" and not studio.bridge.star.health()["ready"]
            setup=HERE.parent/"finish-setup.ps1"
            if setup.is_file() and (sound or pair):
                import os,subprocess
                powershell=Path(os.environ["SystemRoot"])/"System32/WindowsPowerShell/v1.0/powershell.exe"
                subprocess.Popen([str(powershell),"-NoProfile","-ExecutionPolicy","Bypass","-File",str(setup),
                    "-Sound",sound or "none","-Pairing",str(int(pair))],cwd=HERE.parent,creationflags=subprocess.CREATE_NEW_CONSOLE)
                result["message"]="基础工作台已就绪，请在打开的窗口完成所选配置。"
            return self.reply(result)
        if route == "/api/setup":
            import subprocess
            commands={"starcanvas":"Configure-Starcanvas.cmd","clean":"Install-Audio-Clean.cmd","dub":"Install-Audio-Dubbing.cmd"}
            name=commands.get(self.json_body().get("component"))
            if not name or not (HERE.parent/name).is_file(): raise ReviewError("该安装器不在本机程序目录。")
            subprocess.Popen(["cmd.exe","/d","/c",name],cwd=HERE.parent,creationflags=subprocess.CREATE_NEW_CONSOLE)
            return self.reply({"opened":True})
        upload = re.fullmatch(r"/api/projects/([a-z0-9-]+)/segments/(\d+)/import",route)
        if upload:
            from studio import new_id,inspect_take
            pid,index=upload[1],int(upload[2])
            revision=int(params.get("rev",[""])[0])
            count=int(self.headers.get("Content-Length",0))
            if not 0<count<=2*1024**3:
                raise ReviewError("请选择 2 GB 以内的 MP4。")
            project=studio.load(pid)
            part_at(project,index)
            path=studio.file(pid).parent/"imports"/(new_id()+".mp4")
            path.parent.mkdir(exist_ok=True)
            try:
                with path.open("xb") as dest:
                    while count:
                        chunk=self.rfile.read(min(count,1024**2))
                        if not chunk: raise ReviewError("文件传输中断。")
                        dest.write(chunk)
                        count-=len(chunk)
                take=inspect_take(path,"本地导入",normalize_timing=True)
                with studio.lock:
                    project=studio.load(pid)
                    studio.ensure_idle(project)
                    if project["rev"]!=revision: raise Conflict("项目已更新，请重新导入。")
                    part=part_at(project,index)
                    take["label"]+=f" · 版本 {len(part['takes'])+1}"
                    part["takes"].append(take)
                    studio.save(project)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return self.reply(studio.public(project))
        dub = re.fullmatch(r"/api/projects/([a-z0-9-]+)/dialogue-track",route)
        if dub:
            return self.reply(studio.set_dialogue(dub[1],self.json_body()))
        sound = re.fullmatch(r"/api/projects/([a-z0-9-]+)/(audio-process|voice-reference)", route)
        if sound:
            if not AUDIO: raise ReviewError("请先按需安装声音组件。")
            from audio_post import process, upload_reference
            if sound[2] == "voice-reference":
                return self.reply(upload_reference(studio, sound[1], self.body(32_000_000)))
            return self.reply(process(studio, sound[1], self.json_body()))
        if route == "/api/projects":
            data = self.json_body()
            return self.reply(studio.create(data.get("title"), data.get("prompts"), data.get("ratio")), status=201)
        match = re.fullmatch(r"/api/projects/([a-z0-9-]+)/(review|seam|segments/(\d+)/opening)", route)
        if not match:
            raise FileNotFoundError
        project_id, action, index = match.groups()
        if index is not None:
            revision = int(params.get("rev", [""])[0])
            return self.reply(studio.open_image(project_id, int(index), revision, self.body(12_000_000)))
        data = self.json_body()
        return self.reply(studio.seam(project_id, data) if action == "seam" else studio.mutate(project_id, data))

    def dispatch(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in allowed:
            return self.reply({"error": "请从本机地址打开审片台。"}, status=403)
        try:
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            if self.command == "POST":
                token = self.headers.get("X-Muse-Review", "")
                if self.headers.get("Origin") != f"http://{host}" or not secrets.compare_digest(token, self.server.token):
                    return self.reply({"error": "请从审片台本页操作。"}, status=403)
                return self.post_route(parsed.path, params)
            return self.get_route(parsed.path, params)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except FileNotFoundError:
            return self.reply({"error": "文件或项目找不到。"}, status=404)
        except Conflict as exc:
            return self.reply({"error": str(exc)}, status=409)
        except (ReviewError, PlanError, ValueError) as exc:
            return self.reply({"error": str(exc)}, status=400)
        except Exception as exc:
            print(f"Review request failed ({type(exc).__name__})", file=sys.stderr, flush=True)
            return self.reply({"error": "本次操作未完成。请确认素材可读取，或查看启动窗口。"}, status=500)

    do_GET = dispatch
    do_HEAD = dispatch
    do_POST = dispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--port", type=int, default=8786)
    parser.add_argument("--demo-plan", type=Path)
    parser.add_argument("--starcanvas", action="store_true")
    args = parser.parse_args()
    from services import Services
    bridge = Services(args.workspace.resolve(),args.starcanvas)
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.token = secrets.token_urlsafe(24)
        server.studio = Studio(args.workspace.resolve(), args.demo_plan, bridge)
        samples=HERE.parent/"samples"
        if samples.is_dir() and not server.studio.file("starter").exists():
            from studio import segment,inspect_take
            parts=[]
            for file in sorted(samples.glob("*.mp4")):
                part=segment()
                part["takes"]=[inspect_take(file,file.stem)]
                parts.append(part)
            if parts: server.studio.save(dict(id="starter",title="入门示例 · 两段素材",mode="demo",rev=0,segments=parts,outputs=[]))
        print(f"Muse review studio: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
