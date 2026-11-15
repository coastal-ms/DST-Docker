# DST for Docker

Run Dune Server Tool from a browser, with the server and management services inside Linux or Windows WSL.

DST Docker is a standalone browser application for hosting and managing Dune Awakening servers on Linux and Windows WSL. It has its own releases and installer, separate from the Windows Dune Server Tool application.

## Install DST Docker 1.0.5

Windows users prepare Ubuntu below, then run the Linux installation command. Native Linux users can go directly to **Linux or WSL: install**.

## Windows: prepare WSL

Open PowerShell as administrator and run:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if prompted. Open Ubuntu and finish creating your Linux user account. Run the remaining commands in the Ubuntu terminal.

If Ubuntu is already installed, open it and continue. See Microsoft's [WSL installation guide](https://learn.microsoft.com/windows/wsl/install) for other configurations.

## Linux or WSL: install

You need an x86_64 Linux environment and a Funcom self-host service token. The installer prepares missing prerequisites on supported Ubuntu/Debian systems, including Docker Engine and Compose. Docker runs inside Linux or WSL; Docker Desktop is not required.

Run this in Ubuntu or your Linux terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/coastal-ms/DST-Docker/main/bootstrap.sh | bash
```

The bootstrap downloads the latest tagged source release and starts installation. Releases contain GitHub�s source ZIP and tarball; there is no separate installer download.

For this private repository, sign in with GitHub CLI and use:

```sh
gh api repos/coastal-ms/DST-Docker/contents/bootstrap.sh --jq .content | base64 --decode | bash
```

The installer walks you through missing prerequisites on supported Ubuntu/Debian hosts and asks for the Web UI port (press Enter for 8088). It installs Docker Engine inside Linux when needed; Docker Desktop is not required. If the current terminal needs `sudo` to access Docker, setup continues using it. The installer builds and starts the Web UI, prints the complete browser link, then downloads the official Linux server package. You can open the Web UI and create your Owner account while the game files download. Keep the installer terminal open until it finishes. It preserves existing Docker data and does not remove another container runtime to resolve a conflict. Existing installations retain their console port; use `--port PORT` to change it. Scripted installations can use `--non-interactive` or an explicit `--port PORT`.

## Open the portal

Windows WSL installations create a **DST Docker** desktop icon. Open it to start the console, resume a battlegroup stopped by the host shutdown action, and open your browser. Its visible hosting window keeps WSL running; keep that window open while hosting. Use **Commands → Shut down host** to stop the battlegroup first, wait for game processes to exit, stop DST containers cleanly, then shut down WSL. The action requires an Owner account and confirmation, and refuses to shut down while another WSL distribution, unrelated Docker workload or maintenance operation is running. A failed stop leaves WSL running and reports the failure in the hosting window.

Use **Commands → Create desktop shortcut** to recreate the icon, or run `sh bin/dst-docker shortcut` in the installation folder (`~/.local/share/dst-docker/current` by default). `sh bin/dst-docker desktop` starts the same foreground hosting session from Ubuntu. Opening the icon again reopens the console through its existing hosting window, including after a partial shutdown; an active shutdown must finish first. A saved world restart is cleared after startup completes, and a later deliberate stop takes precedence. The installer uses your current Windows Desktop location, including a relocated Desktop. It preserves an existing shortcut belonging to a different installation. Native Linux installations continue to use `sh bin/dst-docker up`; WSL-specific host controls require the installed Windows hosting session.

The console and management services restart when Docker starts, including when you reopen a systemd-enabled WSL distribution. A battlegroup saved as running resumes through the normal startup checks; a deliberately stopped battlegroup or map stays stopped. An interrupted maintenance operation still requires recovery before startup. Intentionally stopping the management containers keeps them stopped until you start DST again.

When startup completes, the terminal prints a private first-setup link. Open that complete link in your normal browser and choose your Owner username and password. After setup, open the console's IP address and port and sign in with that account. Windows users can use their Windows browser; it does not need to run inside the WSL terminal.

The launcher prints links for the Linux host's IP addresses as well as localhost. In WSL NAT mode, its Linux address works from Windows. To use the Windows machine's LAN address, run `packaging/docker/Enable-DstDockerLan.ps1 -ListenAddress <Windows-LAN-IP>` from administrator Windows PowerShell after the console starts. Use `-WhatIf` to preview the specific forwarding and private-LAN firewall rule. Rerun it if WSL receives a new address.

Complete the Setup Wizard in the portal. Enter your Funcom service token there, configure the world, and start the server. Keep the token out of repository files and chat.

If you need the portal link again:

```sh
sh bin/dst-docker url
```

For remote browser access without forwarding a router port, open **Settings > Remote access with Tailscale**. Choose **Private** for devices on your Tailscale network or **Public HTTPS** for Tailscale Funnel, then select **Connect** and follow the Tailscale sign-in link. If Tailscale asks you to enable HTTPS or Funnel, complete that setup and select Connect again. DST shows the resulting address and QR code; users sign in with their DST portal accounts. The Live Map QR uses this address too. Tailscale runs in a separate userspace container, retains its identity across restarts, and can be turned off without restarting game maps. Private access requires Tailscale on the connecting device; public Funnel access does not.

The console uses **HTTP by default**; HTTPS is optional. To enable HTTPS for your host address, run `sh bin/dst-docker https HOST_IPV4 [PORT]` and follow the printed certificate instructions. To return to HTTP, run `sh bin/dst-docker http [PORT]`. Omitting the port preserves your current console port. Switching transport restarts only the console and its optional proxy; saved accounts, world data and map processes are preserved. The HTTPS certificate data is retained so you can enable it again later.

Owners can manage browser accounts in **Settings → Browser Portal accounts**. Current Docker server roles are Owner and Admin. New accounts must replace their initial password at first sign-in. Owners can reset passwords, revoke sessions, change roles, disable accounts and delete accounts. The last enabled Owner is protected, and account sign-in stays enabled.

If no Owner can sign in on Windows, open the **DST Docker** desktop icon and choose **2 · Recover Owner password** in the hosting window. The menu lists Owner accounts, asks for confirmation and shows a one-time password. **3 · Open management terminal** opens a command prompt in the correct installation folder.

On native Linux, open a terminal and run:

```sh
cd "$HOME/.local/share/dst-docker/current"
sh bin/dst-docker owners
sh bin/dst-docker reset-owner "OWNER_USERNAME"
```

Use the exact existing Owner username and type `RESET OWNER` at the prompt. Recovery re-enables that Owner, replaces their password, revokes their sessions and clears sign-in lockouts. The terminal shows a one-time password; sign in and replace it before continuing. Other account passwords and sessions stay unchanged. For a custom Linux installation, change to the `current` folder under its chosen path first. Recovery does not start the database or maps.

### Preferred Windows browser

In the Windows hosting window, **6 - Choose browser** saves your choice of system default, Chrome, Edge or Firefox. **1 - Open browser** and subsequent desktop launches use that choice without changing your Windows default browser. The selected browser must be installed.

### WSL RAM limit

On Windows, open **Settings > WSL RAM limit** to choose a lower RAM ceiling in GiB, or restore the WSL default of 50% of Windows RAM. Select **Save WSL RAM limit**. Other WSL settings are preserved, and the server keeps running. The limit applies to all WSL 2 distributions after WSL restarts; the page shows when a restart is pending. Adjust per-map allocations to fit the smaller ceiling before restarting.

### Chrome: video freezes while the portal is visible

If YouTube or another video freezes while the portal is visible in Chrome despite having buffered video, try opening `chrome://flags/#disable-accelerated-video-decode`, setting **Hardware-accelerated video decode** to **Disabled**, and selecting **Relaunch**. Leave Chrome's general graphics acceleration enabled. This switches video decoding to the CPU and can increase CPU use. It is a workaround for the observed Chrome playback issue, not a required setting for every installation. Opening the portal in Edge is another workaround. Return the flag to **Default** if it does not help.

