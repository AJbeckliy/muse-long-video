"""Use Starcanvas' installed, paired local connector. No browser-side credentials."""

from contextlib import AbstractContextManager
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import threading
import time

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from studio import LaunchRejected, ReviewError

MODEL = "muse-video-wd"
TERMINAL_FAILURES = {"error", "failed", "canceled", "cancelled"}


class WaitPending(ReviewError):
    """Starcanvas is still generating after the requested wait interval."""


class Connection(AbstractContextManager):
    def __enter__(self):
        from paths import HOME, location
        home = location("codex",HOME)
        try:
            data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8-sig"))
            config = data["mcp_servers"]["synmew-canvas"]
            exe = Path(config["command"])
            if not config.get("enabled", True) or exe.name.lower() != "synmewinfinitecanvas.exe" or not exe.is_file() or config.get("args") != ["--mcp-server"]:
                raise ValueError
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise ReviewError("本机没有可用的星幕画布连接配置。") from exc
        environment = os.environ.copy()
        environment.update(config.get("env", {}))
        self.process = subprocess.Popen([str(exe), "--mcp-server"], env=environment, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.messages = Queue()
        self.counter = 0
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        try:
            self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "Muse Review Studio", "version": "1.0"}})
            self.send({"method": "notifications/initialized", "params": {}})
            self.guide = self.rpc("resources/read", {"uri": "canvas://guide/workflow"})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, value, traceback):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=4)
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()

    def read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.messages.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def rpc(self, method, arguments, *, timeout=40):
        self.counter += 1
        request_id = self.counter
        self.send({"id": request_id, "method": method, "params": arguments})
        deadline = time.monotonic() + timeout
        while True:
            try:
                data = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except Empty as exc:
                raise ReviewError("星幕本机连接响应超时，请打开星幕并检查连接。") from exc
            if data is None:
                raise ReviewError("星幕本机连接已断开。")
            if data.get("id") != request_id:
                continue
            if "error" in data:
                raise ReviewError(f"星幕未接受 {method}，请检查连接或应用状态。")
            return data["result"]

    def call(self, tool_name, **arguments):
        envelope = self.rpc("tools/call", {"name": tool_name, "arguments": arguments})
        payload = envelope.get("structuredContent")
        if not isinstance(payload, dict):
            for item in envelope.get("content", []):
                if item.get("type") != "text":
                    continue
                try:
                    payload = json.loads(item["text"])
                    break
                except ValueError:
                    continue
        if envelope.get("isError") or not isinstance(payload, dict) or payload.get("ok") is False:
            issue = payload.get("error") if isinstance(payload, dict) else None
            code = issue.get("code") if isinstance(issue, dict) else None
            if tool_name == "result_wait_card" and code == "WAIT_TIMEOUT" and issue.get("retryable") is True:
                raise WaitPending("星幕仍在生成。")
            if isinstance(code, str) and code.lower() == "confirmation_required":
                raise LaunchRejected("星幕要求额外确认。请先在星幕端处理确认，再回到审片台。")
            raise ReviewError(f"星幕未完成 {tool_name}，请检查画布和账号状态。")
        return payload


