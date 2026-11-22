"""Obtain exact upstream Windows wheels once; subsequent launches work offline."""
import hashlib,json,os,shutil,ssl,subprocess,sys,urllib.request
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
MANIFEST=HERE/"upstream-wheels.json"
def destination():
    cache=os.environ.get("MUSE_BASE_CACHE") or str(Path(os.environ.get("LOCALAPPDATA",Path.home()))/"MuseReview"/"base-cache")
    return Path(cache)/hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:16]

def install():
    dest=destination()
    if (dest/"ready").is_file():return
    dest.parent.mkdir(parents=True,exist_ok=True)
    stage=dest.with_name(dest.name+"-"+uuid4().hex)
    stage.mkdir()
    manifest=json.loads(MANIFEST.read_text(encoding="utf8"))
    for item in manifest:
        print("正在准备基础组件 "+item["name"],flush=True)
        src=dest.parent/item["name"]
        if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=item["sha256"]:
            incoming=stage/(item["name"]+".part")
            with urllib.request.urlopen(item["url"],timeout=90) as response, incoming.open("xb") as out:
                shutil.copyfileobj(response,out)
            if hashlib.sha256(incoming.read_bytes()).hexdigest()!=item["sha256"]:
                raise RuntimeError("下载内容校验失败，请重新运行安装。")
            os.replace(incoming,src)
        with ZipFile(src) as wheel:wheel.extractall(stage)
    (stage/"ready").touch()
    try:stage.rename(dest)
    except OSError:
        if not (dest/"ready").is_file():raise
if __name__=="__main__":install()