## Network ports

Game connections and browser access use separate ports. Check **Setup Wizard > Your world > Game-port base** for your configured base, called `B` below; the default is **7777**. Changing the console port does not change the game ports. In **Settings > Player connections**, choose **Private / LAN** or **Public / External** and apply the corresponding IPv4 address. Public access detects your public IPv4 automatically. The separate Docker IP is the router forwarding target; it stays visible when the advertised public address changes. Applying uses TCP **31982** and UDP **7777-7810**, updates the advertised addresses and restarts a running world. Existing custom-port installations keep their current ports until this change is applied.

| Purpose | Protocol | Default / configured port | Who needs access |
| --- | --- | --- | --- |
| Game traffic for each map partition | UDP | `B + partition ID - 1`; Hagga **7777**, Overmap **7778** with the default base | Players. Allow every partition's game port, including maps that start on demand. |
| Game login and messaging | TCP | **31982** | Players. Forward this along with the game UDP ports when hosting behind a router. |
| Browser portal and its API | TCP | **8088**, or your selected console port | Browser users only; it is not required for game login. HTTP is the default. Optional local HTTPS uses the same selected external port. |
| Tailscale private browser access / public HTTPS Funnel | HTTPS | **443** on the address shown by Tailscale | Optional browser access. No inbound router forward is needed for this path; it does not carry game traffic. |

