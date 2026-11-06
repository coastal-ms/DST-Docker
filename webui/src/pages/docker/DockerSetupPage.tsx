import { PageHeader } from '../../components/PageHeader'
import DockerSetup from './DockerSetup'
import './docker.css'

export default function DockerSetupPage() {
  return <>
    <PageHeader title="Setup Wizard" icon="Wand2" description="Set up your Docker-hosted Dune server." />
    <DockerSetup />
  </>
}
