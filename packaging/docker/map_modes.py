"""Map lifecycle policy decisions. No timers, I/O or game starts here."""
MODES={'dynamic','always-on','overmap-active','disabled'}
IDLE_SECONDS=60


def mode_for(state,row):
    if row.get('initialReplicas',0)>0:return 'core'
    explicit=state.get('mapModes',{}).get(row['map'])
    if explicit in MODES:return explicit
    return 'always-on' if any(state.get('manualPins',{}).get('game-'+str(partition),False) for partition in row['partitions']) else 'dynamic'


def overmap_floor(players,map_players,idle_since,now):
    # Unknown occupancy never authorizes automatic shutdown.
    if players is None:return None,None
    if players>0:return True,None
    since=now if idle_since is None else idle_since
    if now-since<IDLE_SECONDS or map_players is None or map_players>0:return None,since
    return False,since
