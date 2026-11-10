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

## Console address and port

HTTP is the default on port8088. The installer prints addresses reachable from the Linux host. Select a different port during installation or run `sh bin/dst-docker port PORT` later. Windows WSL NAT users can access the WSL address from Windows. To use the Windows LAN address, run `packaging/docker/Enable-DstDockerLan.ps1 -ListenAddress <Windows-LAN-IP> -Port 8088` from administrator PowerShell. Rerun it if WSL receives a new address. `-WhatIf` previews changes. Other devices also need the host firewall to permit the chosen port.

## Optional HTTPS

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
