from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from copy import deepcopy
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
        self.assertIn('--baseURL=/api/docker/file-browser',spec['Cmd'])

    def prepared_endpoint(self):
        mounts=file_browser.saved_mounts(self.state,self.engine)
        self.state['fileBrowser']={'id':'browser','mounts':mounts,'port':29782,'baseUrl':file_browser.BASE_URL}
        observed={'Config':{'Image':file_browser.IMAGE,'User':'1000:1000','Cmd':file_browser.command()},
                  'HostConfig':{'PortBindings':{'80/tcp':[{'HostIp':'127.0.0.1','HostPort':'29782'}]},
                                'ReadonlyRootfs':True,'NetworkMode':self.state['worldPlan']['network']},
                  'Mounts':[{'Destination':m['Target'],'Name':m['Source']} for m in mounts]+[
                      {'Destination':'/database','Name':'dst-'+self.project+'-file-browser'}],
                  'State':{'Status':'running'}}
        prior=self.engine.assert_owned.side_effect
        self.engine.assert_owned.side_effect=lambda identifier,project,component:deepcopy(observed) if component=='file-browser' else prior(identifier,project,component)
        return observed

    def test_endpoint_only_returns_verified_owned_loopback_target(self):
        self.prepared_endpoint()
        self.assertEqual(file_browser.endpoint(self.state,self.engine),{'available':True,'port':29782})

    def test_unprepared_endpoint_does_not_start_or_create_anything(self):
        self.assertEqual(file_browser.endpoint(self.state,self.engine),{'available':False})
        self.engine.request.assert_not_called()

    def test_endpoint_rejects_changed_binding_image_command_mounts_and_stopped_helper(self):
        for mutation in ('port','binding','image','command','mounts','stopped'):
            with self.subTest(mutation=mutation):
                observed=self.prepared_endpoint()
                if mutation=='port':self.state['fileBrowser']['port']=8088
                if mutation=='binding':observed['HostConfig']['PortBindings']['80/tcp'][0]['HostIp']='0.0.0.0'
                if mutation=='image':observed['Config']['Image']='other-image'
                if mutation=='command':observed['Config']['Cmd']=[]
                if mutation=='mounts':observed['Mounts'].append({'Destination':'/host','Name':'foreign'})
                if mutation=='stopped':observed['State']['Status']='exited'
                if mutation=='mounts':
                    with self.assertRaisesRegex(ValueError,'storage'):file_browser.endpoint(self.state,self.engine)
                else:self.assertFalse(file_browser.endpoint(self.state,self.engine)['available'])


if __name__=='__main__':unittest.main()
