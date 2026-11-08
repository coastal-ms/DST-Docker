"""Native backup scheduling policy. No browser, cron, SSH or game lifecycle."""
from datetime import datetime,timedelta,timezone
import re
import uuid

PRESETS={'Off':'Disabled','Hourly':'Every hour (on the hour)','Every6Hours':'Every6 hours',
         'DailyUtc04':'Daily at04:00','TwiceDailyUtc':'Twice daily (04:00 and16:00)',
         'WeeklyMonUtc04':'Weekly, Monday04:00'}


def settings(state):
    value=state.get('backupSchedule') or {'preset':'Off','keepLast':0,'keepLastPods':10,'keepDaysPods':0}
    if not isinstance(value,dict) or not isinstance(value.get('preset'),str) or value['preset'] not in PRESETS:raise ValueError('The saved backup preset needs review.')
    for key,maximum in [('keepLast',1000),('keepLastPods',100),('keepDaysPods',365)]:
        if type(value.get(key)) is not int or not 0<=value[key]<=maximum:raise ValueError('The saved backup retention needs review.')
    return value


def configure(state,request,now):
    value={key:request.get(key,default) for key,default in [('preset','Off'),('keepLast',0),('keepLastPods',10),('keepDaysPods',0)]}
    settings({'backupSchedule':value})
    value.update(configuredAt=now,revision=uuid.uuid4().hex)
    state['backupSchedule']=value
    return value


def slot(preset,now):
    if preset=='Off':return None
    if preset not in PRESETS:raise ValueError('Choose a supported backup preset.')
    current=datetime.fromtimestamp(now,timezone.utc).replace(minute=0,second=0,microsecond=0)
    if preset=='Every6Hours':current=current.replace(hour=(current.hour//6)*6)
    elif preset in {'DailyUtc04','TwiceDailyUtc','WeeklyMonUtc04'}:
        hours=[4,16] if preset=='TwiceDailyUtc' else [4]
        eligible=[current.replace(hour=hour) for hour in hours if current>=current.replace(hour=hour)]
        current=max(eligible) if eligible else (current-timedelta(days=1)).replace(hour=max(hours))
        if preset=='WeeklyMonUtc04':current-=timedelta(days=current.weekday())
    return current.timestamp()


def due(state,now):
    config=settings(state);at=slot(config['preset'],now)
    if at is None or at<float(config.get('configuredAt',now)) or now-at>1800:return None
    # Changing retention or disabling/re-enabling within the same slot does
    # not authorize another backup of that slot.
    run=state.get('scheduledBackup',{})
    if isinstance(run.get('slot'),(int,float)) and at<=run['slot']:return None
    return at


def retained_ids(state,keep):
    rows=sorted(((key,value) for key,value in state.get('backups',{}).items() if value.get('phase')=='completed'),
                key=lambda row:row[1]['createdAt'],reverse=True)
    protected={value.get('backupId') for value in (state.get('restore',{}),state.get('updateRun',{}))}
    if rows:protected.add(rows[0][0])
    mirror=state.get('backupMirror',{});run=mirror.get('run',{})
    if run.get('phase') in {'preparing','running','failed'}:protected.update(run.get('backupIds',[]))
    if mirror.get('enabled'):
        protected.update(key for key,value in rows if mirror.get('mirrored',{}).get(value['name'],{}).get('sha256')!=value.get('sha256'))
    return [key for key,value in rows[max(1,keep):] if key not in protected
            and value.get('verification',{}).get('phase') not in {'preparing','running'}
            and value.get('export',{}).get('phase') not in {'preparing','running'}
            and re.fullmatch(r'[a-f0-9]{64}',value.get('sha256',''))] if keep else []


def snapshot(state,now,worker_alive):
    config=settings(state)
    return {**{key:config[key] for key in ('preset','keepLast','keepLastPods','keepDaysPods')},
            'enabled':config['preset']!='Off','vmTimezone':'UTC',
            'vmNowUtc':datetime.fromtimestamp(now,timezone.utc).isoformat(),
            'crondRunning':worker_alive,'crondStatusRaw':state.get('backupSchedulerError') or 'Docker backup worker; runs independently of the browser.',
            'hasUnmanagedBackupLines':False,'managedBlockLooksTampered':False,'inferredFromUnmanaged':False,
            'presets':[{'id':key,'label':value} for key,value in PRESETS.items()],
            'backend':'docker','schedulerError':state.get('backupSchedulerError'),
            'lastRun':{key:state['scheduledBackup'][key] for key in ('phase','error','startedAt','finishedAt') if key in state['scheduledBackup']} if state.get('scheduledBackup') else None,
            'cleanup':{key:state['backupCleanup'][key] for key in ('phase','error') if key in state['backupCleanup']} if state.get('backupCleanup') else None}


def history(state,recent=10):
    if type(recent) is not int or not 1<=recent<=5000:raise ValueError('Choose between one and5000 recent backups.')
    rows=sorted((value for value in state.get('backups',{}).values() if value.get('phase')=='completed'),key=lambda value:value['createdAt'],reverse=True)
    return {'recent':[{'path':'/backups/'+value['name'],'sizeBytes':value['bytes'],'mtimeEpoch':value['createdAt'],
                       'mtimeIso':datetime.fromtimestamp(value['createdAt'],timezone.utc).isoformat(),
                       'verificationPhase':value.get('verification',{}).get('phase','unverified'),
                       'verificationError':value.get('verification',{}).get('error','')} for value in rows[:recent]],
            'total':len(rows),'dumpDirPath':'/backups','dumpDirSize':str(sum(value['bytes'] for value in rows))+' bytes',
            'logPath':'Docker backup operation history',
            'logTail':'\n'.join(value.get('error') or (value['name']+': '+value['phase'])
                               for value in sorted(state.get('backups',{}).values(),key=lambda value:value['createdAt'],reverse=True)[:50])}
