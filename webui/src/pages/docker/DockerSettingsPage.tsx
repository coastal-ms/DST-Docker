import { PageHeader } from '../../components/PageHeader'
import { AppearanceCard } from '../settings/AppearanceCard'
import { UsageCountCard } from '../settings/UsageCountCard'
import { MemoryBalancingControl } from '../../components/MemoryBalancingControl'
import { Link } from '../../router'
import DockerResourcesCard from './DockerResourcesCard'
import { PortalAccountsManager } from '../settings/PortalAccountsManager'
import { usePortalAccess } from '../../auth/portalAccess'
import { DockerTailscaleAccess } from './DockerTailscaleAccess'
import { DockerHttpsCard } from './DockerHttpsCard'
import { WslMemoryCard } from './WslMemoryCard'
import DockerNetworkCard from './DockerNetworkCard'
import { DockerProductUpdateCard } from './DockerProductUpdateCard'

export default function DockerSettingsPage() {
  const { canAccessOwnerSurfaces } = usePortalAccess()
  return <>
    <PageHeader title="Settings" icon="Settings" description="Manage your Docker host resources and DST preferences." />
    <div className="space-y-5">
      {canAccessOwnerSurfaces && <DockerProductUpdateCard />}
      {canAccessOwnerSurfaces && <DockerNetworkCard />}
      <DockerResourcesCard />
      {canAccessOwnerSurfaces && <WslMemoryCard />}
      <MemoryBalancingControl />
      {canAccessOwnerSurfaces && <DockerHttpsCard />}
      {canAccessOwnerSurfaces && <DockerTailscaleAccess />}
      {canAccessOwnerSurfaces && <UsageCountCard />}
      <AppearanceCard />
      {canAccessOwnerSurfaces && <div className="card p-5"><PortalAccountsManager docker /></div>}
      <div className="card p-5 flex flex-wrap gap-4"><Link to="/server-settings" className="text-accent">Server settings</Link><Link to="/setup" className="text-accent">Server setup</Link></div>
    </div>
  </>
}
