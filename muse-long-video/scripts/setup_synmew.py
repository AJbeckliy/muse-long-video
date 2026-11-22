"""Register SynMew's bundled STDIO MCP. No generation, uploads or account access."""
from pathlib import Path
import argparse, datetime, getpass, importlib.util, json, os, queue, shutil, subprocess, sys, threading, time
try:
    import tomllib
except ImportError:
    import tomli as tomllib

SERVER = 'synmew-canvas'

def read_config(path):
    raw = path.read_bytes() if path.exists() else b''
    return raw, tomllib.loads(raw.decode('utf-8-sig'))

def configure(config, exe, workspace, port, token, apply=False, pair_only=False):
    config, exe, workspace = map(Path, (config, exe, workspace))
    if not all(p.is_absolute() for p in (config, exe, workspace)):
        raise ValueError('Use absolute paths.')
    if not exe.is_file() or exe.suffix.lower() != '.exe':
        raise ValueError('Select the installed SynMewInfiniteCanvas.exe.')
    if not 1 <= port <= 65535 or not token or '\n' in token or '\r' in token:
        raise ValueError('A valid local MCP port and pairing token are required.')
    raw, data = read_config(config)
    old = data.get('mcp_servers', {}).get(SERVER)
    expected = {'command':str(exe), 'args':['--mcp-server'],
                'env':{'SYNMEW_MCP_PORT':str(port),'SYNMEW_MCP_TOKEN':token}}
    same = (old is not None and os.path.normcase(old.get('command','')) == os.path.normcase(str(exe))
            and old.get('args') == expected['args']
            and all(old.get('env',{}).get(k) == v for k,v in expected['env'].items())
            and old.get('enabled',True))
    if old is not None and not same:
        raise ValueError('Existing synmew-canvas configuration differs or is disabled. It was not overwritten. Ask your assistant to review this one entry.')
    state = {'config_action':'already_configured' if same else 'add_server',
             'workspace':str(workspace), 'applied':False, 'probe':'not_run'}
    if not apply:
        return state
    config.parent.mkdir(parents=True, exist_ok=True)
    # A conservative additive write preserves model/provider/other MCP settings verbatim.
    if not same:
        q = lambda s: json.dumps(s,ensure_ascii=False)
        block = '\n\n[mcp_servers.synmew-canvas]\ncommand = '+q(str(exe))+'\nargs = ["--mcp-server"]\nenabled = true\nstartup_timeout_sec = 30\ntool_timeout_sec = 120\n\n[mcp_servers.synmew-canvas.env]\nSYNMEW_MCP_PORT = '+q(str(port))+'\nSYNMEW_MCP_TOKEN = '+q(token)+'\n'
        new = raw + block.encode('utf8')
        parsed = tomllib.loads(new.decode('utf-8-sig'))
        assert parsed['mcp_servers'][SERVER]['command'] == str(exe)
        if config.exists():
            backup = config.with_name(config.name+'.before-synmew-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            shutil.copy2(config,backup)
            if config.read_bytes() != raw:
                raise ValueError('Configuration changed during setup; retry after reviewing it.')
        temp = config.with_name(config.name+'.synmew-new-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        with temp.open('xb') as f:
            f.write(new)
        os.replace(temp,config)
    for name in ('Projects','Temp','Outputs'):
        (workspace/name).mkdir(parents=True,exist_ok=True)
    local = config.parent/'muse-long-video.local.json'
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'windows'/'studio'))
    from settings_io import merge_settings
    fields={'synmew_exe':str(exe),'mcp_server':SERVER}
    if not pair_only:
        fields.update(backend='starcanvas',workspace_root=str(workspace),python=sys.executable)
    merge_settings(local,fields)
    state['applied'] = True
    return state

