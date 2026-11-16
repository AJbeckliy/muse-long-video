"""Offline API contract tests: fake transport, no credentials or paid calls."""
import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
import video_api as api
import setup_backend

def profile():
    return {'backend':'api','protocol':'video_async_json_v1','base_url':'https://provider.example.test/v1','model':'fixture-video','key_env':'MUSE_TEST_ONLY_KEY',
            'paths':{'check':'models','submit':'videos','status':'videos/{id}','upload':'uploads'},
            'selectors':{'models':'data','model_id':'id','job_id':'data.id','status':'data.status','result_url':'data.url','upload_url':'url'},
            'fields':{'model':'model','prompt':'prompt','image':'image_url'},
            'states':{'pending':['queued','running'],'succeeded':['done'],'failed':['error']},
            'parameters':{'duration':{'type':'integer','minimum':4,'maximum':10,'required':True}},
            'capabilities':{'image_role':'first_frame','image_formats':['png'],'max_image_bytes':100000,'audio_output':True},
            'evidence':{'source':'https://provider.example.test/docs','model':'fixture-video','protocol_verified':True,'readonly_check_verified':True,'reference_images_verified':True}}
class Transport:
    def __init__(self,results):self.results=list(results);self.calls=[]
    def __call__(self,*args,**kwargs):
        self.calls.append((args,kwargs));r=self.results.pop(0)
        if isinstance(r,Exception):raise r
        return r
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import imageio_ffmpeg
        cls.video=WORK/'fixture.mp4'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-n','-v','error','-f','lavfi','-i','color=blue:s=64x96:r=24','-frames:v','2','-c:v','libx264','-pix_fmt','yuv420p',str(cls.video)],check=True)
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='api-',dir=WORK));self.c=profile()
        self.old=os.environ.get('MUSE_TEST_ONLY_KEY');os.environ['MUSE_TEST_ONLY_KEY']='fixture-secret-not-real'
        self.receipt=self.root/'check.json';self.image=self.root/'image.png';Image.new('RGB',(32,48),'blue').save(self.image)
        self.r={'prompt':'测试','parameters':{'duration':10},'reference_image':str(self.image),'reference_role':'first_frame','needs_continuity':True}
    def tearDown(self):
        if self.old is None:os.environ.pop('MUSE_TEST_ONLY_KEY',None)
        else:os.environ['MUSE_TEST_ONLY_KEY']=self.old
    def checked(self):
        api.check(self.c,self.receipt,Transport([{'data':[{'id':'fixture-video'}]}]));return api.read(self.receipt)
    def submitted(self):
        t=Transport([{'url':'https://media.example.test/input.png'},{'data':{'id':'job/1'}}]);p=self.root/'attempt'
        api.submit(self.c,self.checked(),self.r,p,True,t);return p,t
    def test_check_read_only_and_no_plain_key(self):
        t=Transport([{'data':[{'id':'fixture-video'}]}]);api.check(self.c,self.receipt,t)
        self.assertEqual(len(t.calls),1);self.assertEqual(t.calls[0][0][0],'GET');self.assertNotIn('fixture-secret-not-real',self.receipt.read_text())
    def test_missing_key_rejected_without_request(self):
        os.environ.pop('MUSE_TEST_ONLY_KEY');t=Transport([])
        with self.assertRaises(api.ApiError):api.check(self.c,self.receipt,t)
        self.assertEqual(t.calls,[])
    def test_exact_model_required(self):
        with self.assertRaises(api.ApiError):api.check(self.c,self.receipt,Transport([{'data':[{'id':'fixture-other'}]}]))
        self.assertFalse(self.receipt.exists())
    def test_unsupported_protocol_and_unverified_evidence(self):
        c=copy.deepcopy(self.c);c['protocol']='chat_video'
        with self.assertRaises(api.ApiError):api.validate(c)
        self.c['evidence']['protocol_verified']=False
        with self.assertRaises(api.ApiError):api.validate(self.c)
    def test_dry_run_does_not_upload_or_create_attempt(self):
        t=Transport([]);p=self.root/'attempt';api.submit(self.c,self.checked(),self.r,p,False,t)
        self.assertFalse(p.exists());self.assertEqual(t.calls,[])
    def test_changed_config_and_key_need_recheck(self):
        rec=self.checked();self.c['model']='other'
        with self.assertRaises(api.ApiError):api.submit(self.c,rec,self.r,self.root/'x',False,Transport([]))
        self.c=profile();os.environ['MUSE_TEST_ONLY_KEY']='changed-fixture'
        with self.assertRaises(api.ApiError):api.submit(self.c,rec,self.r,self.root/'x',False,Transport([]))
    def test_reference_role_limits_and_missing_reference(self):
        for mutation in [{'reference_role':'reference'},{'reference_image':None},{'parameters':{'duration':11}}]:
            r=copy.deepcopy(self.r);r.update(mutation)
            with self.assertRaises(api.ApiError):api.validate_request(self.c,r)
        self.c['capabilities']['max_image_bytes']=1
        with self.assertRaises(api.ApiError):api.validate_request(self.c,self.r)
    def test_submit_maps_fields_and_refuses_duplicate(self):
        p,t=self.submitted();body=json.loads(t.calls[1][0][3]);self.assertEqual(body['image_url'],'https://media.example.test/input.png');self.assertEqual(body['model'],'fixture-video')
        with self.assertRaises(FileExistsError):api.submit(self.c,self.checked(),self.r,p,True,Transport([]))
    def test_timeout_after_submit_persists_unknown(self):
        p=self.root/'attempt';t=Transport([{'url':'https://media.example.test/in.png'},TimeoutError('do not expose secret')])
        with self.assertRaises(api.ApiError) as err:api.submit(self.c,self.checked(),self.r,p,True,t)
        self.assertNotIn('secret',str(err.exception));self.assertEqual(api.read(p/'attempt.json')['status'],'unknown')
        with self.assertRaises(api.ApiError):api.status(p,Transport([]))
    def test_status_recovery_uses_original_config(self):
        p,t=self.submitted();self.c['model']='changed-after-submit';q=Transport([{'data':{'status':'running'}}]);api.status(p,q)
        self.assertEqual(q.calls[0][0][1],'https://provider.example.test/v1/videos/job%2F1');self.assertEqual(api.read(p/'attempt.json')['status'],'pending')
    def test_terminal_failure_does_not_poll_again(self):
        p,_=self.submitted();api.status(p,Transport([{'data':{'status':'error'}}]));q=Transport([])
        self.assertEqual(api.status(p,q)['status'],'failed');self.assertEqual(q.calls,[])
    def test_download_no_key_forwarding_or_overwrite(self):
        p,_=self.submitted();api.status(p,Transport([{'data':{'status':'done','url':'https://cdn.example.test/v.mp4'}}]))
        q=Transport([self.video.read_bytes()]);dst=self.root/'out.mp4';api.download(p,dst,q)
        self.assertEqual(len(q.calls[0][0]),2);self.assertNotIn('key',q.calls[0][1]);self.assertEqual(dst.read_bytes(),self.video.read_bytes())
        with self.assertRaises(api.ApiError):api.download(p,dst,Transport([]))
    def test_collection_retry_does_not_resubmit(self):
        p,_=self.submitted();api.status(p,Transport([{'data':{'status':'done','url':'https://cdn.example.test/v.mp4'}}]));dst=self.root/'out.mp4'
        with self.assertRaises(api.ApiError):api.download(p,dst,Transport([b'not a video']))
        self.assertFalse(dst.exists());self.assertEqual(api.read(p/'attempt.json')['status'],'succeeded');api.download(p,dst,Transport([self.video.read_bytes()]))
    def test_api_setup_leaves_mcp_untouched(self):
        cfg=self.root/'codex';cfg.mkdir();f=cfg/'config.toml';f.write_text('# untouched\n')
        setup_backend.configure(cfg,self.root/'media','api',True)
        self.assertEqual(f.read_text(),'# untouched\n');self.assertEqual(api.read(cfg/'muse-long-video.local.json')['backend'],'api')
    def test_cross_host_and_parent_paths_rejected(self):
        for path in ['/generate','https://other.example.test/run','../run']:
            c=copy.deepcopy(self.c);c['paths']['submit']=path
            with self.assertRaises(api.ApiError):api.validate(c)
    def test_secret_in_config_rejected(self):
        self.c['api_key']='fixture'
        with self.assertRaises(api.ApiError):api.validate(self.c)
    def test_http_200_business_error_not_ready_or_leaked(self):
        from unittest.mock import patch,MagicMock
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=b'{"error":"fixture-secret-not-real"}'
        opener=MagicMock();opener.open.return_value=response
        with patch.object(api.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(api.ApiError) as caught:api.http('GET','https://provider.example.test/models','fixture-secret-not-real')
        self.assertIn('business error',str(caught.exception));self.assertNotIn('fixture-secret-not-real',str(caught.exception))

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Provide a new absolute test directory')
    WORK=Path(sys.argv.pop());assert WORK.is_absolute();WORK.mkdir(parents=True,exist_ok=False);unittest.main(verbosity=2)
