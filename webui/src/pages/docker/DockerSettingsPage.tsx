import { PageHeader } from '../../components/PageHeader'
import { AppearanceCard } from '../settings/AppearanceCard'
import { MemoryBalancingControl } from '../../components/MemoryBalancingControl'
import { Link } from '../../router'
import DockerResourcesCard from './DockerResourcesCard'

export default function DockerSettingsPage() {
  return <>
    <PageHeader title="Settings" icon="Settings" description="Manage your Docker host resources and DST preferences." />
    <div className="space-y-5">
      <DockerResourcesCard />
      <MemoryBalancingControl />
      <AppearanceCard />
      <div className="card p-5 flex flex-wrap gap-4"><Link to="/server-settings" className="text-accent">Server settings</Link><Link to="/setup" className="text-accent">Server setup</Link></div>
    </div>
  </>
}