def probe(config, timeout=25):
    _, data = read_config(Path(config))
    cfg = data.get('mcp_servers',{}).get(SERVER)
    if not cfg or not cfg.get('enabled',True):
        raise ValueError('Enabled synmew-canvas entry not found.')
    if cfg.get('args') != ['--mcp-server'] or not Path(cfg.get('command','')).is_file():
        raise ValueError('SynMew executable or --mcp-server entry is invalid.')
    env = os.environ.copy(); env.update(cfg.get('env',{}))
    proc = subprocess.Popen([cfg['command'],'--mcp-server'],stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,
                            encoding='utf8',errors='replace',env=env,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    lines = queue.Queue()
    def reader():
        for line in proc.stdout:
            try: lines.put(json.loads(line))
            except (ValueError,TypeError): pass
        lines.put(None)
    threading.Thread(target=reader,daemon=True).start()
    def send(body):
        proc.stdin.write(json.dumps(body,ensure_ascii=False)+'\n');proc.stdin.flush()
    def call(i, method, params):
        send({'jsonrpc':'2.0','id':i,'method':method,'params':params})
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            try: msg=lines.get(timeout=max(.01,end-time.monotonic()))
            except queue.Empty: break
            if msg is None: break
            if msg.get('id')==i:
                if 'error' in msg: raise ValueError('MCP returned an error; check local pairing and app state.')
                return msg['result']
        raise ValueError('MCP did not respond; open SynMew, enable MCP, and check the local pairing port/token.')
    try:
        init=call(1,'initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'muse-long-video-check','version':'1.0'}})
        send({'jsonrpc':'2.0','method':'notifications/initialized','params':{}})
        tool_result=call(2,'tools/list',{})
        names={t['name'] for t in tool_result.get('tools',[])}
        if 'workspace_get_context' not in names: raise ValueError('This app version does not expose workspace_get_context.')
        read=call(3,'tools/call',{'name':'workspace_get_context','arguments':{}})
        if read.get('isError'): raise ValueError('MCP launched but the canvas read failed. Check pairing and open an app workspace.')
        for c in read.get('content',[]):
            if c.get('type')=='text':
                try:
                    body=json.loads(c['text'])
                except ValueError: continue
                if isinstance(body,dict) and body.get('ok') is False:
                    raise ValueError('MCP launched but the canvas is not readable. Check pairing and open a workspace.')
        return {'handshake':True,'tools_list':True,'workspace_read':True,
                'tool_count':len(names),'server':init.get('serverInfo',{}),
                'generation_submitted':False,'paid_access':'not_tested'}
    finally:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill();proc.wait()
        proc.stdin.close();proc.stdout.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    home=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))
    p.add_argument('--config',type=Path,default=home/'config.toml')
    p.add_argument('--exe',type=Path);p.add_argument('--workspace',type=Path)
    p.add_argument('--port',type=int);p.add_argument('--apply',action='store_true')
    p.add_argument('--pair-only',action='store_true',help='Register the connection; keep the current provider preference.')
    p.add_argument('--probe',action='store_true');p.add_argument('--check',action='store_true')
    a=p.parse_args()
    try:
        if a.check:
            raw,data=read_config(a.config)
            print(json.dumps({'python':sys.version.split()[0], 'dependencies':{m:importlib.util.find_spec(m) is not None for m in ['av','PIL','imageio_ffmpeg']},'mcp_configured':SERVER in data.get('mcp_servers',{}),'generation_submitted':False},ensure_ascii=False))
        if a.exe:
            if a.workspace is None or a.port is None: raise ValueError('Provide --workspace and --port.')
            _,d=read_config(a.config)
            token=d.get('mcp_servers',{}).get(SERVER,{}).get('env',{}).get('SYNMEW_MCP_TOKEN')
            if not token: token=getpass.getpass('粘贴你自己星幕的 MCP 配对 Token（隐藏输入，按回车提交）：')
            print(json.dumps(configure(a.config,a.exe,a.workspace,a.port,token,a.apply,a.pair_only),ensure_ascii=False))
        if a.probe: print(json.dumps(probe(a.config),ensure_ascii=False))
        if not (a.check or a.probe or a.exe):p.print_help()
        return 0
    except Exception as exc:
        # Deliberately suppress raw subprocess/server/config content, which may contain secrets.
        if isinstance(exc,ValueError) and not isinstance(exc,tomllib.TOMLDecodeError):print('ERROR: '+str(exc),file=sys.stderr)
        else:print('ERROR: setup/check failed ('+type(exc).__name__+'). No credentials displayed.',file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
