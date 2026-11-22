"""Local Muse review workspace and frame-accurate editing."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import av
from PIL import Image

from paths import SKILL, AUDIO, DUB
sys.path.insert(0, str(SKILL / "scripts"))
from edit_video import PlanError, render, validate


class ReviewError(ValueError):
    pass


class Conflict(ReviewError):
    pass


class LaunchRejected(ReviewError):
    pass


def new_id():
    return uuid4().hex[:16]


def read_json(path):
    for attempt in range(6):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            if attempt==5: raise
            time.sleep(.025*(attempt+1))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f"{path.name}.{new_id()}.tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(6):
        try:
            os.replace(pending, path)
            break
        except PermissionError:
            if attempt==5: raise
            time.sleep(.025*(attempt+1))


def text_field(value, limit, label):
    if not isinstance(value, str) or len(value) > limit:
        raise ReviewError(f"{label}过长或格式有误。")
    return value.strip()


def inspect_take(path, label, *, windows=None, bounds=None, job=None, normalize_timing=False):
    from media_timing import is_mp4
    if not is_mp4(path):
        raise ReviewError("请选择实际格式为 MP4 的视频文件。")
    with av.open(str(path),format="mov",options={"protocol_whitelist":"file,pipe","enable_drefs":"0"}) as media:
        if not media.streams.video:
            raise ReviewError("所选文件没有可用的视频画面。")
        video = media.streams.video[0]
        rate = video.average_rate
        if not rate or not media.streams.audio:
            raise ReviewError("片段需要有固定帧率的视频和音轨。")
        first_pts = previous_pts = None
        frame_count = 0
        for frame in media.decode(video):
            if frame.pts is None or frame.time_base is None:
                raise ReviewError("视频缺少可用于逐帧裁剪的时间信息。")
            timestamp = frame.pts * frame.time_base
            if first_pts is None:
                first_pts = timestamp
            if previous_pts is not None and abs(timestamp - previous_pts - 1 / rate) > frame.time_base:
                raise ReviewError("当前片段是可变帧率，需转换成固定帧率后再使用。")
            previous_pts = timestamp
            frame_count += 1
        if not frame_count:
            raise ReviewError("视频里没有可播放的画面。")
        audio = media.streams.audio[0]
        if audio.start_time is None or audio.time_base is None or audio.duration is None:
            raise ReviewError("片段缺少音轨时间信息，请先转为音画起点为零的 MP4。")
        audio_start = audio.start_time * audio.time_base
        duration = frame_count / Fraction(rate)
        timing_fix = (abs(first_pts) > video.time_base or abs(audio_start-first_pts) > Fraction(1,1000)
                      or audio.duration * audio.time_base + Fraction(1,100) < duration)
        take = {
            "id": new_id(), "label": label, "path": str(path), "fps": str(rate),
            "frames": frame_count, "width": video.width, "height": video.height,
            "windows": windows or [], "bounds": bounds or [0, frame_count - 1],
        }
        if job:
            take["job"] = job
    if timing_fix:
        if not normalize_timing:
            raise ReviewError("片段需要规范化音轨时间，请从「导入本段本机视频」重新导入。")
        import subprocess
        from media_timing import normalize
        try:
            normalize(path, first_pts, audio_start, duration, frame_count)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise ReviewError("无法保持原始音画时差，请先转为固定帧率、音画起点为零的 MP4。") from exc
    return take


def segment(prompt=""):
    return {"prompt": prompt, "duration": 10, "takes": [], "approval": None, "review": "", "opening": None, "job": None}


def pick_take(part, take_id):
    for candidate in part["takes"]:
        if candidate["id"] == take_id:
            return candidate
    raise ReviewError("找不到这个版本，请刷新后再试。")


def part_at(project, index):
    if type(index) is not int or not 0 <= index < len(project["segments"]):
        raise ReviewError("找不到这段视频。")
    return project["segments"][index]


def review_bounds(take, first, last):
    if type(first) is not int or type(last) is not int or not 0 <= first <= last < take["frames"]:
        raise ReviewError("请选有效的入点和结束帧。")
    return first, last


def clip(take, first, last, *, dialogue=True):
    return {
        "id": take["id"], "path": take.get("dub_path") or take["path"], "source_fps": take["fps"],
        "source_frames": take["frames"], "in_frame": first, "out_frame": last + 1,
        "dialogue_windows": take["windows"] if dialogue else [],
    }


def exact_frame(take, index, *, thumbnail=False):
    review_bounds(take, index, index)
    with av.open(take["path"]) as media:
        for position, frame in enumerate(media.decode(video=0)):
            if position == index:
                picture = frame.to_image()
                break
        else:
            raise ReviewError("无法解码这帧。")
    if thumbnail:
        picture.thumbnail((192, 192), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG" if thumbnail else "PNG", quality=83)
    return buffer.getvalue()


class Studio:
    ACTIVE = {"queued", "preparing", "submitting", "running"}

    def set_dialogue(self, pid, data):
        with self.lock:
            p = self.load(pid)
            self.ensure_idle(p)
            if p["rev"] != data.get("rev"):
                raise Conflict("项目已更新，请刷新。")
        if "ref" not in data:
            raise ReviewError("请选择参考音色，或明确恢复原对白。")
        ref = data["ref"]
        if ref is not None:
            if not DUB:
                raise ReviewError("请先安装对白重配组件。")
            from dialogue_dub import prepare
        if ref is not None and (not isinstance(ref,str) or not re.fullmatch("[a-f0-9]{16}",ref) or not (self.temp/pid/"audio"/f"ref-{ref}.wav").is_file()):
            raise ReviewError("请选择有效的参考人声。")
        for part in p["segments"]:
            for t in part["takes"]:
                t.pop("dub_path",None)
            if ref and part["takes"]:
                t = pick_take(part,part["approval"]["take"]) if part["approval"] else part["takes"][-1]
                t["dub_path"] = prepare(self,pid,part,t,ref)
        with self.lock:
            if self.load(pid)["rev"] != p["rev"]:
                raise Conflict("项目在配音期间发生变化，请重新应用。")
            p["dub_ref"] = ref
            self.save(p)
        return self.public(p)

    def __init__(self, workspace, demo_plan=None, bridge=None):
        self.projects = workspace / "Projects" / "Muse审片台"
        self.temp = workspace / "Temp" / "Muse审片台"
        self.outputs = workspace / "Outputs" / "Muse审片台"
        self.bridge = bridge
        self.lock = threading.RLock()
        self.rendering = set()
        self.projects.mkdir(parents=True, exist_ok=True)
        self.recover_jobs()
        if demo_plan:
            self.seed_demo(demo_plan)

    def file(self, project_id):
        if not re.fullmatch(r"[a-z0-9-]{1,48}", project_id):
            raise ReviewError("找不到这个项目。")
        return self.projects / project_id / "project.json"

    def load(self, project_id):
        with self.lock:
            return read_json(self.file(project_id))

    def save(self, project):
        project["rev"] += 1
        write_json(self.file(project["id"]), project)

    def recover_jobs(self):
        for path in self.projects.glob("*/project.json"):
            project = read_json(path)
            changed = False
            for part in project["segments"]:
                job = part["job"]
                if job and job["status"] in self.ACTIVE:
                    job["status"] = "unknown" if job["status"] in {"submitting", "running"} else "failed"
                    job["message"] = "页面已重启。请查询原任务。" if job["status"] == "unknown" else "上次在提交前中断，可以手动重新发起。"
                    changed = True
            if changed:
                self.save(project)

    def seed_demo(self, plan_path):
        path = self.file("demo")
        if path.exists():
            return
        plan = read_json(plan_path)
        old = [Path(c["path"]) for c in plan["clips"]]
        first = inspect_take(old[0], "原始拍摄段", bounds=[0, 132])
        second = inspect_take(old[1], "中景接续版 · 15.5 秒原片", bounds=[1, 239], windows=plan["clips"][1]["dialogue_windows"])
        alternate = inspect_take(old[1].with_name("part2.mp4"), "正脸接续 · 历史候选", windows=[[7.34, 8.68]])
        parts = [segment(), segment()]
        parts[0]["takes"] = [first]
        parts[1]["takes"] = [second, alternate]
        parts[1]["review"] = "先确认第 1 段的接点。"
        self.save({"id": "demo", "title": "找钥匙 · 15.5 秒实片", "mode": "demo", "rev": 0,
                   "segments": parts, "outputs": [], "original": plan["output"]})

    def summary(self):
        with self.lock:
            projects = [read_json(path) for path in self.projects.glob("*/project.json")]
        cap=self.bridge.info() if hasattr(self.bridge,"info") else {"provider":"starcanvas" if self.bridge else "local","can_generate":bool(self.bridge),"sound_question":False}
        configured = cap["provider"]=="starcanvas"
        return {**cap,"service":"muse-review","workspace":str(self.projects.parent.parent),"audio":AUDIO,"dub":DUB,"starcanvas": configured, "projects": [
            {k: p[k] for k in ("id", "title", "mode")} for p in sorted(projects, key=lambda p: (p["mode"] != "demo", p["title"]))
        ]}

    def public(self, project):
        result = copy.deepcopy(project)
        cfg=getattr(self.bridge,"config",{})
        result["requires_rebind"]=bool(getattr(self.bridge,"kind",None)=="api" and project.get("api_binding") and project["api_binding"]!=cfg.get("api_binding"))
        result["original"] = bool(result.get("original"))
        for part in result["segments"]:
            part["opening"] = bool(part["opening"])
            for take in part["takes"]:
                take.pop("path")
                take.pop("job", None)
            if part["approval"]:
                part["approval"].pop("reference", None)
            if part["job"]:
                job=part["job"]
                missing=bool(job["status"]=="unknown" and hasattr(self.bridge,"missing_receipt") and self.bridge.missing_receipt(job))
                part["job"] = {**{k:job.get(k) for k in ("status", "message", "card")},"missing_receipt":missing}
        return result

    def create(self, title, prompts, ratio):
        title = text_field(title, 80, "项目名称")
        if not title or not isinstance(prompts, list) or not 1 <= len(prompts) <= 12:
            raise ReviewError("请填项目名，并规划 1–12 段。")
        if ratio not in {"9:16", "16:9"}:
            raise ReviewError("请选择横屏或竖屏。")
        prompts = [text_field(p, 16000, "分段提示词") for p in prompts]
        project = {"id": new_id(), "title": title, "mode": getattr(self.bridge,"kind","starcanvas"), "rev": 0,
                   "ratio": ratio, "segments": [segment(p) for p in prompts], "outputs": []}
        with self.lock:
            self.save(project)
        return self.public(project)

    def ensure_idle(self, project):
        if project["id"] in self.rendering:
            raise Conflict("成片正在合成，请稍等。")
        if any(p["job"] and p["job"]["status"] in self.ACTIVE for p in project["segments"]):
            raise Conflict("这个项目还有一段在生成，请等它结束。")

    def ensure_previous(self, project, index):
        if any(not p["approval"] or p["review"] for p in project["segments"][:index]):
            raise ReviewError("请先确认前面的片段并复查标记的接缝。")

    def open_image(self, project_id, index, revision, data):
        try:
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG", "WEBP"]) as picture:
                if picture.width * picture.height > 16_000_000:
                    raise ReviewError("图片太大，请缩小到 1600 万像素以内。")
                from PIL import ImageOps
                picture = ImageOps.exif_transpose(picture).convert("RGB")
                buffer = io.BytesIO()
                picture.save(buffer, "PNG")
        except (OSError, Image.DecompressionBombError) as exc:
            raise ReviewError("请上传 PNG、JPEG 或 WebP 图片。") from exc
        with self.lock:
            project = self.load(project_id)
            if project["rev"] != revision:
                raise Conflict("项目有新变化，请刷新后再试。")
            self.ensure_idle(project)
            part = part_at(project, index)
            path = self.projects / project_id / "references" / f"opening-{new_id()}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(buffer.getvalue())
            part["opening"] = str(path)
            self.save(project)
            return self.public(project)

    def approval_for(self, project, index, part, data):
        take = pick_take(part, data.get("take"))
        first, last = review_bounds(take, data.get("first"), data.get("last"))
        mode = data.get("mode")
        if mode not in {"continue", "cut", "end"} or (mode == "end") != (index == len(project["segments"]) - 1):
            raise ReviewError("请选择接下一段的方式。")
        rate = Fraction(take["fps"])
        for left, right in take["windows"]:
            if Fraction(str(left)) < first / rate or Fraction(str(right)) > (last + 1) / rate:
                raise ReviewError(f"该范围会截掉已标记的对白（{left}–{right} 秒）。请调整裁剪点。")
        approval = {"take": take["id"], "first": first, "last": last, "mode": mode, "reference": None}
        if mode == "continue":
            payload = exact_frame(take, last)
            digest = hashlib.sha256(payload).hexdigest()
            path = self.projects / project["id"] / "references" / f"{digest}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(payload)
            approval["reference"] = str(path)
        return approval

    def apply_approval(self, project, index, part, approval):
        previous = part["approval"]
        part["approval"] = approval
        part["review"] = ""
        if index + 1 >= len(project["segments"]):
            return
        following = project["segments"][index + 1]
        keys = ("take", "last", "mode")
        if following["takes"] and (not previous or any(previous[key] != approval[key] for key in keys)):
            following["review"] = "上游接点已确认，请连播检查接缝，再决定保留现有版本或重跑。"

    def prepare_job(self, project, index, *, confirmed, selection=None):
        part = part_at(project, index)
        self.ensure_previous(project, index)
        choice=self.bridge.info() if hasattr(self.bridge,"info") else {}
        provider=choice.get("provider",getattr(self.bridge,"kind","starcanvas"))
        binding=choice.get("selection") if provider=="api" else None
        if selection is not None and selection!=(binding if provider=="api" else provider):
            raise Conflict("生成通道或 API 配置已在其他窗口更改，请刷新后重新确认。")
        if project["mode"] not in ("demo",) and not any(p["job"] for p in project["segments"]):
            project["mode"]=provider
        if project["mode"] != provider or provider not in ("api","starcanvas") or self.bridge is None:
            raise ReviewError("请先配置本项目对应的生成通道。")
        if provider=="api" and project.get("api_binding") and project["api_binding"]!=binding:
            raise ReviewError("此项目绑定的 API 与当前设置不同。请先确认更换本项目的 API。")
        if not confirmed:
            raise ReviewError("请先确认本次视频生成。")
        if any(p["job"] and p["job"]["status"] == "unknown" for p in project["segments"]):
            raise ReviewError("项目中有一笔提交状态未确认，请先查询原任务。")
        if not part["prompt"]:
            raise ReviewError("请先填写并保存这一段的提示词。")
        previous = project["segments"][index - 1]["approval"] if index else None
        reference = previous["reference"] if previous and previous["mode"] == "continue" else part["opening"]
        attempt_index = project.get("attempt_count", 0)
        project["attempt_count"] = attempt_index + 1
        job = {"id": new_id(), "status": "queued", "message": "等待星幕预检…", "card": None,
               "prompt": part["prompt"], "reference": reference, "predecessor": previous,
               "ratio": project.get("ratio", "9:16"), "duration": part.get("duration", 10), "attempt_index": attempt_index,
               "remote_project": project.get("remote_project"),
               "project_title": f"Muse 审片台 · {project['title'][:48]} · {project['id'][:6]}"}
        job["backend"]=provider
        if provider=="api":
            project.setdefault("api_binding",binding)
            job["api_binding"]=project["api_binding"]
            job["message"]="等待 API 提交…"
        part["job"] = job
        return job["id"]

    def mutate(self, project_id, data):
        job_to_start = None
        output = None
        dub_path = None
        if data.get("action") == "approve":
            snapshot = self.load(project_id)
            if snapshot.get("dub_ref") and snapshot["rev"] == data.get("rev"):
                if not DUB:
                    raise ReviewError("此项目启用了对白重配。请在「项目对白重配」恢复原对白，或安装重配组件后继续。")
                from dialogue_dub import prepare
                current = part_at(snapshot,data.get("index"))
                dub_path = prepare(self,project_id,current,pick_take(current,data.get("take")),snapshot["dub_ref"])
        with self.lock:
            project = self.load(project_id)
            if type(data.get("rev")) is not int or data["rev"] != project["rev"]:
                raise Conflict("项目有新变化，请刷新后再试。")
            index = data.get("index")
            part = part_at(project, index)
            action = data.get("action")
            self.ensure_idle(project)
            if action == "save-prompt":
                part["prompt"] = text_field(data.get("prompt"), 16000, "提示词")
                duration = data.get("duration", part.get("duration", 10))
                if type(duration) is not int or not 2 <= duration <= 10:
                    raise ReviewError("单段目标时长请选择 2–10 秒。")
                part["duration"] = duration
            elif action == "clear-opening":
                part["opening"] = None
            elif action == "generate":
                job_id = self.prepare_job(project, index, confirmed=data.get("confirmed") is True, selection=data.get("selection"))
                job_to_start = (index, job_id, False)
            elif action == "check-job":
                job = part["job"]
                if not job or job["status"] != "unknown" or not job["card"] or self.bridge is None:
                    raise ReviewError("没有可查询的原任务。")
                job["status"] = "running"
                job_to_start = (index, job["id"], True)
            elif action == "rebind-api":
                if data.get("confirmed") is not True or project["mode"]!="api" or getattr(self.bridge,"kind",None)!="api":
                    raise ReviewError("请确认更换本项目的 API 配置。")
                if any(p["job"] and p["job"]["status"]=="unknown" for p in project["segments"]):
                    raise ReviewError("请先核对项目中的未确认提交。")
                project["api_binding"]=self.bridge.config["api_binding"]
            elif action in ("restore-receipt","confirm-not-submitted"):
                job=part["job"]
                if not job or job["status"]!="unknown" or not hasattr(self.bridge,"missing_receipt") or not self.bridge.missing_receipt(job):
                    raise ReviewError("这个任务不需要手动核对。")
                if data.get("confirmed") is not True:
                    raise ReviewError("请先核对供应商记录。")
                if action=="restore-receipt":
                    remote=data.get("task_id")
                    self.bridge.restore_receipt(job,remote)
                    job.update(status="running",card=remote,message="查询已核对的原任务…")
                    job_to_start=(index,job["id"],True)
                else:
                    job.update(status="failed",message="用户已核对供应商记录，确认该次请求未被受理。")
            elif action == "approve":
                self.ensure_previous(project, index)
                if dub_path:
                    pick_take(part,data.get("take"))["dub_path"] = dub_path
                approval = self.approval_for(project, index, part, data)
                self.apply_approval(project, index, part, approval)
                if approval["mode"] == "end":
                    output = self.reserve_output(project)
                elif data.get("confirmed") is True:
                    following = project["segments"][index + 1]
                    if following["takes"]:
                        raise ReviewError("下一段已有素材，请先查看接缝。")
                    job_id = self.prepare_job(project, index + 1, confirmed=True, selection=data.get("selection"))
                    job_to_start = (index + 1, job_id, False)
            else:
                raise ReviewError("没有这个操作。")
            self.save(project)
            if output:
                self.rendering.add(project_id)
        if job_to_start:
            threading.Thread(target=self.run_job, args=(project_id, *job_to_start), daemon=True).start()
        if output:
            try:
                self.render_output(project_id, *output)
            finally:
                with self.lock:
                    self.rendering.remove(project_id)
            with self.lock:
                project = self.load(project_id)
        return self.public(project)

    def make_plan(self, clips, base_take, destination):
        total = sum(Fraction(c["out_frame"] - c["in_frame"], 1) / Fraction(c["source_fps"]) for c in clips)
        return {"version": 1, "target_seconds": str(total), "width": base_take["width"],
                "height": base_take["height"], "fps": base_take["fps"], "clips": clips, "output": str(destination)}

    def reserve_output(self, project):
        takes = [pick_take(p, p["approval"]["take"]) for p in project["segments"]]
        clips = [clip(t, p["approval"]["first"], p["approval"]["last"]) for t, p in zip(takes, project["segments"])]
        output_id = new_id()
        destination = self.outputs / project["id"] / f"成片-{output_id}.mp4"
        plan = self.make_plan(clips, takes[0], destination)
        if project.get("dub_ref"):
            plan["dialogue_reference"] = project["dub_ref"]
        validate(plan)
        return output_id, plan, project["rev"] + 1

    def render_output(self, project_id, output_id, plan, source_revision):
        destination = self.outputs / project_id / f"剪辑记录-{output_id}.json"
        write_json(destination, plan)
        result = render(plan)
        if plan.get("dialogue_reference"):
            result["audio_label"] = "参考音色重配 · 时间轴对齐"
        with self.lock:
            project = self.load(project_id)
            project["outputs"].append({"id": output_id, "source_rev": source_revision, **result})
            self.save(project)

    def seam(self, project_id, data):
        with self.lock:
            project = self.load(project_id)
            index = data.get("index")
            if type(index) is not int or index < 1:
                raise ReviewError("第 1 段前面还没有片段。")
            prev = part_at(project, index - 1)
            approved = prev["approval"]
            if not approved:
                raise ReviewError("请先确认上一段的接点。")
            previous = pick_take(prev, approved["take"])
            current = pick_take(part_at(project, index), data.get("take"))
        first, last = review_bounds(current, data.get("first"), data.get("last"))
        if project.get("dub_ref"):
            if not DUB:
                raise ReviewError("此项目启用了对白重配。请先恢复原对白，或安装重配组件后连播。")
            from dialogue_dub import prepare
            current["dub_path"] = prepare(self, project_id, project["segments"][index], current, project["dub_ref"])
        prev_last = approved["last"]
        prev_first = max(approved["first"], prev_last + 1 - int(Fraction(previous["fps"]) * 2))
        end = min(last, first + int(Fraction(current["fps"]) * 2) - 1)
        preview_clips = [clip(previous, prev_first, prev_last, dialogue=False), clip(current, first, end, dialogue=False)]
        preview_id = new_id()
        path = self.temp / project_id / f"接缝-{preview_id}.mp4"
        result = render(self.make_plan(preview_clips, previous, path))
        return {"id": preview_id, "seconds": result["seconds"]}

    def job_update(self, project_id, index, job_id, **changes):
        with self.lock:
            project = self.load(project_id)
            part = part_at(project, index)
            job = part["job"]
            if not job or job["id"] != job_id:
                raise Conflict("原任务记录有变化。")
            job.update(changes)
            if changes.get("remote_project"):
                project["remote_project"] = changes["remote_project"]
            self.save(project)
            return copy.deepcopy(job)

    def run_job(self, project_id, index, job_id, resume):
        update = lambda **changes: self.job_update(project_id, index, job_id, **changes)
        try:
            job = update(status="running" if resume else "preparing", message="查询原任务…" if resume else "检查生成服务与参考图…")
            source = self.bridge.run(job, update, resume=resume, title=f"审片台 {project_id} 第 {index + 1} 段")
            attempt_dir = self.projects / project_id / "takes" / job_id
            attempt_dir.mkdir(parents=True, exist_ok=True)
            destination = attempt_dir / "source.mp4"
            silent=False
            if job.get("backend")=="api":
                # Older versions may already have collected a silent artifact.
                from media_timing import is_mp4
                check_file=destination if destination.exists() else source
                if not is_mp4(check_file):raise ReviewError("API 结果未通过 MP4 文件检查。")
                with av.open(str(check_file),format="mov",options={"enable_drefs":"0","protocol_whitelist":"file,pipe"}) as media:
                    silent=not media.streams.audio
            if silent or not destination.exists():
                import shutil
                pending = attempt_dir / f"incoming-{new_id()}.mp4"
                if silent:
                    import subprocess
                    from edit_video import find_ffmpeg
                    subprocess.run([
                        find_ffmpeg(),"-nostdin","-n","-v","error","-protocol_whitelist","file,pipe",
                        "-f","mov","-enable_drefs","0","-i",str(source),
                        "-f","lavfi","-i","anullsrc=r=48000:cl=stereo","-map","0:v:0",
                        "-map","1:a:0","-c:v","copy","-c:a","aac","-shortest",str(pending)
                    ],check=True,capture_output=True)
                else:
                    shutil.copyfile(source, pending)
                os.replace(pending, destination)
            take = inspect_take(destination, "自带 API" if job.get("backend")=="api" else "星幕 Muse", job=job_id,normalize_timing=True)
            with self.lock:
                project = self.load(project_id)
                part = part_at(project, index)
                take["label"] += f" · 版本 {len(part['takes']) + 1}"
                part["takes"].append(take)
                part["job"].update(status="done", message="新版本已回传，可以审片。")
                self.save(project)
        except LaunchRejected as exc:
            update(status="failed", message=str(exc))
        except Exception as exc:
            job = update()
            status = "unknown" if job["status"] in {"submitting", "running"} else "failed"
            message = str(exc) if isinstance(exc, ReviewError) else "未能收集结果，请检查生成服务后查询原任务。"
            update(status=status, message=message)
