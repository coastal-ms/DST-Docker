import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { confirmAction } from '../../util/actionConfirmation'
import { checkDockerProductUpdate, publishDockerProductUpdate, useDockerProductUpdate } from '../../hooks/useDockerProductUpdate'
import type { DockerProductUpdate } from '../../hooks/useDockerProductUpdate'
import { version as portalVersion } from '../../../package.json'

export type { DockerProductUpdate } from '../../hooks/useDockerProductUpdate'

export function DockerProductUpdateCard() {
  const status = useDockerProductUpdate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reconnecting, setReconnecting] = useState(false)
  const running = status?.operation?.phase === 'running'
  const redeploy = !!status?.latestVersion && status.currentVersion === status.latestVersion
  const load = useCallback(async (force = false) => {
    try {
      await checkDockerProductUpdate(force)
      setError(''); setReconnecting(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setReconnecting(true)
    }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!running && !reconnecting) return
    const timer = window.setInterval(() => { void load() }, 3000)
    return () => window.clearInterval(timer)
  }, [load, running, reconnecting])
  async function check() {
    setBusy(true)
    try { await load(true) } finally { setBusy(false) }
  }
  async function install() {
    if (!status?.tag || !status.commit) return
    const action = redeploy ? `Redeploy DST Docker ${status.currentVersion}?` : `Update DST Docker from ${status.currentVersion} to ${status.latestVersion}?`
    if (!confirmAction(`${action} The battlegroup can stay running. The portal restarts automatically; keep this tab open. Your saved server data and accounts are retained.`)) return
    setBusy(true); setError('')
    try {
      const result = await api<DockerProductUpdate>('/api/docker/product-update', {
        method: 'POST', body: JSON.stringify({ tag: status.tag, commit: status.commit, confirmation: 'UPDATE DST DOCKER' }),
      })
      publishDockerProductUpdate({ ...status, operation: result.operation })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      if (!(e instanceof Error) || !('status' in e)) setReconnecting(true)
    }
    finally { setBusy(false) }
  }
  const completed = status?.operation?.phase === 'completed' && status.currentVersion === status.operation.toVersion
  const needsReload = completed && portalVersion !== status.currentVersion
  const showOperation = status?.operation && (status.operation.phase !== 'completed' || needsReload)
  return <section id="settings.docker-updates" className="card p-5 space-y-4" data-section-nav-id="settings.docker-updates" data-section-nav-label="DST Docker updates">
    <h2 className="text-lg font-semibold">DST Docker updates</h2>
    <p className="text-sm text-text-muted">Update the DST management portal and Docker services. Official game-server updates are managed separately in Server updates.</p>
    <dl className="flex flex-wrap gap-x-10 gap-y-3 text-sm">
      <div><dt className="text-text-muted">Installed version</dt><dd>{status?.currentVersion ?? 'Checking…'}</dd></div>
      <div><dt className="text-text-muted">Latest version</dt><dd>{status?.latestVersion ?? 'Not checked'}</dd></div>
    </dl>
    {!status?.available && status?.latestVersion && !status.error && <p className="text-success">You have this or a newer version.</p>}
    {status?.available && <p>Version {status.latestVersion} is available.</p>}
    <p className="text-sm text-text-muted">The battlegroup can stay running. The portal restarts automatically. Keep this tab open so it can reconnect. Accounts, server data and the selected console port are kept.</p>
    {(error || status?.error) && <p role="alert" className="text-danger">{running && reconnecting ? 'The portal is reconnecting. Update completion has not been confirmed yet.' : error || status?.error}</p>}
    {showOperation && status?.operation && <p role="status" className={status.operation.phase === 'failed' ? 'text-danger' : completed ? 'text-success' : 'text-text-muted'}>
      {completed ? `DST Docker ${status.currentVersion} is installed. Reload the portal to use the updated interface.` : status.operation.message}
    </p>}
    {status?.operation?.phase === 'failed' && <p className="text-sm text-text-muted">The update log is in portal-update/update.log under your installation folder. You can retry after correcting the reported problem.</p>}
    <div className="flex flex-wrap gap-3">
      <button type="button" className="btn-secondary" disabled={busy || running} onClick={() => void check()}>{busy ? 'Working…' : 'Check now'}</button>
      <button type="button" className="btn-primary" disabled={busy || running || !status?.supported || !(status.available || redeploy) || !!status.error || !status.tag || !status.commit} onClick={() => void install()}>{running ? 'Updating DST Docker…' : redeploy ? 'Redeploy DST Docker' : 'Update DST Docker'}</button>
      {needsReload && <button type="button" className="btn-secondary" onClick={() => window.location.reload()}>Reload portal</button>}
    </div>
  </section>
}
