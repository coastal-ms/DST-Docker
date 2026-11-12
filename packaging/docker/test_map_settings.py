from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from settings_service import SavedSettings, SettingsConflict
import manager


class MapSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.saved=Path(self.temp.name)
        (self.saved/'UserSettings').mkdir()
        self.global_file=self.saved/'UserSettings/UserServerCustomSettings.ini'
        self.global_file.write_text('; keep comment\n[Rules]\nMultiplier=1\n+Array=keep\n')
        self.store=SavedSettings(self.saved)

    def tearDown(self):self.temp.cleanup()

    def write(self,target,raw=None,inherit=False,revision=None):
        return self.store.dispatch({'action':'maps.write','target':target,'file':'server','raw':raw,
            'inherit':inherit,'revision':revision or self.store.map_read(target,'server')['revision']})

    def test_partition_save_never_changes_global_or_another_partition(self):
        original=self.global_file.read_bytes()
        first=self.write('1','[Rules]\nMultiplier=3\n')
        self.assertTrue(first['overridden'])
        self.assertEqual(self.store.map_read('8','server')['raw'],original.decode())
        self.assertEqual(self.global_file.read_bytes(),original)
        self.write('8','[Rules]\nMultiplier=5\n')
        self.assertEqual(self.store.map_read('1','server')['raw'],'[Rules]\nMultiplier=3\n')

    def test_global_defaults_flow_to_both_supported_maps_without_replacing_an_own_copy(self):
        current=self.store.read('server')
        self.store.write('server','[Rules]\nMultiplier=2\n',current['revision'],current['fileExists'])
        for target in ('1','8'):
            self.assertFalse(self.store.map_read(target,'server')['overridden'])
            self.assertEqual(self.store.map_read(target,'server')['raw'],'[Rules]\nMultiplier=2\n')
        self.write('1','[Rules]\nMultiplier=5\n')
        current=self.store.read('server')
        self.store.write('server','[Rules]\nMultiplier=3\n',current['revision'],current['fileExists'])
        self.assertEqual(self.store.map_read('1','server')['raw'],'[Rules]\nMultiplier=5\n')
        self.assertEqual(self.store.map_read('8','server')['raw'],'[Rules]\nMultiplier=3\n')

    def test_inherited_draft_conflicts_with_global_edit_and_identical_override_creation(self):
        before=self.store.map_read('1','server')
        self.global_file.write_text('[Rules]\nMultiplier=2\n')
        with self.assertRaises(SettingsConflict):self.write('1','stale',revision=before['revision'])
        before=self.store.map_read('1','server')
        self.write('1',before['raw'])
        with self.assertRaises(SettingsConflict):self.write('1','stale',revision=before['revision'])

    def test_override_is_independent_and_reset_backs_up_then_resumes_global(self):
        self.write('1','[Rules]\nMultiplier=3\n')
        before=self.store.map_read('1','server')
        self.global_file.write_text('[Rules]\nMultiplier=9\n')
        self.assertEqual(self.store.map_read('1','server')['revision'],before['revision'])
        result=self.write('1',inherit=True)
        self.assertFalse(result['overridden'])
        self.assertEqual(result['raw'],self.global_file.read_text())
        backup=self.saved/'UserSettings/.dst-map-settings/1/UserSettings/.dst-backups'/result['backup']
        self.assertEqual(backup.read_text(),'[Rules]\nMultiplier=3\n')

    def test_invalid_targets_and_symlinked_directories_are_rejected(self):
        for target in ['../1','0','01',1,None,'9999999']:
            with self.assertRaises(ValueError):self.store.map_read(target,'server')
        root=self.saved/'UserSettings/.dst-map-settings'
        root.symlink_to(self.saved,target_is_directory=True)
        with self.assertRaises(ValueError):self.store.map_read('1','server')

    def test_inherited_source_change_during_replacement_does_not_save_a_stale_copy(self):
        before=self.store.map_read('1','server')
        real=tempfile.mkstemp
        def change(*args,**kwargs):
            self.global_file.write_text('new manual settings')
            return real(*args,**kwargs)
        with patch('settings_service.tempfile.mkstemp',side_effect=change):
            with self.assertRaises(SettingsConflict):self.write('1','stale',revision=before['revision'])
        self.assertFalse(self.store.map_read('1','server')['overridden'])

    def test_real_startup_projection_uses_each_partition_and_keeps_running_snapshot(self):
        # Execute the actual launcher through its projection boundary in an
        # isolated filesystem; never run a game, Docker, chown or system tools.
        source=(Path(__file__).parent/'native-game.sh').read_text()
        boundary=source.index('if [ -L "$settings/.dst-startup-exec-commands" ]')
        source=source[:boundary]+'\n'
        work=self.saved/'world';work.mkdir()
        shared=work/'UserSettings';shared.mkdir()
        (shared/'UserGame.ini').write_text('global-game')
        (shared/'UserEngine.ini').write_text('global-engine')
        (shared/'UserServerCustomSettings.ini').write_text('global-custom')
        store=SavedSettings(work)
        before=store.map_read('8','server')
        store.map_write({'target':'8','file':'server','raw':'dd-custom','revision':before['revision']})
        config=self.saved/'config';config.parent.mkdir(exist_ok=True)
        script=self.saved/'project.sh'
        source=source.replace('/home/dune/server/DuneSandbox/Saved',str(work)).replace("config='/home/dune/.config/Epic/Unreal Engine/Engine/Config'",'config='+str(config)).replace("mkdir -p '/home/dune/.config/Epic/Unreal Engine/Engine'",'true')
        script.write_text(source)
        subprocess.run(['sh',str(script)],env={**os.environ,'SERVER_INDEX':'8'},check=True,capture_output=True)
        self.assertEqual((work/'Config/LinuxServer/ServerCustomSettings.ini').read_text(),'dd-custom')
        self.assertEqual((config/'UserGame.ini').read_text(),'global-game')
        # A live snapshot cannot change when shared configuration is saved.
        (shared/'UserGame.ini').write_text('new-global-game')
        self.assertEqual((config/'UserGame.ini').read_text(),'global-game')
        subprocess.run(['sh',str(script)],env={**os.environ,'SERVER_INDEX':'1'},check=True,capture_output=True)
        self.assertEqual((work/'Config/LinuxServer/ServerCustomSettings.ini').read_text(),'global-custom')
        self.assertEqual((config/'UserGame.ini').read_text(),'new-global-game')


