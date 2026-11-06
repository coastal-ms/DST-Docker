"""Replace stopped owned components while retaining a recoverable generation."""
import copy
import time
import uuid


def collection(component):return 'connections' if component.startswith('rmq-') else 'services'


def replace_generation(state,engine,specifications,plan,persist,purpose,previous_plan=None,previous_profile=None):
    if state.get('generationChange'):raise ValueError('Recover the previous component replacement before starting another.')
    old={}
    # Validate every old component and Saved mount before the first rename.
    for component in specifications:
        entry=state.get(collection(component),{}).get(component)
        old[component]=copy.deepcopy(entry)
        if entry:
            observed=engine.assert_owned(entry['id'],state['id'],component)
            if entry['phase']!='prepared' or observed['State']['Status'] not in {'created','exited'}:
                raise ValueError('Every component must finish stopping before replacement.')
            if component.startswith('game-'):
                saved=[m for m in observed.get('Mounts',[]) if m.get('Destination')=='/home/dune/server/DuneSandbox/Saved']
                if len(saved)!=1 or saved[0].get('Type')!='volume' or saved[0].get('Name')!='dst-'+state['id']+'-'+component+'-saved':
                    raise ValueError('Existing game Saved storage needs review; no components were replaced.')
        source=plan['images']['game' if component.startswith('game-') else component]
        engine.ensure_package_image(source['archive'],source['image'])
    journal={'id':uuid.uuid4().hex,'phase':'replacing','purpose':purpose,'old':old,
             'previousPlan':copy.deepcopy(previous_plan if previous_plan is not None else state['worldPlan']),
             'previousProfile':copy.deepcopy(previous_profile if previous_profile is not None else state['profile'])}
    state['generationChange']=journal;persist(state)
    for component,original_spec in specifications.items():
        spec=copy.deepcopy(original_spec);entries=state.setdefault(collection(component),{})
        entry={'phase':'retiring','generation':journal['id']};entries[component]=entry;persist(state)
        if old[component]:
            entry['previousName']=engine.retire_component(old[component]['id'],state['id'],component);persist(state)
        entry['phase']='creating';persist(state)
        files=spec.pop('files');source=plan['images']['game' if component.startswith('game-') else component]
        identifier=engine.create_component(state['id'],component,source['image'],plan['network'],generation=journal['id'],**spec)
        entry.update(id=identifier,phase='configuring');persist(state)
        engine.upload_component_files(identifier,state['id'],component,files)
        entry['phase']='prepared';persist(state)
    journal['phase']='prepared';persist(state)
    return journal


def rollback_generation(state,engine,persist):
    journal=state.get('generationChange')
    if not journal:raise ValueError('There is no component generation to recover.')
    journal['phase']='rolling-back';persist(state)
    for component,previous in reversed(list(journal['old'].items())):
        canonical='dst-'+state['id']+'-'+component
        found=engine.request('GET','/containers/'+canonical+'/json',expected=(200,404))
        if found and (not previous or found['Id']!=previous['id']):
            labels=found.get('Config',{}).get('Labels',{})
            if labels.get('io.dst.generation')!=journal['id']:
                raise ValueError('The replacement name belongs to a different generation. Recovery stopped.')
            engine.assert_owned(found['Id'],state['id'],component)
            if found['State']['Status'] in {'running','restarting'}:engine.lifecycle(found['Id'],state['id'],'stop')
            engine.retire_component(found['Id'],state['id'],component)
        entries=state.setdefault(collection(component),{})
        if previous:
            observed=engine.assert_owned(previous['id'],state['id'],component)
            if observed.get('Name','').lstrip('/')!=canonical:
                engine.request('POST','/containers/'+previous['id']+'/rename?name='+canonical)
            entries[component]=previous
        else:entries.pop(component,None)
        persist(state)
    state['worldPlan']=journal['previousPlan'];state['profile']=journal['previousProfile']
    journal['phase']='rolled-back';journal['finishedAt']=time.time()
    state.setdefault('generationHistory',[]).append(journal);state.pop('generationChange');persist(state)
    return {'rolledBack':True,'components':len(journal['old'])}


def commit_generation(state,persist):
    journal=state.get('generationChange')
    if not journal or journal['phase']!='prepared':raise ValueError('The component generation is not ready to commit.')
    candidate=copy.deepcopy(state);journal=candidate['generationChange']
    journal['phase']='committed';journal['finishedAt']=time.time()
    candidate.setdefault('generationHistory',[]).append(journal);candidate.pop('generationChange')
    persist(candidate)
    state.clear();state.update(candidate)
