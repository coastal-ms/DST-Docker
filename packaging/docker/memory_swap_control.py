"""Durable typed Memory Swap operations and read-only host observations."""
import copy
import time

import memory_swap

_CACHE = {}


def host_job(state, engine, save, request=None, pending=None):
    read_only = request is None
    identifier = pending.get('hostJob') if pending else None
    if not identifier:
        identifier = engine.create_host_swap_job(state['id'], request or {'action': 'status'})
        if pending is not None:
            pending['hostJob'] = identifier; save(state)
    end = time.monotonic() + (30 if read_only else 900)
    while True:
        observed = engine.assert_owned(identifier, state['id'], 'host-memory-swap')
        phase = observed['State']['Status']
        if phase == 'created': engine.lifecycle(identifier, state['id'], 'start')
        elif phase == 'exited':
            report = engine.backup_report(identifier, state['id'], 'host-memory-swap')
            if not report.get('ok'):
                raise ValueError(report.get('error', 'The host Memory Swap operation needs recovery.'))
            # Retain mutation-job identity until the owning operation commits.
            if read_only: engine.request('DELETE', '/containers/' + identifier + '?v=false', expected=(204,))
            return report['data']
        elif phase not in {'running', 'restarting'}:
            raise ValueError('The host Memory Swap helper needs recovery.')
        if time.monotonic() >= end:
            raise ValueError('The host Memory Swap helper is still pending. Check its recorded operation before retrying.')
        time.sleep(.25)


def snapshot(state, engine, refresh=False):
    project = state['id']
    cached = _CACHE.get(project)
    if refresh or not cached or time.monotonic() - cached[0] >= 30:
        try:
            host = host_job(state, engine, lambda value: None)
            host['available'] = True
        except Exception as error:
            host = {'available': False, 'error': str(error)}
        _CACHE[project] = (time.monotonic(), host)
    else: host = cached[1]
    policy = state.get('memorySwap') or {}
    services=engine_swap_services(state, engine)
    running = sum(row.get('state') == 'running' for row in services)
    existing = host.get('existingSwapBytes', 0)
    return {**host, 'enabled': policy.get('enabled') is True,
            'perServerGiB': policy.get('perServerGiB', 2), 'poolGiB': policy.get('poolGiB', 0),
            'configuredSwappiness': policy.get('swappiness', 10),
            'requiresDefaultRestore':policy.get('enabled') is not True and any(row.get('memory',0)>0 and row.get('combined')!=row['memory']*2 for row in services),
            'worldServerCount': max(2, running), 'existingSwapGiB': (existing + memory_swap.GIB - 1) // memory_swap.GIB,
            'recommendedPoolGiB': memory_swap.recommended_pool(policy.get('perServerGiB') or 2, running, existing),
            'pending': bool(state.get('pendingSwapChange')),
            'pendingChange': state.get('pendingSwapChange'),
            'operation': {key:state.get('operation',{}).get(key) for key in ['id','phase','error']}}


def engine_swap_services(state, engine):
    rows=[]
    for component,entry in state.get('services',{}).items():
        if not component.startswith('game-'):continue
        observed=engine.assert_owned(entry['id'],state['id'],component)
        rows.append({'component':component,'state':observed['State']['Status'],
                     'memory':observed.get('HostConfig',{}).get('Memory',0),
                     'combined':observed.get('HostConfig',{}).get('MemorySwap',0)})
    return rows


def configure(state, engine, save, request, recovering=False):
    desired = memory_swap.validate(request)
    pending = state.get('pendingSwapChange')
    if pending and pending['desired'] != desired:
        raise ValueError('Retry or restore the pending Memory Swap operation before choosing another policy.')
    if not pending:
        engine.assert_swap_supported()
        for component,entry in state.get('services',{}).items():
            if component.startswith('game-'):
                observed=engine.assert_owned(entry['id'],state['id'],component)
                memory_swap.total_limit(observed['HostConfig']['Memory'],desired)
        pending = {'desired': desired, 'previous': copy.deepcopy(state.get('memorySwap') or {'enabled': False}),
                   'phase': 'preparing', 'startedAt': time.time()}
        state['pendingSwapChange'] = pending; save(state)
    if recovering and pending.get('error'):
        identifier = pending.get('hostJob')
        if identifier:
            observed = engine.assert_owned(identifier, state['id'], 'host-memory-swap')
            if observed['State']['Status'] in {'running', 'restarting'}:
                raise ValueError('The recorded host swap helper is still running; wait before retrying.')
            pending.setdefault('previousJobs', []).append(identifier)
            pending.pop('hostJob', None)
        pending.pop('error', None); save(state)
    host_request = {**desired, 'action': 'configure', 'confirmation': request['confirmation']}
    try:
        if desired['enabled']:
            pending['phase'] = 'host'; save(state)
            host_job(state, engine, save, host_request, pending)
        pending['phase'] = 'containers'; save(state)
        for component, entry in state.get('services', {}).items():
            if component.startswith('game-'):
                engine.set_component_swap(entry['id'], state['id'], component, desired)
        if not desired['enabled']:
            # Restore container defaults before evacuating only our host swap.
            pending['phase'] = 'host'; save(state)
            host_job(state, engine, save, host_request, pending)
        state['memorySwap'] = desired
        if state.get('worldPlan'):state['worldPlan']['memorySwap']=copy.deepcopy(desired)
        state['lastSwapChange'] = {**pending, 'phase': 'completed', 'finishedAt': time.time()}
        state.pop('pendingSwapChange'); save(state)
        _CACHE.pop(state['id'], None)
        return snapshot(state, engine, refresh=True)
    except Exception as error:
        pending.update(phase='failed', error=str(error)); save(state)
        _CACHE.pop(state['id'], None)
        raise


def recover(state, engine, save, restore_previous=False):
    pending = state.get('pendingSwapChange')
    if not pending: raise ValueError('There is no pending Memory Swap operation.')
    if restore_previous:
        identifier = pending.get('hostJob')
        if identifier and engine.assert_owned(identifier, state['id'], 'host-memory-swap')['State']['Status'] in {'running', 'restarting'}:
            raise ValueError('The recorded host swap helper is still running; wait before restoring the previous policy.')
        if identifier: pending.setdefault('previousJobs', []).append(identifier)
        pending.pop('hostJob', None)
        previous=copy.deepcopy(pending['previous'])
        pending['desired'] = memory_swap.validate({**previous, 'confirmation':memory_swap.CONFIRM_ENABLE if previous['enabled'] else memory_swap.CONFIRM_DISABLE})
        pending['error'] = 'Restoring the previous Memory Swap policy.'
        save(state)
    desired = pending['desired']
    return configure(state, engine, save, {**desired,
                     'confirmation': memory_swap.CONFIRM_ENABLE if desired['enabled'] else memory_swap.CONFIRM_DISABLE}, recovering=True)
