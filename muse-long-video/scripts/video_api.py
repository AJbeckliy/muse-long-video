"""Document-matched Bearer JSON async video adapter. No default host or model."""
from pathlib import Path
import argparse, hashlib, json, mimetypes, os, re, sys, time, urllib.request, urllib.error, urllib.parse, uuid

class ApiError(ValueError): pass

def read(path): return json.loads(Path(path).read_text('utf-8-sig'))
def save(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.tmp-'+uuid.uuid4().hex)
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,p)
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def select(data,path):
    for part in path.split('.'):
        if not isinstance(data,dict) or part not in data: raise ApiError('Response does not match documented selector: '+path)
        data=data[part]
    return data
def https(url):
    s=urllib.parse.urlsplit(url)
    if s.scheme!='https' or not s.hostname or s.username or s.password or s.fragment:
        raise ApiError('Only HTTPS URLs without embedded credentials/fragments are supported.')
    return url
def endpoint(c,name,job=None):
    path=c['paths'][name]
    if job is not None:path=path.replace('{id}',urllib.parse.quote(str(job),safe=''))
    if path.startswith(('/', '\\')) or '://' in path or '..' in path.split('/'):
        raise ApiError('API paths must be relative to the supplied base URL.')
    return https(c['base_url'].rstrip('/')+'/'+path)
def validate(c):
    if c.get('backend')!='api' or c.get('protocol')!='video_async_json_v1':raise ApiError('Unsupported protocol; do not guess an adapter.')
    https(c['base_url'])
    if urllib.parse.urlsplit(c['base_url']).query:raise ApiError('Base URL must not contain a query.')
    if not isinstance(c.get('model'),str) or not c['model'].strip():raise ApiError('An exact user-selected model is required.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',c.get('key_env','')):raise ApiError('Specify an environment variable name, not a key.')
    if any(k in c for k in ('api_key','token','headers','key')):raise ApiError('Credentials belong only in the local environment.')
    evidence=c.get('evidence',{})
    if evidence.get('model')!=c['model'] or evidence.get('protocol_verified') is not True or evidence.get('readonly_check_verified') is not True:
        raise ApiError('Provider documentation, exact model and read-only endpoint must be verified first.')
    https(evidence['source'])
    for name in ('check','submit','status'):endpoint(c,name)
    if c['paths']['status'].count('{id}')!=1:raise ApiError('Status path must contain exactly one {id}.')
    for name in ('models','model_id','job_id','status','result_url'):
        if not isinstance(c.get('selectors',{}).get(name),str) or not c['selectors'][name]:raise ApiError('Missing response selector: '+name)
    groups=[c.get('states',{}).get(k) for k in ('pending','succeeded','failed')]
    if any(not isinstance(g,list) or not g or any(not isinstance(v,str) for v in g) for g in groups):raise ApiError('Provide documented status values.')
    flat=[v for g in groups for v in g]
    if len(flat)!=len(set(flat)):raise ApiError('Status groups overlap.')
    fields=c.get('fields',{})
    if not all(isinstance(fields.get(n),str) and fields[n] for n in ('model','prompt')):raise ApiError('Missing request field mapping.')
    names=list(fields.values())
    if any(not isinstance(v,str) or not v for v in names) or len(names)!=len(set(names)):raise ApiError('Invalid or conflicting request field mappings.')
    if not isinstance(c.get('parameters'),dict):raise ApiError('Documented parameter rules required.')
    if set(c['parameters'])&set(names):raise ApiError('Parameters may not override model/prompt/image fields.')
    cap=c.get('capabilities',{})
    if cap.get('image_role') not in ('none','reference','first_frame'):raise ApiError('Reference image role must be documented.')
    if not isinstance(cap.get('audio_output'),bool):raise ApiError('Audio output capability must be documented.')
    if cap['image_role']!='none':
        if evidence.get('reference_images_verified') is not True:raise ApiError('Selected model reference-image support is unverified.')
        endpoint(c,'upload')
        if not fields.get('image') or not c['selectors'].get('upload_url'):raise ApiError('Image upload mappings required.')
        if not cap.get('image_formats') or not isinstance(cap.get('max_image_bytes'),int) or cap['max_image_bytes']<=0:raise ApiError('Image format and size limits required.')
    return c
