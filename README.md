# DST for Docker

Run Dune Server Tool from a browser, with the server and management services inside Linux or Windows WSL.

This is the private development repository for DST's Docker hosting option. It remains part of DST. Feature parity and installation testing are still in progress.

The Docker edition manages self-hosted servers on native Linux or Windows WSL. Solo save tools stay in the standalone Windows DST application and are outside this edition's scope. Docker server hosting does not require a Windows companion.

## Installation status

The intended setup is: install WSL on Windows, open Ubuntu, run one DST install command, then finish setup in the browser. Native Linux users will run the same install command directly.

The self-contained installer has passed isolated Ubuntu dependency installation and browser startup. Wider clean-machine, upgrade and game acceptance remain in progress. There is no stable installer download command yet. The private development setup below can use the installer directly from a committed checkout.

## Windows: prepare WSL

Open PowerShell as administrator and run:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if prompted. Open Ubuntu and finish creating your Linux user account. Run the remaining commands in the Ubuntu terminal.

If Ubuntu is already installed, open it and continue. See Microsoft's [WSL installation guide](https://learn.microsoft.com/windows/wsl/install) for other configurations.

## Linux or WSL: current development setup

You need:

- An x86_64 Linux environment, directly or through WSL 2.
- Docker Engine 26 or newer, running inside that Linux environment, with the Docker Compose plugin.
- Git access to this private repository.
- A Funcom self-host service token for the portal's server setup.

Use Docker's [Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/) or [Debian installation instructions](https://docs.docker.com/engine/install/debian/) if Docker is not installed. This preview uses Linux host networking; Docker Desktop and macOS hosting have not been qualified.

Verify that your Linux user can access Docker:

```sh
docker info
docker compose version
```

Then get the private Docker branch and start DST:

```sh
git clone --branch codex/docker-edition https://github.com/coastal-ms/DST-Docker.git
cd DST-Docker
bash bin/dst-install --source "$PWD"
```

The installer prepares missing prerequisites on supported Ubuntu/Debian hosts, extracts a verified source snapshot, downloads the official Linux server package, builds the DST images, and starts the portal. Let it finish; download and build time depend on your connection and hardware. It preserves existing Docker data and does not remove another container runtime to resolve a conflict.

## Open the portal

When startup completes, the terminal prints a private first-setup link. Open that complete link in your normal browser and choose your Owner username and password. After setup, open the console's IP address and port and sign in with that account. Windows users can use their Windows browser; it does not need to run inside the WSL terminal.

The launcher prints links for the Linux host's IP addresses as well as localhost. In WSL NAT mode, its Linux address works from Windows. To use the Windows machine's LAN address, run `packaging/docker/Enable-DstDockerLan.ps1 -ListenAddress <Windows-LAN-IP>` from administrator Windows PowerShell after the console starts. Use `-WhatIf` to preview the specific forwarding and private-LAN firewall rule. Rerun it if WSL receives a new address.

Complete the Setup Wizard in the portal. Enter your Funcom service token there, configure the world, and start the server. Keep the token out of repository files and chat.

If you need the portal link again:

```sh
sh bin/dst-docker url
```

Owners can manage browser accounts in **Settings → Browser Portal accounts**. Current Docker server roles are Owner and Admin. New accounts must replace their initial password at first sign-in. Owners can reset passwords, revoke sessions, change roles, disable accounts and delete accounts. The last enabled Owner is protected, and account sign-in stays enabled.

If no Owner can sign in, open the Linux or WSL terminal on the Docker host. With the console running, run these commands from the installation folder (`~/.local/share/dst-docker/current` for a default standalone installation, or the checkout folder for development):

```sh
sh bin/dst-docker owners
sh bin/dst-docker reset-owner "OWNER_USERNAME"
```

Use the exact existing Owner username and type `RESET OWNER` at the prompt. Recovery re-enables that Owner, replaces their password, revokes their sessions and clears sign-in lockouts. The terminal shows a one-time password; sign in and replace it before continuing. Other account passwords and sessions stay unchanged. A custom standalone installation uses the `current` folder under its chosen install path. Recovery does not start the database or maps.

## Manage this installation

Run these commands from the `DST-Docker` folder:

```sh
sh bin/dst-docker up      # Start the portal
sh bin/dst-docker status  # Show portal container status
sh bin/dst-docker logs    # Show recent portal logs
sh bin/dst-docker url     # Print the browser address / first-setup link
sh bin/dst-docker down    # Stop the portal containers
```

Use the portal's normal server controls to stop or restart the game world. The launcher's `down` command stops the portal containers; game services are managed separately.

Configuration, databases, game saves, and official packages persist in Docker volumes. Stopping the portal does not delete those volumes.

## Control server resources

Open **Settings → Docker resources** to review the RAM and CPUs available to the Linux host, choose a server RAM budget and game CPU budget, and set RAM/CPU limits for each map instance. The familiar map names are searchable.

Stop the battlegroup before applying different allocations. Saving never stops it implicitly. DST verifies each container limit, persists the allocations and checks the combined map budgets before startup or demand scaling. The RAM budget reserves 2 GiB for supporting services, with another 2 GiB left for the host. These controls manage this installation's game allocations within the Linux host's limits; they do not resize WSL itself.

## Development scope

Optional in-game commands are configured on **Players → Community tools**. They are off by default, with separate command and channel selections. Messages are consumed once; DST does not save a chat history. Cooldown timestamps prevent repeated use, and switching the listener off removes its queue.

This is an unfinished Docker preview. Some DST actions still need Linux/browser adapters, and clean-machine installation and upgrade acceptance are not complete. The existing DST interface and feature behavior are the parity baseline.

See [Docker development details](packaging/docker/README.md) for the current implementation and remaining work. VM-data migration and Discord portal login are deferred.

Part of [Dune Server Tool](https://github.com/coastal-ms/DST-DuneServerTool), by Coastal. Licensed under [Apache 2.0](LICENSE).
