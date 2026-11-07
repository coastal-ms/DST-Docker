"""Persistent game resource allocations and admission within the Linux host."""
import math
import os
from pathlib import Path

GIB = 1024 ** 3
SERVICE_RESERVE = 2 * GIB


def host_capacity():
    counters = {line.split(':', 1)[0]: int(line.split(':', 1)[1].split()[0]) * 1024
                for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:', 'MemAvailable:'))}
    memory = counters['MemTotal']
    cpus = float(len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)
    try:
        limit = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if limit != 'max': memory = min(memory, int(limit))
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max': cpus = min(cpus, int(quota) / int(period))
    except FileNotFoundError:
        pass
    return {'memoryBytes': memory, 'availableBytes': min(memory, counters['MemAvailable']), 'cpus': cpus}


def snapshot(state, engine):
    host = host_capacity()
    policy = state.get('resourcePolicy', {})
    memory = policy.get('memoryGiB', max(1, math.floor(host['memoryBytes'] / GIB) - 2))
    cpus = policy.get('cpuCount', host['cpus'])
    maps = []
    reserved_memory = 0
    reserved_cpu = 0
    for row in state.get('worldPlan', {}).get('maps', []):
        running = 0
        for partition in row['partitions']:
            entry = state.get('services', {}).get('game-' + str(partition))
            if entry and engine.assert_owned(entry['id'], state['id'], 'game-' + str(partition))['State']['Status'] == 'running':
                running += 1
        cpu = state.get('mapCpuOverrides', {}).get(row['map'], 1)
        maps.append({'map': row['map'], 'memoryGiB': row['memoryBytes'] / GIB, 'cpus': cpu,
                     'runningInstances': running, 'initialInstances': row['initialReplicas']})
        reserved_memory += running * row['memoryBytes']
        reserved_cpu += running * cpu
    return {'host': host, 'memoryGiB': memory, 'cpuCount': cpus, 'serviceReserveGiB': 2,
            'reservedMemoryGiB': reserved_memory / GIB, 'reservedCpus': reserved_cpu,
            'configured': bool(policy), 'maps': maps, 'pending': bool(state.get('pendingResourceChange')),
            'pendingAllocation': state.get('pendingResourceChange'),
            'worldRunning': state.get('desiredState') == 'running' or any(row['runningInstances'] for row in maps)}


def validate_change(state, request, host):
    memory, cpu, maps = request.get('memoryGiB'), request.get('cpuCount'), request.get('maps')
    if type(memory) is not int or not 3 <= memory <= math.floor(host['memoryBytes'] / GIB) - 2:
        raise ValueError('Choose a server RAM budget of at least 3 GiB, leaving 2 GiB for the host.')
    if type(cpu) not in (int, float) or not math.isfinite(cpu) or not 1 <= cpu <= host['cpus']:
        raise ValueError('Choose a game CPU budget within the CPUs available to Docker.')
    rows = {row['map']: row for row in state.get('worldPlan', {}).get('maps', [])}
    if not isinstance(maps, list) or len(maps) != len(rows):
        raise ValueError('Supply allocations for every installed map.')
    seen = set()
    memory_total = SERVICE_RESERVE
    cpu_total = 0
    for item in maps:
        name = item.get('map') if isinstance(item, dict) else None
        if not isinstance(name,str) or name not in rows or name in seen: raise ValueError('Choose each installed map exactly once.')
        seen.add(name)
        ram, cores = item.get('memoryGiB'), item.get('cpus')
        if type(ram) not in (int,float) or not math.isfinite(ram) or not .25 <= ram <= min(128, memory - 2) or ram*4 != int(ram*4):
            raise ValueError('Choose map RAM in 0.25 GiB steps within the server budget.')
        if type(cores) not in (int, float) or not math.isfinite(cores) or not .25 <= cores <= cpu:
            raise ValueError('Each map needs a CPU limit between 0.25 and the game CPU budget.')
        row = rows[name]
        # Include saved start targets, not only stock defaults.
        initial = sum(state.get('mapTargets', {}).get('game-' + str(p), 'running' if i < row['initialReplicas'] else 'stopped') == 'running'
                      for i, p in enumerate(row['partitions']))
        memory_total += initial * ram * GIB
        cpu_total += initial * cores
    if memory_total > memory * GIB or cpu_total > cpu:
        raise ValueError('The selected startup maps exceed the server RAM or game CPU budget. Adjust their sizes or stop an unused map.')
    return {'memoryGiB': memory, 'cpuCount': cpu, 'maps': maps}


def admit(state, engine, partitions):
    policy = state.get('resourcePolicy')
    if not policy: return
    if state.get('pendingResourceChange'): raise ValueError('Finish the pending resource allocation before starting maps.')
    selected = set(partitions)
    for component, entry in state.get('services', {}).items():
        if component.startswith('game-') and engine.assert_owned(entry['id'], state['id'], component)['State']['Status'] == 'running':
            selected.add(int(component[5:]))
    memory, cpus = SERVICE_RESERVE, 0
    for row in state['worldPlan']['maps']:
        count = len(selected.intersection(row['partitions']))
        memory += count * row['memoryBytes']
        cpus += count * state.get('mapCpuOverrides',{}).get(row['map'],1)
    if memory > policy['memoryGiB'] * GIB or cpus > policy['cpuCount']:
        raise ValueError('Starting these maps would exceed the configured server RAM or game CPU budget.')