class Starcanvas:
    def __init__(self):
        self.lock = threading.Lock()

    def health(self):
        try:
            with Connection() as connection:
                connection.call("workspace_get_context")
                model = connection.call("model_get_capabilities", modelId=MODEL)["data"]
                if not model.get("accountAvailable") or "video" not in model.get("kinds", []):
                    return {"ready": False, "message": "星幕已连接，当前账号未显示 Muse 视频模型可用。"}
                return {"ready": True, "message": "星幕本机连接正常，Muse 模型可查询。", "model": MODEL}
        except (OSError, KeyError, ReviewError):
            return {"ready": False, "message": "未连接星幕。请打开已配对的星幕画布后，再点这里检查。"}

    def prepare(self, connection, job, update, title):
        context = connection.call("workspace_get_context")["data"]
        if context["viewMode"] != "result":
            connection.call("workspace_set_view_mode", mode="result")
            connection.call("workspace_get_context")
        available = connection.call("model_get_capabilities", modelId=MODEL)["data"]
        if not available.get("accountAvailable"):
            raise LaunchRejected("当前星幕账号未显示 Muse 模型可用，请在星幕确认账号状态。")
        remote_project = job.get("remote_project")
        if not remote_project:
            created = connection.call("project_create", kind="result", name=job["project_title"])["data"]
            remote_project = created.get("projectId") or created.get("id") or created.get("project", {}).get("id")
            if not isinstance(remote_project, str) or not remote_project:
                raise LaunchRejected("星幕没有返回新项目编号。")
            update(remote_project=remote_project)
        kinds = connection.call("result_list_card_types", projectId=remote_project)["data"]["cardTypes"]
        video = next((card for card in kinds if card.get("kind") == "video"), {})
        if MODEL not in video.get("models", []):
            raise LaunchRejected("这个星幕项目未列出 Muse 视频模型。")

        y = 340 * job["attempt_index"]
        card = {"clientRef": "generate", "kind": "video", "role": "generate", "x": 430, "y": y,
                "data": {"title": title, "model": MODEL, "prompt": job["prompt"], "aspectRatio": job["ratio"],
                         "resolution": "720p", "duration": str(job["duration"])}}
        reference = Path(job["reference"]) if job.get("reference") else None
        cards = [card]
        if reference:
            if not reference.is_file():
                raise LaunchRejected("选中的参考帧找不到，请回到审片台重新选帧。")
            cards.insert(0, {"clientRef": "reference", "kind": "image", "role": "input", "x": 70, "y": y,
                             "data": {"title": f"{title} · 参考图"}})
        connection.call("result_create_cards", projectId=remote_project, cards=cards, dryRun=True)
        result = connection.call("result_create_cards", projectId=remote_project, cards=cards)["data"]
        identifiers = result.get("idsByRef") or result.get("idMap") or result.get("clientRefMap") or result.get("cardIds")
        if isinstance(identifiers, list):
            identifiers = dict(zip((item["clientRef"] for item in cards), identifiers))
        if not isinstance(identifiers, dict):
            raise LaunchRejected("星幕没有返回生成卡编号。")
        card_id = identifiers.get("generate")
        if not card_id:
            raise LaunchRejected("星幕没有返回 Muse 生成卡编号。")
        update(card=card_id)
        expected_inputs = []
        if reference:
            image_id = identifiers.get("reference")
            if not image_id:
                raise LaunchRejected("星幕没有返回参考图卡编号。")
            attach = {"projectId": remote_project, "cardId": image_id, "paths": [str(reference)], "kind": "image", "replace": True}
            connection.call("result_attach_local_images", **attach, dryRun=True)
            receipt = connection.call("result_attach_local_images", **attach)["data"]
            if receipt.get("total") != 1 or receipt.get("fileNames") != [reference.name]:
                raise LaunchRejected("星幕返回的参考图与选中的帧不一致。")
            links = [{"fromId": image_id, "toId": card_id}]
            expected_inputs = [image_id]
            connection.call("result_connect_cards", projectId=remote_project, links=links, dryRun=True)
            connection.call("result_connect_cards", projectId=remote_project, links=links)
        details = connection.call("result_get_card", projectId=remote_project, cardId=card_id)["data"]
        incoming = details.get("incoming", [])
        if details.get("card", {}).get("model") != MODEL or [link.get("fromId") for link in incoming] != expected_inputs:
            raise LaunchRejected("预检发现模型或参考图连接与审片台的选择不符。")
        checked = connection.call("run_preflight", projectId=remote_project, cardId=card_id, goal="save")["data"]
        if checked.get("blocked") is not False or any(issue.get("severity") == "error" for issue in checked.get("issues", [])):
            raise LaunchRejected("星幕预检未通过，请打开该生成卡查看原因。")
        return remote_project, card_id

    def run(self, job, update, *, resume, title):
        if not self.lock.acquire(blocking=False):
            raise ReviewError("另一个项目正在使用星幕，请等它完成再提交。")
        try:
            with Connection() as connection:
                if resume:
                    connection.call("workspace_get_context")
                    remote_project, card = job["remote_project"], job["card"]
                else:
                    remote_project, card = self.prepare(connection, job, update, title)
                    update(status="submitting", message="正在提交本次 Muse 生成…")
                    reply = connection.call("result_run_card", projectId=remote_project, cardId=card, goal="save")["data"]
                    if str(reply.get("status", "")).lower() in TERMINAL_FAILURES:
                        raise LaunchRejected("星幕报告生成失败，可以回到本段检查提示词后重新发起。")
                    update(status="running", message="星幕正在生成，完成后会回到这里。")
                return self.collect(connection, remote_project, card)
        finally:
            self.lock.release()

    def collect(self, connection, project_id, card):
        deadline = time.monotonic() + 25 * 60
        while time.monotonic() < deadline:
            try:
                status = connection.call("result_wait_card", projectId=project_id, cardId=card, timeoutMs=25000)["data"]
            except WaitPending:
                continue
            name = str(status.get("status", "")).lower()
            if name in TERMINAL_FAILURES:
                raise LaunchRejected("星幕报告本段生成失败或已取消。")
            if name == "done" and status.get("hasMedia"):
                local = status.get("resultPath")
                if isinstance(local, str) and Path(local).is_absolute() and Path(local).is_file():
                    return Path(local)
                raise ReviewError("星幕报告已生成，但本机暂未找到可读取的视频。请检查星幕输出目录，再查询原任务。")
            if name not in {"queued", "running", "pending", "waiting", "processing", "generating"}:
                raise ReviewError("星幕未返回已生成的视频，请核对原任务。")
            time.sleep(1)
        raise ReviewError("星幕仍未回传视频，可以查询原任务继续收集。")
