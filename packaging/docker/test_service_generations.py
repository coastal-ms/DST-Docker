import copy
import unittest
from service_generations import replace_generation,rollback_generation,commit_generation

PROJECT='a'*32


class Resources:
    def __init__(self):
        self.rows={'old':{'Id':'old','Name':'/dst-'+PROJECT+'-game-1','State':{'Status':'created'},
            'Config':{'Labels':{'io.dst.project':PROJECT,'io.dst.component':'game-1'}},
            'Mounts':[{'Type':'volume','Name':'dst-'+PROJECT+'-game-1-saved','Destination':'/home/dune/server/DuneSandbox/Saved'}]}}
        self.mutations=[];self.lose_reply=False
    def assert_owned(self,identifier,project,component):
        row=self.rows[identifier]
        assert row['Config']['Labels']['io.dst.project']==project
        return row
    def ensure_package_image(self,*args):pass
    def retire_component(self,identifier,project,component):
        self.rows[identifier]['Name']='/retired-'+identifier;self.mutations.append(('retire',identifier));return 'retired-'+identifier
    def create_component(self,project,component,image,network,generation,**kwargs):
        self.rows['new']=copy.deepcopy(self.rows['old']);self.rows['new'].update(Id='new',Name='/dst-'+project+'-'+component)
        self.rows['new']['Config']['Labels']['io.dst.generation']=generation;self.mutations.append(('create','new'))
        if self.lose_reply:raise RuntimeError('Lost create response')
        return 'new'
    def upload_component_files(self,*args):pass
    def request(self,method,path,**kwargs):
        if method=='GET':return next((r for r in self.rows.values() if r['Name']=='/'+path.split('/')[2]),None)
        identifier=path.split('/')[2];self.rows[identifier]['Name']='/'+path.split('name=')[1];self.mutations.append(('rename',identifier))


class GenerationTests(unittest.TestCase):
    def test_failed_metadata_commit_retains_the_recoverable_generation_in_memory(self):
        state,plan,specs,engine=self.prepare();replace_generation(state,engine,specs,plan,lambda s:None,'update')
        before=copy.deepcopy(state)
        def fail(value):raise OSError('Fixture full disk')
        with self.assertRaises(OSError):commit_generation(state,fail)
        self.assertEqual(state,before)
        rollback_generation(state,engine,lambda s:None)
        self.assertEqual(state['services']['game-1']['id'],'old')
    def prepare(self):
        plan={'network':'owned','images':{'game':{'archive':'official','image':'official'}}}
        state={'id':PROJECT,'profile':{'name':'old'},'worldPlan':plan,'services':{'game-1':{'id':'old','phase':'prepared'}}}
        return state,plan,{'game-1':{'environment':{},'files':{}}},Resources()

    def test_successful_replacement_can_restore_the_exact_previous_component_and_plan(self):
        state,plan,specs,engine=self.prepare();old=copy.deepcopy(state)
        replace_generation(state,engine,specs,plan,lambda s:None,'update')
        self.assertEqual(state['services']['game-1']['id'],'new')
        rollback_generation(state,engine,lambda s:None)
        self.assertEqual(state['services'],old['services']);self.assertEqual(state['worldPlan'],old['worldPlan'])
        self.assertEqual(engine.rows['old']['Name'],'/dst-'+PROJECT+'-game-1')
        self.assertNotIn('generationChange',state)

    def test_lost_create_response_is_reconciled_by_generation_label_and_name(self):
        state,plan,specs,engine=self.prepare();engine.lose_reply=True
        with self.assertRaisesRegex(RuntimeError,'Lost create'):replace_generation(state,engine,specs,plan,lambda s:None,'update')
        self.assertNotIn('id',state['services']['game-1'])
        rollback_generation(state,engine,lambda s:None)
        self.assertEqual(state['services']['game-1']['id'],'old')
        self.assertEqual(engine.rows['new']['Name'],'/retired-new')

    def test_foreign_saved_storage_is_rejected_before_any_rename(self):
        state,plan,specs,engine=self.prepare();engine.rows['old']['Mounts'][0]['Name']='other-project-saved'
        with self.assertRaisesRegex(ValueError,'Saved'):replace_generation(state,engine,specs,plan,lambda s:None,'update')
        self.assertEqual(engine.mutations,[]);self.assertNotIn('generationChange',state)

    def test_recovery_refuses_to_retire_a_different_generation_at_the_expected_name(self):
        state,plan,specs,engine=self.prepare();replace_generation(state,engine,specs,plan,lambda s:None,'update')
        engine.rows['new']['Config']['Labels']['io.dst.generation']='b'*32
        before=list(engine.mutations)
        with self.assertRaisesRegex(ValueError,'different generation'):rollback_generation(state,engine,lambda s:None)
        self.assertEqual(engine.mutations,before)
