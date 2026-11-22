# DST Docker hosting and maintenance

[Installation and first setup](../../README.md) · [Release notes](../../CHANGELOG.md)

DST Docker is a separate product with its own installer and releases. Run hosting commands inside Linux or WSL, from `~/.local/share/dst-docker/current` unless you selected a custom installation path.

## Start and stop

```sh
sh bin/dst-docker up
sh bin/dst-docker status
sh bin/dst-docker url
sh bin/dst-docker logs
```

On Windows, the **DST Docker** desktop icon opens a visible hosting window and the browser. Keep that window open while hosting. **Commands → Shut down host** stops game processes first, stops the installation's containers, then shuts down WSL. Another active WSL distribution, unrelated Docker workload or active maintenance operation prevents the host shutdown. Opening the icon again reuses the existing hosting window and can reopen the console after a partial shutdown.

**Commands → Create desktop shortcut** recreates the icon. Installations use the current Windows Desktop location. An additional installation receives a distinct shortcut instead of replacing another installation's icon.

On native Linux, stop the battlegroup through the browser before running `sh bin/dst-docker down` to stop the console containers. Docker starts the console services again when the host starts; a world deliberately stopped through its normal controls stays stopped.

On native Linux with a desktop, **DST Docker** opens the portal in your default browser from the applications menu or desktop icon. Use the link printed by the installer to create your first Owner account. Run `sh bin/dst-docker shortcut` from the installation if you add a desktop later or need to recreate the shortcut.

## Console address and port

HTTP is the default on port8088. The installer prints addresses reachable from the Linux host. Select a different port during installation or run `sh bin/dst-docker port PORT` later. Windows WSL NAT users can access the WSL address from Windows. To use the Windows LAN address, run `packaging/docker/Enable-DstDockerLan.ps1 -ListenAddress <Windows-LAN-IP> -Port 8088` from administrator PowerShell. Rerun it if WSL receives a new address. `-WhatIf` previews changes. Other devices also need the host firewall to permit the chosen port.

## Network details

