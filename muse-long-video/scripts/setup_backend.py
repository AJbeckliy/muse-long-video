"""Save shared local setup without installing or inspecting Starcanvas."""
import argparse,json,sys
from pathlib import Path
def configure(config_dir,workspace,backend,apply=False):
    config_dir,workspace=Path(config_dir),Path(workspace)
    if not config_dir.is_absolute() or not workspace.is_absolute():raise ValueError('Use absolute directories')
    if backend not in ('api','defer'):raise ValueError('Expected api or defer')
    result={'backend':backend,'workspace_root':str(workspace),'python':sys.executable,'generation_ready':False}
    if apply:
        config_dir.mkdir(parents=True,exist_ok=True)
        for n in ('Projects','Temp','Outputs'):(workspace/n).mkdir(parents=True,exist_ok=True)
        p=config_dir/'muse-long-video.local.json'
        old=json.loads(p.read_text('utf-8-sig')) if p.exists() else {}
        old.update(result);p.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf8')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config-dir',required=True);p.add_argument('--workspace',required=True);p.add_argument('--backend',choices=['api','defer'],required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    print(json.dumps(configure(a.config_dir,a.workspace,a.backend,a.apply),ensure_ascii=False))
