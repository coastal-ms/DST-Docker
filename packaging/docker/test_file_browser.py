from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).parent))
import file_browser


class FileBrowserTests(unittest.TestCase):
    def setUp(self):
        self.project='a'*32
        self.state={'id':self.project,'profile':{'gamePortBase':28777},
                    'worldPlan':{'network':'dst-'+self.project+'-network','games':[
                        {'partition':1,'map':'Survival_1'},{'partition':8,'map':'DeepDesert_1'}]},
                    'services':{'game-1':{'id':'hagga','phase':'prepared'},'game-8':{'id':'dd','phase':'prepared'}}}
        self.engine=Mock(spec=['assert_owned','request','ensure_owned_volume'])
        def observed(identifier,project,component):
            return {'Mounts':[{'Destination':'/home/dune/server/DuneSandbox/Saved','Type':'volume',
                               'Name':'dst-'+project+'-'+component+'-saved'}]}
        self.engine.assert_owned.side_effect=observed
        def request(method,path,body=None):
            if path.startswith(('/volumes/','/networks/')):return {'Labels':{'io.dst.project':self.project,'io.dst.managed':'true'}}
            if path.startswith('/images/'):return {'RepoDigests':[file_browser.IMAGE]}
            return {'Id':'browser'}
        self.engine.request.side_effect=request

    def test_mounts_only_owned_saved_files_and_preserves_usual_settings_root(self):
        mounts=file_browser.saved_mounts(self.state,self.engine)
        self.assertEqual([m['Target'] for m in mounts],['/srv','/srv/Maps/DeepDesert_1-8','/srv/Maps/DeepDesert_1-8/UserSettings'])
        self.assertTrue(all(m['Source'].startswith('dst-'+self.project+'-game-') for m in mounts))
        self.assertEqual(mounts[-1]['Source'],mounts[0]['Source'])
        self.assertEqual(mounts[-1]['VolumeOptions'],{'Subpath':'UserSettings'})

    def test_foreign_or_non_volume_saved_files_fail_before_create(self):
        self.engine.assert_owned.return_value={}
        self.engine.assert_owned.side_effect=lambda *args:{'Mounts':[{'Destination':'/home/dune/server/DuneSandbox/Saved',
                                                                   'Type':'bind','Name':'foreign'}]}
        with self.assertRaises(ValueError):file_browser.saved_mounts(self.state,self.engine)
        self.engine.request.assert_not_called()

    def test_browser_is_loopback_only_nonroot_and_cannot_run_commands_or_follow_external_links(self):
        mounts=file_browser.saved_mounts(self.state,self.engine)
        file_browser.create(self.state,self.engine,mounts)
        spec=self.engine.request.call_args.args[2]
        self.assertEqual(spec['User'],'1000:1000')
        self.assertEqual(spec['HostConfig']['PortBindings']['80/tcp'],[{'HostIp':'127.0.0.1','HostPort':'29782'}])
        self.assertTrue(spec['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(spec['HostConfig']['CapDrop'],['ALL'])
        self.assertIn('--disableExec=true',spec['Cmd'])
        self.assertIn('--followExternalSymlinks=false',spec['Cmd'])
        self.assertNotIn('/var/run/docker.sock',str(spec))


if __name__=='__main__':unittest.main()
