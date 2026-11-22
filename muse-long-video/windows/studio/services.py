"""User-selected video services. Keys stay encrypted for the current Windows user."""
import base64
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from paths import FILE, SETTINGS, SKILL
from studio import LaunchRejected, ReviewError, write_json
from starcanvas import Starcanvas
from api_attempt import rejected_http
from settings_io import merge_settings
import video_api as adapter


class Blob(ctypes.Structure):
    _fields_=[("size",ctypes.c_uint32),("ptr",ctypes.c_void_p)]


def protect(data, opening=False):
    buf=ctypes.create_string_buffer(data)
    inp=Blob(len(data),ctypes.cast(buf,ctypes.c_void_p))
    out=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if opening else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(inp),None,None,None,None,1,ctypes.byref(out)):
        raise ReviewError("Windows 用户密钥保护失败。请使用配置该 API 的 Windows 账号。")
    try: return ctypes.string_at(out.ptr,out.size)
    finally: ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(out.ptr))


class Services:
    def __init__(self,work,star=False,transport=adapter.http):
        self.config=dict(SETTINGS)
        self.kind=self.config.get("provider") or ("starcanvas" if star else "local")
        self.store=work/"Projects"/".muse-providers"
        binding=self.config.get("api_binding")
        if self.kind=="api" and (not isinstance(binding,str) or not re.fullmatch("[a-f0-9]{32}",binding) or not (self.store/(binding+".bin")).is_file()):
            self.kind="local"
            self.config["provider"]="local"
            self.config.pop("api_binding",None)
            self.config["sound_decided"]=False
        self.star=Starcanvas()
        self.transport=transport
        self.lock=threading.RLock()

    def info(self):
        with self.lock:
            return {"provider":self.kind,"selection":self.config.get("api_binding") if self.kind=="api" else self.kind,"can_generate":self.kind in ("starcanvas","api"),
                    "saved_api":bool(self.config.get("api_binding")),"sound_question":not self.config.get("sound_decided",False)}

    def persist(self, **values):
        with self.lock:
            latest=merge_settings(FILE,values)
            self.config=latest
            self.kind=latest.get("provider",self.kind)
            if self.kind=="api" and not (self.store/(str(latest.get("api_binding"))+".bin")).is_file():
                self.kind="local"
                self.config.pop("api_binding",None)
            if "provider" in values and latest.get("codex"):
                pref=Path(latest["codex"])/"muse-long-video.local.json"
                merge_settings(pref,{"backend":self.kind})

    def load(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch("[a-f0-9]{32}",identifier):
            raise ReviewError("缺少此项目绑定的 API 配置。")
        return json.loads(protect((self.store/(identifier+".bin")).read_bytes(),True))

    def missing_receipt(self,job):
        if job.get("backend")!="api" or not job.get("id"):
            return False
        folder=self.store/"tasks"/job["id"]
        remote=folder/"remote.json"
        state=folder/"attempt/attempt.json"
        if remote.is_file() and json.loads(remote.read_text("utf8")).get("id"):
            return False
        if state.is_file() and json.loads(state.read_text("utf8")).get("task_id"):
            return False
        return True

    def restore_receipt(self,job,remote):
        if not self.missing_receipt(job):
            raise ReviewError("已有原任务编号，请先查询。")
        if not isinstance(remote,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}",remote) or remote in (".",".."):
            raise ReviewError("请输入服务商提供的完整任务编号。")
        conf=self.load(job["api_binding"])
        c,token=conf["profile"],conf["key"]
        folder=self.store/"tasks"/job["id"]
        if conf["protocol"]=="json":
            state=folder/"attempt/attempt.json"
            if not state.is_file():
                raise ReviewError("缺少原始请求记录。请先在供应商记录中核对该次提交。")
            result=self.transport("GET",adapter.endpoint(c,"status",remote),token)
            if adapter.select(result,c["selectors"]["status"]) not in sum(c["states"].values(),[]):
                raise ReviewError("供应商未返回可识别的任务状态。")
            record=adapter.read(state)
            record.update(status="submitted",task_id=remote)
            write_json(state,record)
        else:
            result=self.transport("GET",c["base"]+"/contents/generations/tasks/"+urllib.parse.quote(remote,safe=""),token)
            if result.get("status") not in ("queued","running","pending","succeeded","failed","expired","cancelled","canceled") or result.get("id",remote)!=remote:
                raise ReviewError("供应商未确认该任务编号。")
            write_json(folder/"remote.json",{"id":remote})

    def select(self,data):
        kind=data.get("provider")
        if kind=="starcanvas":
            self.persist(provider=kind,starcanvas=True)
            return self.info()
        if kind!="api": raise ReviewError("请选择视频生成服务。")
        if data.get("reuse") and self.config.get("api_binding"):
            self.load(self.config["api_binding"])
            self.persist(provider="api",starcanvas=False)
            return self.info()
        token=data.get("key","").strip()
        if not token or any(ord(ch)<32 for ch in token): raise ReviewError("请填写有效的 API Key。")
        protocol=data.get("protocol","ark")
        if protocol=="ark":
            base=adapter.https(data.get("base","").strip().rstrip("/"))
            if urllib.parse.urlsplit(base).query: raise ReviewError("基础地址不能包含查询参数。")
            model=data.get("model","").strip()
            if not model: raise ReviewError("请填写供应商提供的模型或接入点 ID。")
            profile={"base":base,"model":model}
            self.transport("GET",base+"/contents/generations/tasks?page_size=1",token)
        elif protocol=="json":
            if not isinstance(data.get("profile"),dict):
                raise ReviewError("请选择包含接口配置对象的 JSON 文件。")
            try:
                profile=adapter.validate(data["profile"])
            except (KeyError,AttributeError,TypeError) as exc:
                raise ReviewError("接口配置缺少路径、字段映射或能力描述，请核对异步 JSON 配置模板。") from exc
            if profile["key_env"]!="MUSE_VIDEO_API_KEY": raise ReviewError("配置中的 key_env 应为 MUSE_VIDEO_API_KEY。")
            response=self.transport("GET",adapter.endpoint(profile,"check"),token)
            models=adapter.select(response,profile["selectors"]["models"])
            if not any(adapter.select(m,profile["selectors"]["model_id"])==profile["model"] for m in models):
                raise ReviewError("此服务未列出所选模型。")
        else: raise ReviewError("未知 API 协议。")
        raw=json.dumps({"protocol":protocol,"profile":profile,"key":token},sort_keys=True).encode()
        digest=hashlib.sha256(raw).hexdigest()[:32]
        self.store.mkdir(parents=True,exist_ok=True)
        with self.lock:
            path=self.store/(digest+".bin")
            if not path.exists():
                pending=path.with_suffix(".new")
                pending.write_bytes(protect(raw));pending.replace(path)
            self.persist(provider=kind,api_binding=digest,starcanvas=False)
        return self.info()

    def health(self):
        if self.kind=="starcanvas": return self.star.health()
        if self.kind=="api":
            c=self.load(self.config["api_binding"])
            return {"ready":True,"message":"已配置 API · "+c["profile"]["model"]}
        return {"ready":False,"message":"可先审片，生成前请选择星幕或自带 API。"}

    def download_result(self,url,result):
        import av
        from media_timing import is_mp4
        payload=self.transport("GET",adapter.https(url),binary=True)
        pending=result.with_suffix(".part")
        pending.write_bytes(payload)
        if not is_mp4(pending):
            raise ReviewError("供应商返回的结果不是可读取的 MP4。")
        with av.open(str(pending),format="mov",options={"enable_drefs":"0","protocol_whitelist":"file,pipe"}) as video:
            next(video.decode(video=0))
        pending.replace(result)
        return result

    def run(self,job,update,*,resume,title):
        if job.get("backend","starcanvas")=="starcanvas":
            return self.star.run(job,update,resume=resume,title=title)
        conf=self.load(job["api_binding"])
        folder=self.store/"tasks"/job["id"]
        folder.mkdir(parents=True,exist_ok=True)
        result=folder/"download.mp4"
        if result.is_file(): return result
        c,token=conf["profile"],conf["key"]
        if conf["protocol"]=="json":
            def cli(*args):
                submit=args[0]=="submit" and args[-1]=="--execute"
                script=Path(__file__).with_name("api_attempt.py") if submit else SKILL/"scripts/video_api.py"
                proc=subprocess.run([sys.executable,"-B",str(script),*map(str,args[1:-1] if submit else args)],
                    env=dict(os.environ,MUSE_VIDEO_API_KEY=token,PYTHONIOENCODING="utf-8"),capture_output=True,encoding="utf8",errors="replace")
                if submit and proc.returncode==3:
                    code=proc.stdout.strip()
                    raise LaunchRejected(f"视频 API 拒绝提交（HTTP {code}）。请检查模型、参数、账户或配额。" if code.isdigit() else "参考图上传失败，视频任务尚未提交。")
                if proc.returncode: raise ReviewError("视频 API 操作未完成，请核对协议、模型参数与原任务。")
                return json.loads(proc.stdout)
            state=folder/"attempt"
            if not resume:
                profile,receipt,request=(folder/n for n in ("profile.json","receipt.json","request.json"))
                write_json(profile,c);cli("check",profile,receipt)
                params={k:v for k,v in [(c.get("studio_duration_field","duration"),job["duration"]),(c.get("studio_ratio_field","aspect_ratio"),job["ratio"])] if k in c["parameters"]}
                r={"prompt":job["prompt"],"parameters":{**c.get("studio_defaults",{}),**params},"reference_image":job.get("reference"),"reference_role":c["capabilities"]["image_role"]}
                write_json(request,r);cli("submit",profile,receipt,request,state)
                update(status="submitting",card=job["id"],message="正在提交视频 API…")
                submitted=cli("submit",profile,receipt,request,state,"--execute")
                update(status="running",card=submitted["task_id"],message="API 已受理。")
            for _ in range(360):
                status=cli("status",state)["status"]
                if status=="succeeded":
                    return self.download_result(adapter.read(state/"attempt.json")["result_url"],result)
                if status=="failed": raise LaunchRejected("API 报告生成失败。")
                if status!="pending":raise ReviewError("原任务状态未知，请向供应商核对。")
                time.sleep(5)
        else:
            url=c["base"]+"/contents/generations/tasks"
            receipt=folder/"remote.json"
            if not resume:
                content=[{"type":"text","text":job["prompt"]}]
                if job.get("reference"):
                    image=Path(job["reference"]).read_bytes()
                    content.append({"type":"image_url","role":"first_frame","image_url":{"url":"data:image/png;base64,"+base64.b64encode(image).decode()}})
                body={"model":c["model"],"content":content,"duration":job["duration"],"ratio":job["ratio"]}
                update(status="submitting",card=job["id"],message="正在提交视频 API…")
                try:
                    remote=self.transport("POST",url,token,json.dumps(body).encode()).get("id")
                except adapter.ApiError as exc:
                    code=rejected_http(exc)
                    if code:
                        raise LaunchRejected(f"视频 API 拒绝提交（HTTP {code}）。请检查模型、参数、账户或配额。") from exc
                    raise
                if not isinstance(remote,str) or not remote:raise ReviewError("API 未返回任务编号，请核对供应商记录。")
                write_json(receipt,{"id":remote})
                update(status="running",card=remote,message="API 已受理。")
            if not receipt.is_file(): raise ReviewError("上次提交未返回任务编号，请核对供应商记录。")
            remote=json.loads(receipt.read_text("utf8"))["id"]
            for _ in range(360):
                data=self.transport("GET",url+"/"+urllib.parse.quote(remote,safe=""),token)
                if data.get("status")=="succeeded":
                    return self.download_result(data["content"]["video_url"],result)
                if data.get("status") in ("failed","expired","cancelled","canceled"):
                    raise LaunchRejected("API 报告任务失败或已取消。")
                if data.get("status") not in ("queued","running","pending"):
                    raise ReviewError("API 返回未知状态，请查询原任务。")
                time.sleep(5)
        raise ReviewError("生成仍在等待，请稍后查询原任务。")
