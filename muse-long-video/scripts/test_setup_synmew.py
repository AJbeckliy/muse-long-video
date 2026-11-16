"""Offline setup tests. Does not start SynMew, install packages or change real config."""
from pathlib import Path
import json,sys,tempfile,unittest
import setup_synmew as setup

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='synmew-setup-',dir=WORK))
        self.exe=self.root/'Chinese 路径 with space'/'SynMewInfiniteCanvas.exe'
        self.exe.parent.mkdir();self.exe.write_bytes(b'TEST NOT EXECUTABLE')
        self.cfg=self.root/'codex'/'config.toml';self.cfg.parent.mkdir()
        self.raw=b'# keep this comment\nmodel_reasoning_effort = "ultra"\n[mcp_servers.other]\ncommand = "other"\n'
        self.cfg.write_bytes(self.raw);self.workspace=self.root/'media'
    def run_setup(self,apply=False,**kw):
        args=dict(config=self.cfg,exe=self.exe,workspace=self.workspace,port=18765,token='fixture-only-token',apply=apply);args.update(kw)
        return setup.configure(**args)
    def test_preview_writes_nothing(self):
        result=self.run_setup();self.assertFalse(result['applied'])
        self.assertEqual(self.cfg.read_bytes(),self.raw);self.assertFalse(self.workspace.exists())
        self.assertFalse((self.cfg.parent/'muse-long-video.local.json').exists())
    def test_apply_preserves_unrelated_settings_and_backup(self):
        self.run_setup(True);b=self.cfg.read_bytes();self.assertTrue(b.startswith(self.raw))
        d=setup.read_config(self.cfg)[1]
        self.assertEqual(d['model_reasoning_effort'],'ultra');self.assertEqual(d['mcp_servers']['other']['command'],'other')
        self.assertEqual(d['mcp_servers']['synmew-canvas']['command'],str(self.exe))
        backups=list(self.cfg.parent.glob('config.toml.before-synmew-*'));self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),self.raw)
        local=json.loads((self.cfg.parent/'muse-long-video.local.json').read_text('utf8'))
        self.assertNotIn('fixture-only-token',json.dumps(local));self.assertTrue((self.workspace/'Outputs').is_dir())
    def test_second_apply_has_no_duplicate_server_or_backup(self):
        self.run_setup(True);original=self.cfg.read_bytes();result=self.run_setup(True)
        self.assertEqual(result['config_action'],'already_configured');self.assertEqual(original,self.cfg.read_bytes())
        self.assertEqual(len(list(self.cfg.parent.glob('config.toml.before-synmew-*'))),1)
    def test_conflicting_token_does_not_overwrite(self):
        self.run_setup(True);original=self.cfg.read_bytes()
        with self.assertRaises(ValueError):self.run_setup(True,token='different-fixture-token')
        self.assertEqual(original,self.cfg.read_bytes())
    def test_invalid_port_no_writes(self):
        with self.assertRaises(ValueError):self.run_setup(True,port=0)
        self.assertEqual(self.cfg.read_bytes(),self.raw)
    def test_missing_exe_no_writes(self):
        with self.assertRaises(ValueError):self.run_setup(True,exe=self.root/'missing.exe')
        self.assertEqual(self.cfg.read_bytes(),self.raw)
    def test_new_config_and_unicode_pairing(self):
        new=self.root/'fresh'/'config.toml';self.run_setup(True,config=new,token='fixture-quote-"-slash-\\')
        d=setup.read_config(new)[1];self.assertEqual(d['mcp_servers']['synmew-canvas']['env']['SYNMEW_MCP_TOKEN'],'fixture-quote-"-slash-\\')
    def test_disabled_server_is_not_silently_enabled(self):
        self.run_setup(True);b=self.cfg.read_bytes().replace(b'enabled = true',b'enabled = false');self.cfg.write_bytes(b)
        with self.assertRaises(ValueError):self.run_setup(True)
        self.assertEqual(self.cfg.read_bytes(),b)

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Provide an absolute test output folder')
    WORK=Path(sys.argv.pop());assert WORK.is_absolute();WORK.mkdir(parents=True,exist_ok=True)
    unittest.main(verbosity=2)