class ManagerMapSettingsTests(unittest.TestCase):
    def test_map_local_game_and_engine_files_are_rejected_without_writes(self):
        state={'id':'a'*32,'worldPlan':{'games':[{'partition':1,'map':'Survival_1'}]}}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'settings_request') as request:
            for key in ('game','engine'):
                for action in ('map-settings.read','map-settings.write'):
                    with self.assertRaisesRegex(ValueError,'only Custom Server Settings'):
                        manager.dispatch({'action':action,'target':'1','file':key},Mock())
            request.assert_not_called()

    def test_gameplay_scopes_reject_overmap_and_story_maps(self):
        state={'id':'a'*32,'worldPlan':{'games':[{'partition':2,'map':'Overmap'},{'partition':3,'map':'SH_Arrakeen'},{'partition':9,'map':'CB_Story_Test'}]}}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'settings_request') as request:
            for target in ('2','3','9'):
                for action in ('map-settings.read','map-settings.write'):
                    with self.assertRaisesRegex(ValueError,'only to Hagga and Deep Desert'):
                        manager.dispatch({'action':action,'target':target,'file':'server'},Mock())
            request.assert_not_called()

    def test_global_target_uses_existing_global_read_and_guarded_write(self):
        state={'id':'a'*32,'worldPlan':{'games':[]}}
        current={'fileExists':True,'raw':'global','revision':'a'*64}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'read_settings',return_value=current),patch.object(manager,'write_settings',return_value=current) as write:
            result=manager.dispatch({'action':'map-settings.read','target':'global','file':'server'},Mock())
            self.assertEqual(result['raw'],'global')
            self.assertFalse(result['overridden'])
            manager.dispatch({'action':'map-settings.write','target':'global','file':'server','revision':'a'*64,'raw':'new','inherit':False},Mock())
            self.assertEqual(write.call_args.args[2],{'file':'server','revision':'a'*64,'raw':'new','expectedExists':True})
            with self.assertRaisesRegex(ValueError,'cannot inherit'):
                manager.dispatch({'action':'map-settings.write','target':'global','file':'server','inherit':True},Mock())

    def test_foreign_partition_and_legacy_adapter_cannot_receive_writes(self):
        state={'id':'a'*32,'worldPlan':{'games':[{'partition':1,'map':'Survival_1'}]},'services':{'game-1':{'id':'own'}}}
        engine=Mock(spec=['assert_owned'])
        engine.assert_owned.return_value={'Config':{'Env':[]},'State':{'Status':'exited'}}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'settings_request') as request:
            with self.assertRaisesRegex(ValueError,'from this world'):manager.dispatch({'action':'map-settings.write','target':'8','file':'server'},engine)
            with self.assertRaisesRegex(ValueError,'Update this map adapter'):manager.dispatch({'action':'map-settings.write','target':'1','file':'server'},engine)
            request.assert_not_called()

    def test_saved_map_stays_pending_until_new_map_process_starts(self):
        state={'id':'a'*32,'worldPlan':{'games':[{'partition':1,'map':'Survival_1'}]},'services':{'game-1':{'id':'own'}}}
        engine=Mock(spec=['assert_owned'])
        observed={'Config':{'Env':['DST_MAP_SETTINGS_VERSION=1']},'State':{'Status':'running','StartedAt':'2026-11-08T00:00:00Z'}}
        engine.assert_owned.return_value=observed
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save'),patch.object(manager,'settings_request',return_value={'changed':True}):
            self.assertTrue(manager.dispatch({'action':'map-settings.write','target':'1','file':'server'},engine)['pendingRestart'])
            self.assertTrue(manager.dispatch({'action':'map-settings.read','target':'1','file':'server'},engine)['pendingRestart'])
            observed['State']['StartedAt']='2099-01-01T00:00:00Z'
            self.assertFalse(manager.dispatch({'action':'map-settings.read','target':'1','file':'server'},engine)['pendingRestart'])

    def test_global_edit_marks_only_inheriting_maps_pending_until_their_next_start(self):
        state={'id':'a'*32,'globalSettingsPending':{'server':2000000000},'worldPlan':{'games':[{'partition':1,'map':'Survival_1'}]},'services':{'game-1':{'id':'own'}}}
        engine=Mock(spec=['assert_owned'])
        observed={'Config':{'Env':['DST_MAP_SETTINGS_VERSION=1']},'State':{'Status':'running','StartedAt':'2026-11-08T00:00:00Z'}}
        engine.assert_owned.return_value=observed
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'settings_request',return_value={'overridden':False}) as request:
            self.assertTrue(manager.dispatch({'action':'map-settings.read','target':'1','file':'server'},engine)['pendingRestart'])
            request.return_value={'overridden':True}
            self.assertFalse(manager.dispatch({'action':'map-settings.read','target':'1','file':'server'},engine)['pendingRestart'])
            request.return_value={'overridden':False};observed['State']['StartedAt']='2099-01-01T00:00:00Z'
            self.assertFalse(manager.dispatch({'action':'map-settings.read','target':'1','file':'server'},engine)['pendingRestart'])


if __name__=='__main__':unittest.main()