The [network ports table](../../README.md#network-ports) separates player connections from optional browser access. `B` is **Setup Wizard > Your world > Game-port base**, default **7777**. A partition's game UDP port is `B + partition ID - 1`; its ID comes from the installed official world layout. Include on-demand partitions when preparing game forwarding. A running console or a successful TCP check does not verify UDP reachability for every map.

These additional service ports support the local installation. They are not player-facing router forwards:

| Local service | Protocol | Default / configured port | Listener |
| --- | --- | --- | --- |
| Battlegroup director | TCP | `B + 1000` = **8777** | Linux loopback |
| Administrative messaging | TCP | `B + 1001` = **8778** | Linux loopback |
| Game messaging HTTP endpoint | TCP | `B + 1003` = **8780** | Linux loopback; used by the gateway |
| Text router | TCP | `B + 1004` = **8781** | Linux loopback |
| File Browser | TCP | `B + 1005` = **8782** | Linux loopback; open through the authenticated portal |
| PostgreSQL | TCP | Installation-selected host port | Linux loopback; database connections also use the private Docker network |

Per-partition IGW endpoints use `B + 2000 + partition ID - 1` on the Docker bridge address for internal map communication, rather than a player-facing router forward.

The publicly reachable messaging listener is **TCP 31982**, not the loopback HTTP endpoint. Browser HTTPS and the browser API use the selected console port; there is no additional fixed API port to forward. The internal HTTPS upstream stays on loopback. Tailscale Serve/Funnel publishes the browser on its own HTTPS address at port443 and proxies the console; game clients still need the game UDP ports and messaging TCP port.

For WSL NAT, the Windows host and Linux guest have separate network addresses. `Enable-DstDockerLan.ps1` forwards only the chosen console TCP port and adds a private-LAN rule for that port. It does not forward game UDP or game messaging. Ensure your chosen WSL networking and firewall configuration makes the Linux game listeners reachable from players; a Windows TCP portproxy rule cannot carry game UDP. Native Linux hosts use the Linux host address directly.

**Settings → IP configurations** separates the Docker LAN address from the address advertised to players. On WSL, choose an internal NAT address, share the Windows LAN address, or select an available external switch for **Own LAN address**. The last option is disabled when DST cannot verify any external switches. It uses WSL bridged networking, which Microsoft marks deprecated. DHCP selects a LAN address automatically. DST checks an optional static address for conflicts before assigning it. Saving stages the host network change. Close other running WSL distributions, shut down the Docker host, and reopen its desktop icon to apply the change. The desktop recovery shortcut restores the previous WSL configuration if the selected network prevents startup.

Choose Private / LAN to advertise the detected Docker address, or Public / External to detect or enter the public IPv4 address. Public settings show the separate Docker address and router forwarding target for TCP31982 and UDP7777–7810. Applying player access restarts a running battlegroup and leaves an already stopped battlegroup stopped. A host LAN change updates private advertisement automatically; public advertisement is retained. Existing Windows same-PC public-IP routes are displayed without changing them. Router forwarding remains the operator's responsibility.

The separate **Same-PC public-IP loopback** control shows the current Windows route and defaults to **Keep current target**. Choose Docker, another server IP, or router NAT loopback, then apply and confirm that control to change the route. Windows asks for administrator approval. Only that public IP's host route is changed; the game server keeps running. Changing player access, opening Settings, and installing an update leave the loopback target alone.

When Docker has a separate address and is selected, DST also prepares same-PC game traffic for the Docker listeners. This applies only to the Windows host's connections to that public IP on TCP31982 and UDP7777–7810. The traffic setup is restored after a host restart while the route still targets the same Docker address, and removed when another loopback target is applied. When Docker shares the Windows LAN address, use router NAT loopback for same-PC joins through the public IP.

## Optional HTTPS

Owners can use **Settings > Browser HTTPS**: prepare HTTPS first, download the public CA certificate, install trust on each connecting device, then enable HTTPS. Preparation keeps HTTP available. DST does not automatically install client trust or export a private key. Changing the browser connection restarts the console/proxy only; game maps keep running. Tailscale HTTPS remains an alternative for devices that should not install this local certificate.

The terminal commands remain available:

```sh
sh bin/dst-docker https HOST_IPV4
sh bin/dst-docker https-root "$HOME/dst-root.crt"
```

HTTPS uses the selected console port and redirects HTTP bookmarks. Follow the printed certificate instructions on each client. DST Docker never changes client certificate trust automatically. To return to HTTP, run `sh bin/dst-docker http`; the console port, accounts and certificate data are retained. Both commands accept an explicit port where shown by launcher help.

## Accounts

Create the first Owner using the private setup link printed by the installer. Later, sign in normally at the console address. Owners manage accounts in **Settings → Browser Portal accounts**. For lost Owner access on Windows, choose **2 · Recover Owner password** in the hosting window. Option3 opens a management terminal already in the installation folder. On native Linux, change to the installation folder and use `sh bin/dst-docker owners` and `sh bin/dst-docker reset-owner "OWNER_USERNAME"`. Recovery creates a one-time password and requires a password change at sign-in.

## Storage and backups

Configuration, accounts, databases, map saves and downloaded game packages persist in Docker volumes. Stopping containers preserves those volumes. Use the browser's Database controls to create, download and restore backups, configure retention and select an optional local backup mirror. Keep downloaded recovery copies outside the hosting machine.

Per-map settings inherit global files until a map-specific copy is saved. Only Hagga Basin and Deep Desert offer gameplay overrides. **Use global settings** restores inheritance for the selected file; it does not erase other maps' settings. Map resource controls remain available for the other maps.

## Updates

Run the installer again using the same prefix to upgrade DST Docker. The console installer and its release version are separate from the Funcom game update. **Server updates** stages and applies the official game package, creates a verified database backup before migration and preserves intentionally stopped maps. Interrupted operations expose recovery rather than starting over.

Tank support is an optional compatibility setting for supported game builds. Use the dedicated enable/disable controls with the battlegroup stopped, and review their saved-Tank warning before disabling it. **Update with Tank support** preserves that policy through a supported game update.

## Player compatibility

Docker does not edit players' Windows files. **Server Settings → Player compatibility** provides the complete required Game.ini and Engine.ini entries with Copy and Download actions. Players close the game, back up their files and merge the listed values.
