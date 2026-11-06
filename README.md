# DST for Docker

Run Dune Server Tool from a browser, with the server and management services inside Linux or Windows WSL.

This is the private development repository for DST's Docker hosting option. It remains part of DST. Feature parity and installation testing are still in progress.

## Installation status

The intended setup is: install WSL on Windows, open Ubuntu, run one DST install command, then finish setup in the browser. Native Linux users will run the same install command directly.

That self-contained installer is being qualified. There is no stable installer download command yet. The current development setup below uses the launcher included in this repository.

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
sh bin/dst-docker up
```

The first run downloads the official Linux server package, builds the DST images, and starts the portal. Let it finish; download and build time depend on your connection and hardware.

## Open the portal

When startup completes, the terminal prints an authenticated browser link. Open that complete link in your normal browser. Windows users can use their Windows browser; it does not need to run inside the WSL terminal.

Complete the Setup Wizard in the portal. Enter your Funcom service token there, configure the world, and start the server. Keep the token out of repository files and chat.

If you need the portal link again:

```sh
sh bin/dst-docker url
```

## Manage this installation

Run these commands from the `DST-Docker` folder:

```sh
sh bin/dst-docker up      # Start the portal
sh bin/dst-docker status  # Show portal container status
sh bin/dst-docker logs    # Show recent portal logs
sh bin/dst-docker url     # Print the authenticated browser link
sh bin/dst-docker down    # Stop the portal containers
```

Use the portal's normal server controls to stop or restart the game world. The launcher's `down` command stops the portal containers; game services are managed separately.

Configuration, databases, game saves, and official packages persist in Docker volumes. Stopping the portal does not delete those volumes.

## Development scope

This is an unfinished Docker preview. Some DST actions still need Linux/browser adapters, and clean-machine installation and upgrade acceptance are not complete. The existing DST interface and feature behavior are the parity baseline.

See [Docker development details](packaging/docker/README.md) for the current implementation and remaining work. VM-data migration and Discord portal login are deferred.

Part of [Dune Server Tool](https://github.com/coastal-ms/DST-DuneServerTool), by Coastal. Licensed under [Apache 2.0](LICENSE).
