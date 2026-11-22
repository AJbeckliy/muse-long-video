"""Initialize a copied Codex skill; the studio and interpreter are already here."""
from pathlib import Path
import json,os,sys,subprocess
from uuid import uuid4

root=Path(__file__).resolve().parent
subprocess.run([sys.executable,"-B",str(root/"base_install.py")],check=True)
skill=root.parent
home=Path(os.environ.get("CODEX_HOME",Path.home()/".codex")) if skill.parent.name!="skills" else skill.parent.parent
pref=home/"muse-long-video.local.json"
settings=root/"studio/settings.local.json"
def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
def save(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(".new-"+uuid4().hex)
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf8")
    tmp.replace(p)
current=read(pref)
opts=read(settings)
if not opts and current.get("review_studio"):
    opts=read(Path(current["review_studio"]).parent/"settings.local.json")
media=Path(os.environ.get("MUSE_SETUP_WORKSPACE") or opts.get("workspace") or current.get("workspace_root") or (Path.home()/"Videos/Muse工作台")).resolve()
for sub in ("Temp","Projects","Outputs"): (media/sub).mkdir(exist_ok=True,parents=True)
opts.update(workspace=str(media),skill=str(skill),codex=str(home))
opts.setdefault("audio",False)
opts.setdefault("provider",current.get("backend") if current.get("backend") in ("api","starcanvas") else "local")
if opts.get("audio_packages"):opts["audio_python"]=sys.executable
save(settings,opts)
current.update(workspace_root=str(media),python=sys.executable,review_studio=str(root/"studio/Open-Muse-Review.cmd"))
save(pref,current)
ps=Path(os.environ["SystemRoot"])/"System32/WindowsPowerShell/v1.0/powershell.exe"
if os.environ.get("MUSE_NO_SHORTCUT")!="1":
    env=dict(os.environ,MUSE_LINK_TARGET=current["review_studio"])
    subprocess.run([str(ps),"-NoProfile","-Command","$ErrorActionPreference='Stop';$s=New-Object -ComObject WScript.Shell;$desk=$s.SpecialFolders.Item('Desktop');$l=$s.CreateShortcut((Join-Path $desk 'Muse Review Studio.lnk'));$l.TargetPath=$env:MUSE_LINK_TARGET;$l.WorkingDirectory=Split-Path $env:MUSE_LINK_TARGET;$l.Save()"],env=env,check=True)
if "--no-open" not in sys.argv:
    subprocess.run([sys.executable,"-B",str(root/"studio/launch.py")],check=True)
