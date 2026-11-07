"""Explicit stopped-world Tank opt-in and recoverable Hagga adapter changes."""
import copy
import re
import time
from datetime import datetime

from core_services import game_spec
from regis_artifacts import Builder, accepted_source, inspect_compatibility_image
from regis_job import OVERLAY, OVERLAY_HASHES
import service_generations


def hagga_components(state):
    plan = state.get('worldPlan') or {}
    return ['game-' + str(game['partition']) for game in plan.get('games', [])
            if game.get('map') == 'Survival_1' and 'game-' + str(game['partition']) in state.get('services', {})]


def apply_image_policy(state, partition, spec, policy=None, plan=None):
    plan = plan or state['worldPlan']
    if policy is None:
        policy = state.get('regisSupport') or {}
    selected = next((game for game in plan['games'] if game['partition'] == partition), None)
    if selected and selected['map'] == 'Survival_1' and policy.get('enabled') is True:
        identifier = policy.get('image', '')
        if not isinstance(identifier, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', identifier):
            raise ValueError('The selected Tank compatibility image needs recovery before creating a Hagga map.')
        spec['regis_image'] = identifier
    return spec


def assert_prepared_images(state, engine, components=None):
    if state.get('pendingRegisChange'):
        raise ValueError('Finish or restore the pending Tank change in Server Settings before starting maps.')
    policy = state.get('regisSupport') or {}
    if not policy.get('enabled'):
        return
    official = state['worldPlan']['images']['game']['image']
    image = inspect_compatibility_image(engine, state['id'], official, policy.get('image', ''))
    for component in hagga_components(state):
        if components is not None and component not in components:
            continue
        entry = state['services'][component]
        observed = engine.assert_owned(entry['id'], state['id'], component)
        if observed.get('Image') != image['Id'] or entry.get('phase') != 'prepared':
            raise ValueError('A Hagga adapter does not match the chosen Tank setting. Stop the world and reapply Tank support in Server Settings.')


def status(state, engine):
    policy = state.get('regisSupport') or {}
    pending = state.get('pendingRegisChange')
    reply = {'enabled': policy.get('enabled') is True, 'supported': False, 'legacyPending': False,
             'updateSupported': False, 'recoveryRequired': bool(pending and state.get('operation', {}).get('phase') != 'running'),
             'pending': bool(pending), 'phase': (pending or {}).get('phase'), 'message': ''}
    if not state.get('worldPlan') or not hagga_components(state):
        reply['message'] = 'Prepare Hagga Basin in Docker Setup before choosing Tank support.'
        return reply
    try:
        recipe, _ = accepted_source(engine, state['worldPlan']['images']['game']['image'])
        reply.update(supported=True, build=recipe['build'])
    except (ValueError, OSError):
        reply['message'] = 'This installed server image has no accepted Tank compatibility recipe.'
        return reply
    if pending:
        reply['message'] = ('Tank preparation is in progress.' if not reply['recoveryRequired'] else
                            'The Tank change needs recovery. Stop the world, then restore the previous Tank setting here.')
    elif reply['enabled']:
        reply['message'] = 'Tank compatibility is selected. Disable it before a normal server update; saved Tanks require compatibility.'
    else:
        reply['message'] = 'Tank compatibility is disabled.'
    return reply


def support(state, engine):
    unavailable = {'enabled': False, 'map': 'HaggaBasin'}
    if not (state.get('regisSupport') or {}).get('enabled'):
        return {**unavailable, 'message': 'Enable Tank compatibility in Server Settings before granting Tanks.'}
    if state.get('pendingRegisChange') or state.get('operation', {}).get('phase') == 'running':
        return {**unavailable, 'message': 'Wait for the current server operation before granting Tanks.'}
    if state.get('desiredState') != 'running':
        return {**unavailable, 'message': 'Regis Tank grants require a ready Hagga server.'}
    assert_prepared_images(state, engine)
    director = state.get('services', {}).get('director')
    if not director or not director.get('id'):
        return {**unavailable, 'message': 'Hagga readiness is unavailable.'}
    heartbeats = engine.game_heartbeats(director['id'], state['id'])
    recipe, _ = accepted_source(engine, state['worldPlan']['images']['game']['image'])
    expected = {'/home/dune/server/DuneSandbox/Binaries/Linux/DuneSandboxServer-Linux-Shipping': recipe['patchedExecutableSha256']}
    expected.update({'/home/dune/server/DuneSandbox/Content/Paks/' + OVERLAY + '.' + ext: value for ext, value in OVERLAY_HASHES.items()})
    running = 0
    for component in hagga_components(state):
        identifier = state['services'][component]['id']
        observed = engine.assert_owned(identifier, state['id'], component)
        if observed['State']['Status'] != 'running':
            continue
        heartbeat = heartbeats.get(int(component.removeprefix('game-'))) or {}
        started = datetime.fromisoformat(observed['State']['StartedAt'].replace('Z', '+00:00')).timestamp()
        if not heartbeat.get('ready') or heartbeat.get('observedAt', 0) < started:
            return {**unavailable, 'message': 'Hagga is not ready.'}
        raw = engine.exec_internal(identifier, state['id'], component, ['/usr/bin/sha256sum', *expected])
        actual = {path: value for value, path in re.findall(r'([a-f0-9]{64})\s+(/[^\r\n]+)', raw)}
        if actual != expected:
            return {**unavailable, 'message': 'The running Hagga Tank compatibility files did not pass verification.'}
        running += 1
    if not running:
        return {**unavailable, 'message': 'Regis Tank grants require a ready Hagga server.'}
    return {'enabled': True, 'map': 'HaggaBasin', 'build': recipe['build'], 'message': 'Regis Tank compatibility is enabled.'}


class Compatibility:
    def __init__(self, state, engine, manager):
        self.state, self.engine, self.m = state, engine, manager

    def stopped(self, partial=False):
        if self.state.get('desiredState') != 'stopped':
            raise ValueError('Stop the battlegroup completely before changing Tank compatibility.')
        entries = {name: row for name, row in self.state.get('services', {}).items() if name.startswith('game-')}
        previous = {name: row for name, row in (self.state.get('generationChange') or {}).get('old', {}).items() if name.startswith('game-')}
        for name, row in [*entries.items(), *previous.items()]:
            if not row or not row.get('id'):
                if not partial: raise ValueError('Finish preparing the game adapters before changing Tank compatibility.')
                continue
            observed = self.engine.assert_owned(row['id'], self.state['id'], name)
            if observed['State']['Status'] not in {'created', 'exited'} or (not partial and row.get('phase') != 'prepared'):
                raise ValueError('Every game process must finish stopping before changing Tank compatibility.')
        if partial:
            # A crash can leave a canonical container before its ID was saved.
            # Recovery must not implicitly stop an externally started game.
            for name in entries:
                found = self.engine.request('GET', '/containers/dst-' + self.state['id'] + '-' + name + '/json', expected=(200, 404))
                if found:
                    observed = self.engine.assert_owned(found['Id'], self.state['id'], name)
                    if observed['State']['Status'] not in {'created', 'exited'}:
                        raise ValueError('Stop every game process before restoring the previous Tank setting.')
        if not entries or not hagga_components(self.state):
            raise ValueError('Prepare Hagga Basin before changing Tank compatibility.')

    def preparation_running(self):
        preparation = self.state.get('regisPreparation') or {}
        if not preparation.get('job'):
            return False
        found = self.engine.request('GET', '/containers/' + preparation['job'] + '/json', expected=(200, 404))
        if not found:
            return False
        observed = self.engine.assert_owned(preparation['job'], self.state['id'], 'regis-generate')
        return observed['State']['Status'] not in {'created', 'exited'}

    def recover(self):
        pending = self.state.get('pendingRegisChange')
        if not pending:
            return {'ok': True, 'enabled': bool((self.state.get('regisSupport') or {}).get('enabled')), 'message': 'No Tank change needs recovery.'}
        self.stopped(partial=True)
        if self.preparation_running():
            raise ValueError('Let the isolated Tank utility finish, then restore the previous Tank setting here. The world remains stopped.')
        expected = 'regis-' + pending['id']
        journal = self.state.get('generationChange')
        if not journal and pending.get('generation'):
            found = next((row for row in reversed(self.state.get('generationHistory', [])) if row.get('id') == pending['generation']), None)
            if not found or found.get('purpose') != expected or found.get('phase') not in {'committed', 'rolled-back'}:
                raise ValueError('The previous Tank adapter generation needs review before recovery.')
            if found['phase'] == 'rolled-back':
                # A restart can occur after rollback was persisted but before
                # the pending policy was cleared. Verify the restored adapters
                # instead of requiring another replacement generation.
                for component, previous in found['old'].items():
                    current = self.state.get(service_generations.collection(component), {}).get(component)
                    if not previous or not current or current.get('id') != previous.get('id'):
                        raise ValueError('The restored Tank adapter identity needs review before recovery.')
                    observed = self.engine.assert_owned(previous['id'], self.state['id'], component)
                    if observed.get('Name', '').lstrip('/') != 'dst-' + self.state['id'] + '-' + component:
                        raise ValueError('The restored Tank adapter name needs review before recovery.')
            else:
                self.state['generationChange'] = copy.deepcopy(found); journal = self.state['generationChange']
        if journal:
            if journal.get('purpose') != expected:
                raise ValueError('Another component replacement needs recovery before the Tank change.')
            self.stopped(partial=True)
            service_generations.rollback_generation(self.state, self.engine, self.m.save)
        if pending.get('previous') is None:
            self.state.pop('regisSupport', None)
        else:
            self.state['regisSupport'] = copy.deepcopy(pending['previous'])
        self.state.pop('pendingRegisChange', None); self.m.save(self.state)
        return {'ok': True, 'enabled': bool((self.state.get('regisSupport') or {}).get('enabled')),
                'message': 'The previous Tank setting and stopped map adapters were restored.'}

    def set(self, enabled, acknowledge=False):
        if type(enabled) is not bool or type(acknowledge) is not bool:
            raise ValueError('Supply JSON booleans for Tank support and the stored-Tank acknowledgement.')
        pending = self.state.get('pendingRegisChange') or {}
        if (not enabled and not acknowledge and
                ((self.state.get('regisSupport') or {}).get('enabled') or pending.get('enabled') or (pending.get('previous') or {}).get('enabled'))):
            raise ValueError('Acknowledge that saved Tanks require compatibility before disabling it.')
        if self.state.get('pendingRegisChange'):
            self.recover()
        self.stopped()
        if self.state.get('generationChange'):
            raise ValueError('Recover the previous component replacement before changing Tank support.')
        previous = copy.deepcopy(self.state.get('regisSupport'))
        if (previous or {}).get('enabled') is True and not enabled and not acknowledge:
            raise ValueError('Acknowledge that saved Tanks require compatibility before disabling it.')
        if not enabled and not (previous or {}).get('enabled'):
            return {'ok': True, 'enabled': False, 'message': 'Tank compatibility is already disabled.'}
        if enabled and (previous or {}).get('enabled'):
            try:
                assert_prepared_images(self.state, self.engine)
                return {'ok': True, 'enabled': True, 'message': 'Tank compatibility is already selected.'}
            except ValueError:
                # A stopped adapter refresh can reapply the already-selected
                # verified image without claiming a mismatched adapter is ready.
                pass
        identifier = self.state['operation']['id']
        pending = {'id': identifier, 'previous': previous, 'enabled': enabled, 'phase': 'preparing', 'startedAt': time.time()}
        self.state['pendingRegisChange'] = pending; self.m.save(self.state)
        try:
            image = Builder(self.state, self.engine, self.m.STATE, self.m.save).prepare() if enabled else None
            desired = {'enabled': enabled, 'image': image, 'selectedAt': time.time()}
            pending['phase'] = 'replacing-adapters'; self.m.save(self.state)
            plan = self.state['worldPlan']; credentials = self.m.read_credentials(self.state)
            bridge = self.engine.request('GET', '/networks/' + plan['network'])['IPAM']['Config'][0]['Gateway']
            specs, resources = {}, {}
            for component in hagga_components(self.state):
                entry = self.state['services'][component]
                observed = self.engine.assert_owned(entry['id'], self.state['id'], component)
                host = observed.get('HostConfig') or {}
                if type(host.get('Memory')) is not int or host['Memory'] <= 0:
                    raise ValueError('Review the existing Hagga RAM allocation before changing Tank support.')
                # Defaults are direct Saved uploads, not wrapper fallbacks.
                # Existing adapters must never seed or overwrite those INIs.
                spec = game_spec(plan, int(component.removeprefix('game-')), credentials, bridge, {})
                for volume in spec['volumes']: volume['mustBeNew'] = False
                spec['memory'] = host['Memory']
                specs[component] = apply_image_policy(self.state, int(component.removeprefix('game-')), spec, policy=desired)
                resources[component] = host
            self.stopped()
            journal = service_generations.replace_generation(self.state, self.engine, specs, plan, self.m.save, 'regis-' + identifier)
            pending['generation'] = journal['id']; self.m.save(self.state)
            for component, old in resources.items():
                # Preserve the actual stopped adapter's chosen RAM/CPU limits.
                cap = old.get('NanoCpus', 0) / 1_000_000_000 if old.get('NanoCpus', 0) else (
                    old['CpuQuota'] / old['CpuPeriod'] if old.get('CpuQuota', 0) > 0 and old.get('CpuPeriod', 0) > 0 else None)
                self.engine.set_component_cpu(self.state['services'][component]['id'], self.state['id'], component, cap)
            pending['phase'] = 'committing'; self.state['regisSupport'] = desired
            service_generations.commit_generation(self.state, self.m.save)
            self.state.pop('pendingRegisChange', None); self.m.save(self.state)
            return {'ok': True, 'enabled': enabled, 'message': ('Tank compatibility enabled. Start the battlegroup when ready to apply it.' if enabled else
                    'The official Hagga image was restored. Start the battlegroup when ready to apply it.')}
        except Exception:
            # Never turn an incomplete replacement into a runnable world. If
            # automatic rollback cannot be verified, the persisted pending flag
            # keeps starts blocked and exposes the explicit recovery control.
            try:
                if not self.preparation_running():
                    preparation = self.state.get('regisPreparation')
                    if preparation and preparation.get('phase') != 'verified': preparation['phase'] = 'failed'
                    self.recover()
            except Exception:
                self.m.save(self.state)
            raise
