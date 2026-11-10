"""Shared World Restart research evidence, matching the existing recovery rule.

Capture only purchased recipes with a proven working runtime entry; recovery
resets purchases to NotPurchased so the game can rebuild its runtime normally.
"""
import json,time,re

GROUPS={
    **{key:'DA_GRP_SandbikePack' for key in (
        'RCP_T2_Vehicle(Ground)_SandBikeBodyHull_Recipe','RCP_T2_Vehicle(Ground)_SandBikeChassis_Recipe',
        'RCP_T2_SandbikeEngine_Recipe','RCP_T2_Vehicle(Ground)_SandBikeTreads_Recipe','RCP_PowerUnitVeryLightRecipe',
        'RCP_RepairToolRecipe','RCP_WeldingMaterialRecipe','RCP_T2_Vehicle(Ground)_SandBikeInventoryModule_Recipe')},
    **{'RCP_ScavengerRags_'+part+'_Recipe':'DA_GRP_ScavengerRagsArmor' for part in ('Boots','Bottom','Gloves','Helmet','Top')}}

READ_SQL="""SELECT coalesce(jsonb_agg(jsonb_build_object(
 'characterName',ps.character_name,'accountId',ps.account_id,'funcomId',ac.funcom_id,'pawnId',ps.player_pawn_id,
 'online',ps.online_status::text,
 'research',coalesce(a.properties #> '{TechKnowledgePlayerComponent,m_TechKnowledge,m_TechKnowledgeData}','[]'::jsonb),
 'researchHash',encode(sha256(convert_to(coalesce(a.properties #> '{TechKnowledgePlayerComponent,m_TechKnowledge,m_TechKnowledgeData}','[]'::jsonb)::text,'UTF8')),'hex'),
 'runtime',coalesce(a.properties #> '{CraftingRecipesLibraryActorComponent,m_KnownItemRecipes}','[]'::jsonb))
 ORDER BY ps.character_name,ps.player_pawn_id),'[]'::jsonb)
 FROM dune.player_state ps JOIN dune.actors a ON a.id=ps.player_pawn_id JOIN dune.accounts ac ON ac.id=ps.account_id
 WHERE coalesce(ac.funcom_id,'')<>''"""

def rows(sql):
    result=json.loads(sql(READ_SQL))
    if not isinstance(result,list):raise ValueError('The research evidence has an unexpected shape.')
    for row in result:
        if not isinstance(row.get('research'),list) or not isinstance(row.get('runtime'),list):raise ValueError('The research schema needs review before reset or recovery.')
    return result

def known(row):
    return {item.get('BaseRecipeId',{}).get('Name') for item in row['runtime'] if isinstance(item,dict) and isinstance(item.get('BaseRecipeId'),dict)}

def capture(sql):
    characters=[]
    for row in rows(sql):
        runtime=known(row)
        pairs=[{'itemKey':item['ItemKey'],'baseRecipeId':item['ItemKey'][4:],'groupKey':GROUPS.get(item['ItemKey'],'')}
               for item in row['research'] if isinstance(item,dict) and isinstance(item.get('ItemKey'),str) and
               item['ItemKey'].startswith('RCP_') and item.get('UnlockedState')=='Purchased' and item['ItemKey'][4:] in runtime]
        if pairs:characters.append({key:row[key] for key in ('characterName','accountId','funcomId')}|{'pairs':pairs})
    return {'capturedAt':time.time(),'characters':characters,'pairCount':sum(len(row['pairs']) for row in characters)}