def get_key(c):
    key=os.environ.get(c['key_env'],'')
    if not key or '\n' in key or '\r' in key:raise ApiError('API key environment variable missing or invalid.')
    return key
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
def http(method,url,key=None,body=None,content_type='application/json',binary=False):
    headers={'User-Agent':'MuseLongVideo/2.0','Accept':'application/json' if not binary else '*/*'}
    if key:headers['Authorization']='Bearer '+key
    if body is not None:headers['Content-Type']=content_type
    req=urllib.request.Request(https(url),data=body,headers=headers,method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=60) as response:
            if binary:return response.read()
            data=json.loads(response.read().decode('utf8'))
        if not isinstance(data,dict) or data.get('error'):raise ApiError('API returned a business error or unsupported response; raw body suppressed.')
        return data
    except ApiError:raise
    except urllib.error.HTTPError as e:raise ApiError('API HTTP '+str(e.code)+'; request not retried.') from None
    except (urllib.error.URLError,TimeoutError,OSError,ValueError):raise ApiError('Connection/response failed; request not retried.') from None
def check(c,receipt,transport=http):
    validate(c);key=get_key(c)
    data=transport('GET',endpoint(c,'check'),key)
    models=select(data,c['selectors']['models'])
    if not isinstance(models,list) or not any(isinstance(m,dict) and select(m,c['selectors']['model_id'])==c['model'] for m in models):
        raise ApiError('Exact selected model was not found in the read-only model list.')
    result={'config_hash':digest(c),'key_fingerprint':hashlib.sha256(key.encode()).hexdigest(),'checked_at':time.time(),'readonly_ready':True,'generation_tested':False}
    save(receipt,result);return {'readonly_ready':True,'generation_tested':False}
def validate_request(c,r):
    if not isinstance(r.get('prompt'),str) or not r['prompt'].strip():raise ApiError('Prompt required.')
    params=r.get('parameters',{})
    if not isinstance(params,dict) or set(params)-set(c['parameters']):raise ApiError('Undocumented request parameter.')
    for name,rule in c['parameters'].items():
        if rule.get('required') and name not in params:raise ApiError('Required parameter missing: '+name)
        if name not in params:continue
        value=params[name]
        if 'enum' in rule:
            if value not in rule['enum']:raise ApiError('Unsupported parameter value: '+name)
        elif rule.get('type') in ('integer','number'):
            valid=isinstance(value,int) if rule['type']=='integer' else isinstance(value,(int,float))
            if isinstance(value,bool) or not valid or not rule['minimum']<=value<=rule['maximum']:raise ApiError('Parameter outside documented range: '+name)
        else:raise ApiError('Unsupported parameter schema: '+name)
    image=r.get('reference_image')
    if r.get('needs_continuity') and not image:raise ApiError('Continuation needs an actual reference frame.')
    if image:
        cap=c['capabilities']
        if cap['image_role']=='none' or r.get('reference_role')!=cap['image_role']:raise ApiError('Reference role is unsupported or mismatched.')
        p=Path(image)
        if not p.is_absolute() or not p.is_file():raise ApiError('Reference must be an existing absolute local file.')
        if p.stat().st_size>cap['max_image_bytes']:raise ApiError('Reference exceeds documented byte limit.')
        from PIL import Image
        with Image.open(p) as im:
            fmt=im.format.lower();w,h=im.size;im.verify()
        if fmt not in cap['image_formats']:raise ApiError('Reference image format unsupported.')
        limits=cap.get('image_dimensions',{})
        for key,v in [('width',w),('height',h)]:
            if v<limits.get('min_'+key,0) or v>limits.get('max_'+key,float('inf')):raise ApiError('Reference dimensions unsupported.')
    return params