Forward game traffic to the Linux host running the containers and allow it through that host's firewall. Use your configured base and installed map partition IDs rather than another server tool's port list. DST Docker does not configure a separate public-directory latency-probe range or a separate encrypted-API port; its browser API uses the console's transport and port.

On Windows WSL NAT, forwarding a router port to Windows alone does not make the WSL game listeners reachable. The console LAN helper configures only the selected **TCP console port**, not game UDP or messaging. Tailscale browser access also does not replace game-port reachability. See [hosting network details](packaging/docker/README.md#network-details) for the internal service ports and WSL distinction.

## Manage this installation

Run these commands from `~/.local/share/dst-docker/current` (or the `current` folder under your selected installation path):

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

RAM and CPU allocation changes apply while maps are running. DST verifies each container limit, persists the allocations and checks the combined map budgets before startup or demand scaling. The RAM budget reserves 2 GiB for supporting services, with another 2 GiB left for the host. These controls manage this installation's game allocations within the Linux host's limits; they do not resize WSL itself.

The **Maps & memory** view shows map status, RAM usage and limits, swap allowances and lifecycle modes. **Edit resources** opens the controls directly below the selected map. RAM limits can be raised or lowered while the map runs, within the host and server budgets. Gameplay settings have their own **Settings** tab and scope dropdown. Usage samples older than 30 seconds are marked unavailable, and absent Docker swap counters are shown as unknown.

Optional maps offer **Dynamic**, **Always on**, **Overmap active** and **Disabled** modes. Overmap active keeps a map warm while players are on Overmap, then waits five minutes after Overmap empties before releasing its warm floor, provided the map is empty. Unknown occupancy prevents automatic release. Disabled blocks new starts; it does not forcibly disconnect players on an already running map. Core maps retain their normal startup policy. Existing detailed map tools remain available under **Additional map tools**.

**Server Settings → Map settings** also opens the targeted editor. Choose Global defaults, Hagga Basin or Deep Desert, then select Custom Settings, Game or Engine and search or filter the fields. Overmap and story maps retain resource controls. **Save map settings** saves directly and leaves a pending-restart notice. It does not stop a running map. Each settings file inherits the global file until you save a map-specific copy; that copy is independent of later global edits. **Use global settings** removes the override with a backup and restores inheritance at the next map start. Custom settings saves retain Custom difficulty. Complex arrays and startup console variables retain their specialized global editors. Matching player-file requirements still apply.

Per-map settings require the updated native game adapter. Existing adapters must be updated with the world stopped before they can accept scoped saves; older adapters reject these saves rather than applying them globally. Saved overrides live under the owned shared UserSettings directory and remain available across map recreation and updates.

## Gameplay and compatibility

Optional in-game commands are configured on **Players → Community tools**. They are off by default, with separate command and channel selections. Messages are consumed once; DST does not save a chat history. Cooldown timestamps prevent repeated use, and switching the listener off removes its queue.

Player, base, vehicle and server tools use native Linux database and messaging connections. Server operations use container lifecycle and resource controls. Player compatibility settings provide complete manual INI instructions. Tank support is selected separately under Server Settings → Management & recovery for compatible game builds.

See [Hosting and maintenance](packaging/docker/README.md) for storage, updates, backups and optional HTTPS.

## Upgrade

Run the installation command again to upgrade. Keep the same installation path; accounts, server data, console port, resource settings and optional HTTPS certificates are retained. Use `--prefix` again if you originally chose a custom path.

[Release notes](CHANGELOG.md) · [Downloads](https://github.com/coastal-ms/DST-Docker/releases)

Created by Coastal. Licensed under [Apache 2.0](LICENSE).

## Storage capacity

WSL storage grows within its virtual disk limit and the free space on the Windows drive. See [WSL disk capacity and expansion](docs/wsl-storage.md) if additional capacity is needed.