def audit(sql,snapshot):
    if not snapshot:return {'available':False,'message':'No pre-restart research snapshot is available.','capturedCharacters':0,'rehydratedCharacters':0,'pendingCharacters':[],'mismatches':[]}
    current=rows(sql);pending=[];mismatches=[];returned=0
    for captured in snapshot['characters']:
        matches=[row for row in current if row['funcomId']==captured['funcomId'] and row['characterName']==captured['characterName']]
        if len(matches)>1:raise ValueError('A returning character identity is ambiguous; research recovery was blocked.')
        if not matches:pending.append(captured['characterName']);continue
        returned+=1;row=matches[0];runtime=known(row)
        for pair in captured['pairs']:
            purchases=[item for item in row['research'] if isinstance(item,dict) and item.get('ItemKey')==pair['itemKey']]
            if len(purchases)>1:raise ValueError('A research entry is duplicated; review is required.')
            if purchases and purchases[0].get('UnlockedState')=='Purchased' and pair['baseRecipeId'] not in runtime:
                mismatches.append({key:row[key] for key in ('characterName','accountId','funcomId')}|pair)
    return {'available':True,'capturedCharacters':len(snapshot['characters']),'rehydratedCharacters':returned,
            'pendingCharacters':pending,'mismatches':mismatches,
            'message':str(len(mismatches))+' purchased research item(s) are missing their pre-restart runtime recipe.' if mismatches else
            'No mismatches found among returning characters; some characters have not returned yet.' if pending else
            'All returning characters match their captured research/runtime pairs.'}

def literal(value):return "'"+str(value).replace("'","''")+"'"

def recovery_sql(sql,snapshot,character,funcom,requested):
    if (not isinstance(character,str) or not isinstance(funcom,str) or not isinstance(requested,list) or
        not 1<=len(requested)<=500 or any(not isinstance(key,str) for key in requested) or len(set(requested))!=len(requested)):
        raise ValueError('Select captured research mismatches for one character.')
    allowed=[row for row in audit(sql,snapshot)['mismatches'] if row['characterName']==character and row['funcomId']==funcom]
    if not set(requested)<=set(row['itemKey'] for row in allowed):raise ValueError('A selected item is not a current captured research mismatch.')
    selected=[row for row in allowed if row['itemKey'] in requested]
    keys=set(requested)|{row['groupKey'] for row in selected if row['groupKey']}
    current=[row for row in rows(sql) if row['characterName']==character and row['funcomId']==funcom]
    if len(current)!=1 or current[0]['online']!='Offline':raise ValueError('The selected character must be fully offline before research recovery.')
    row=current[0];entries=[item for item in row['research'] if isinstance(item,dict) and item.get('ItemKey') in keys]
    if len(entries)!=len(keys) or any(item.get('UnlockedState')!='Purchased' for item in entries):raise ValueError('Research bundle state changed before recovery; no write was prepared.')
    updated=[item|{'UnlockedState':'NotPurchased'} if isinstance(item,dict) and item.get('ItemKey') in keys else item for item in row['research']]
    pawn=int(row['pawnId']);fingerprint=row.get('researchHash','')
    if not re.fullmatch(r'[a-f0-9]{64}',fingerprint):raise ValueError('The research fingerprint could not be verified before recovery.')
    key_array='ARRAY['+','.join(literal(key) for key in sorted(keys))+']::text[]'
    query="""WITH rewritten AS (SELECT jsonb_agg(
 CASE WHEN entry->>'ItemKey'=ANY("""+key_array+""") THEN jsonb_set(entry,'{UnlockedState}','"NotPurchased"'::jsonb,true) ELSE entry END ORDER BY ord) AS data
 FROM dune.actors a CROSS JOIN LATERAL jsonb_array_elements(a.properties #> '{TechKnowledgePlayerComponent,m_TechKnowledge,m_TechKnowledgeData}') WITH ORDINALITY items(entry,ord)
 WHERE a.id="""+str(pawn)+""" AND encode(sha256(convert_to((a.properties #> '{TechKnowledgePlayerComponent,m_TechKnowledge,m_TechKnowledgeData}')::text,'UTF8')),'hex')="""+literal(fingerprint)+"""), changed AS (UPDATE dune.actors a
 SET properties=jsonb_set(a.properties,'{TechKnowledgePlayerComponent,m_TechKnowledge,m_TechKnowledgeData}',rewritten.data,true)
 FROM rewritten WHERE a.id="""+str(pawn)+""" AND rewritten.data IS NOT NULL
 AND encode(sha256(convert_to((a.properties #> '{TechKnowledgePlayerComponent,m_TechKnowledge,m_TechKnowledgeData}')::text,'UTF8')),'hex')="""+literal(fingerprint)+"""
 AND EXISTS(SELECT 1 FROM dune.player_state ps JOIN dune.accounts ac ON ac.id=ps.account_id
 WHERE ps.player_pawn_id=a.id AND ps.online_status::text='Offline' AND ps.character_name="""+literal(character)+" AND ac.funcom_id="+literal(funcom)+""" ) RETURNING a.id)
 SELECT count(*) FROM changed"""
    return query,updated,keys