def submit(c,receipt,r,attempt,execute=False,transport=http):
    validate(c);params=validate_request(c,r);key=get_key(c)
    if receipt.get('config_hash')!=digest(c) or receipt.get('key_fingerprint')!=hashlib.sha256(key.encode()).hexdigest() or receipt.get('readonly_ready') is not True:
        raise ApiError('Configuration/key changed or no passing check receipt; recheck first.')
    if not execute:return {'ready_for_authorized_submission':True,'generation_submitted':False}
    folder=Path(attempt)
    if not folder.is_absolute():raise ApiError('Attempt path must be absolute.')
    folder.mkdir(parents=True,exist_ok=False) # refuse repeat submissions to an existing attempt
    state={'config':c,'request':r,'status':'prepared','task_id':None,'config_hash':digest(c)}
    state_path=folder/'attempt.json';save(state_path,state)
    body=dict(params);body[c['fields']['model']]=c['model'];body[c['fields']['prompt']]=r['prompt']
    try:
        image=r.get('reference_image')
        if image:
            state['status']='uploading';save(state_path,state)
            p=Path(image);boundary='MuseLongVideo'+uuid.uuid4().hex
            mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
            upload=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reference{p.suffix.lower()}"\r\nContent-Type: {mime}\r\n\r\n').encode()+p.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
            response=transport('POST',endpoint(c,'upload'),key,upload,'multipart/form-data; boundary='+boundary)
            body[c['fields']['image']]=https(select(response,c['selectors']['upload_url']))
        state['status']='submitting';save(state_path,state)
        result=transport('POST',endpoint(c,'submit'),key,json.dumps(body,ensure_ascii=False).encode())
        task=select(result,c['selectors']['job_id'])
        if not isinstance(task,(str,int)) or isinstance(task,bool) or not str(task):raise ApiError('Response has no usable task ID.')
        state.update(status='submitted',task_id=str(task));save(state_path,state)
        return {'status':'submitted','task_id':str(task)}
    except Exception:
        state['status']='unknown' if state['status']=='submitting' else 'upload_failed'
        save(state_path,state)
        raise ApiError('Submission incomplete: '+state['status']+'. Do not automatically submit again.') from None
def status(attempt,transport=http):
    path=Path(attempt)/'attempt.json';s=read(path);c=validate(s['config'])
    if s['status'] in ('succeeded','failed'):return {'status':s['status'],'task_id':s['task_id']}
    if not s.get('task_id'):raise ApiError('No task ID: reconcile original attempt; do not resubmit.')
    data=transport('GET',endpoint(c,'status',s['task_id']),get_key(c))
    value=select(data,c['selectors']['status']);groups=c['states']
    state=next((k for k in ('pending','succeeded','failed') if value in groups[k]),'unknown')
    if state=='succeeded':s['result_url']=https(select(data,c['selectors']['result_url']))
    s['status']=state;save(path,s)
    return {'status':state,'task_id':s['task_id']}
def download(attempt,output,transport=http):
    s=read(Path(attempt)/'attempt.json')
    if s['status']!='succeeded':raise ApiError('Only download a successful task.')
    dst=Path(output)
    if not dst.is_absolute() or dst.exists():raise ApiError('Use a new absolute output filename.')
    blob=transport('GET',s['result_url'],binary=True) # never forward API credentials to media hosts
    if not blob:raise ApiError('Empty result download; retry collection, not generation.')
    import av
    import io
    try:
        with av.open(io.BytesIO(blob)) as media:
            if not media.streams.video:raise ApiError('Result has no video stream.')
            next(media.decode(video=0))
    except Exception:raise ApiError('Downloaded result is not a decodable video.') from None
    dst.parent.mkdir(parents=True,exist_ok=True)
    with dst.open('xb') as f:f.write(blob)
    return {'output':str(dst),'bytes':len(blob),'first_frame_decoded':True}
def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('check');a.add_argument('config');a.add_argument('receipt')
    a=sub.add_parser('submit');a.add_argument('config');a.add_argument('receipt');a.add_argument('request');a.add_argument('attempt');a.add_argument('--execute',action='store_true')
    a=sub.add_parser('status');a.add_argument('attempt')
    a=sub.add_parser('download');a.add_argument('attempt');a.add_argument('output')
    a=p.parse_args()
    try:
        if a.action=='check':result=check(read(a.config),a.receipt)
        elif a.action=='submit':result=submit(read(a.config),read(a.receipt),read(a.request),a.attempt,a.execute)
        elif a.action=='status':result=status(a.attempt)
        else:result=download(a.attempt,a.output)
        print(json.dumps(result,ensure_ascii=False));return 0
    except Exception as e:
        print('ERROR: '+(str(e) if isinstance(e,ApiError) else type(e).__name__+'; check local inputs/dependencies. Raw content suppressed.'),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
