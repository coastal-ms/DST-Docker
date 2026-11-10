import type { PodSummary } from './api/pods'
import { getBackupOpPodInfo, backupOpKindLabel, isFailedPodStatus } from './podClassification'
import { mapLabel, mapLabelFromPodSlug } from './util/mapLabel'

export type PodGroup = 'maps' | 'services' | 'history'
export function podPresentation(pod: PodSummary) {
  const op = getBackupOpPodInfo(pod.name)
  // A failed game map still needs attention. Only completed workloads and
  // recognized terminal operation/director history leave the live list.
  const terminal = /^(Succeeded)$/i.test(pod.phase) || /^(Completed|Succeeded)$/i.test(pod.status)
    || (!!op || /-bgd-/.test(pod.name)) && (/^Failed$/i.test(pod.phase) || /^(Failed|Evicted)$/i.test(pod.status))
  const map = pod.name.match(/-sg-(.+)-pod-(\d+)$/)
  let group: PodGroup = terminal ? 'history' : map ? 'maps' : 'services'
  let label = pod.name
  let description = 'Unrecognized service · technical name shown'
  if (op) {
    label = `${backupOpKindLabel(op.kind)} · ${op.timestamp.toLocaleString()}`
    description = terminal ? 'Past operation · not a live service' : 'Operation in progress'
  } else if (map) {
    label = mapLabelFromPodSlug(map[1]!) ?? `Game map: ${map[1]}`
    description = `Game map · instance ${map[2]}`
  } else {
    const roles: [RegExp, string, string][] = [
      [/-bgd-/, 'Battlegroup director', 'Schedules game maps'],
      [/-db-dbdepl-/, 'Database', 'World and character data'],
      [/-db-util-pghero-/, 'Database performance monitor', 'Database diagnostics'],
      [/-db-util-mon-/, 'Database monitoring', 'Database health monitoring'],
      [/-mq-admin-/, 'Admin message broker', 'Administrative messaging'],
      [/-mq-game-/, 'Game message broker', 'Game messaging'],
      [/-sgw-/, 'Player gateway', 'Player connections'],
      [/-fb-deploy-/, 'Battlegroup service (FB)', 'Funcom supporting service'],
      [/-tr-deploy-/, 'Battlegroup service (TR)', 'Funcom supporting service'],
      [/^map-helper(?:-|$)/, 'Live map helper', 'DST live map service'],
      [/^battlegroupoperator-/, 'Battlegroup operator', 'Manages the battlegroup'],
      [/^databaseoperator-/, 'Database operator', 'Manages the database'],
      [/^serveroperator-/, 'Game server operator', 'Manages game server workloads'],
      [/^utilitiesoperator-/, 'Utilities operator', 'Manages supporting services'],
      [/^cert-manager-cainjector-/, 'Certificate injector', 'Cluster certificate service'],
      [/^cert-manager-webhook-/, 'Certificate validation', 'Cluster certificate service'],
      [/^cert-manager-/, 'Certificate manager', 'Cluster certificates'],
      [/^coredns-/, 'Cluster DNS', 'Internal service discovery'],
      [/^local-path-provisioner-/, 'Storage provisioner', 'Local persistent storage'],
      [/^metrics-server-/, 'Cluster metrics', 'Resource monitoring'],
    ]
    const role = roles.find(([pattern]) => pattern.test(pod.name))
    if (role) { label = role[1]; description = role[2] }
  }
  if (terminal) group = 'history'
  if (pod.backend === 'docker') {
    const roles: Record<string, [string, string]> = {
      postgres: ['Database', 'World and character data'],
      director: ['Battlegroup director', 'Schedules game maps'],
      gateway: ['Player gateway', 'Player connections'],
      'text-router': ['Text router', 'Game chat routing'],
      'rmq-game': ['Game message broker', 'Game messaging'],
      'rmq-admin': ['Admin message broker', 'Administrative messaging'],
    }
    if (pod.component?.startsWith('game-')) {
      group = 'maps'; label = mapLabel(pod.map) || pod.name; description = `Game map · ${pod.component}`
    } else if (pod.component && roles[pod.component]) {
      [label, description] = roles[pod.component]!
    }
  }
  const ready = pod.ready.match(/^(\d+)\/(\d+)$/)
  const fullyReady = !!ready && +ready[2]! > 0 && +ready[1]! === +ready[2]!
  const failed = isFailedPodStatus(pod.status) || /^Failed$/i.test(pod.phase)
  const healthy = !terminal && !failed && /^Running$/i.test(pod.phase) && fullyReady
  const stopped = pod.backend === 'docker' && pod.desiredState === 'stopped' && pod.phase === 'Stopped'
  const state = stopped ? 'Stopped' : terminal ? (failed ? 'Failed attempt' : 'Completed')
    : failed ? pod.status || 'Failed' : healthy ? 'Ready'
      : /^Running$/i.test(pod.phase) ? 'Not ready' : pod.status || pod.phase || 'Unknown'
  const tone = stopped || terminal ? 'text-text-muted' : failed ? 'text-danger' : healthy ? 'text-success' : 'text-warning'
  return { group, label, description, terminal, healthy, needsAttention: !stopped && !terminal && !healthy, state, tone }
}