def verify(sql,character,funcom,expected):
    current=[row for row in rows(sql) if row['characterName']==character and row['funcomId']==funcom]
    if len(current)!=1 or current[0]['research']!=expected:raise ValueError('The research recovery write did not verify exactly. Keep the world stopped and recover the recorded backup.')


from world_restart import NativeWorldRestart

class NativeResearchRecovery(NativeWorldRestart):
    @property
    def run(self):return self.s['worldResearchRecovery']

    def apply_research(self,confirmation,character,funcom,requested):
        if confirmation!='RESET RESEARCH':raise ValueError('Type RESET RESEARCH exactly to confirm the selected research recovery.')
        restart=self.s.get('worldRestart',{})
        if restart.get('phase')!='done' or not restart.get('researchSnapshot'):raise ValueError('A completed World Restart research snapshot is required.')
        if self.s.get('worldResearchRecovery',{}).get('phase','completed') not in {'completed','rolled-back','failed-preflight'}:raise ValueError('Recover the previous research operation first.')
        recovery_sql(self.sql,restart['researchSnapshot'],character,funcom,requested)
        self.assert_offline()
        if self.s.get('worldResearchRecovery'):self.s.setdefault('worldResearchRecoveryHistory',[]).append(self.s['worldResearchRecovery'])
        self.s['worldResearchRecovery']={'id':self.s['operation']['id'],'phase':'preflight','startedAt':time.time(),
            'previousDesired':self.s.get('desiredState','stopped'),'characterName':character,'funcomId':funcom,'itemKeys':requested,'committed':False}
        self.m.save(self.s)
        try:
            self.maintenance(True);self.assert_offline();self.phase('stopping');self.m.stop_services(self.s,self.e);self.assert_stopped()
            self.backup()
            query,expected,keys=recovery_sql(self.sql,restart['researchSnapshot'],character,funcom,requested)
            self.phase('writing',writeStarted=True,mutationKeys=sorted(keys),expectedResearch=expected)
            if self.sql(query)!='1':raise ValueError('The character research changed before recovery. No matching write was committed.')
            self.phase('verifying');verify(self.sql,character,funcom,expected)
            self.publish('completed')
        except Exception as error:
            self.run['error']=str(error);self.m.save(self.s)
            try:self.recover()
            except Exception:
                self.phase('recovery-required');raise ValueError('Research recovery needs review. Keep players offline and recover its recorded backup.') from error
            if self.run['phase']=='completed':return
            raise

    def recover(self):
        if self.run['phase'] in {'completed','rolled-back','failed-preflight'}:raise ValueError('There is no interrupted research recovery.')
        self.maintenance(True)
        if self.run.get('committed'):self.publish('completed');return
        self.m.stop_services(self.s,self.e);self.assert_stopped()
        if self.run.get('writeStarted'):
            restore=self.s.get('restore',{})
            if restore.get('phase') in {'restoring','recovering','recovery-required'} and restore.get('job'):
                try:self.m.finish_restore(self.s,self.e)
                except Exception:
                    if restore.get('phase')=='recovery-required':raise
            self.phase('restoring-research-backup')
            self.m.restore_backup(self.s,self.e,self.run['backupId'],'RESTORE',keep_maintenance=True)
            self.run['completionPhase']='rolled-back';self.publish('rolled-back')
        else:
            self.run['completionPhase']='failed-preflight';self.publish('failed-preflight')
