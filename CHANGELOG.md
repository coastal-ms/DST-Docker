# DST Docker changelog

## [1.0.20]

- Restore missing cosmetic grant entries, including the Contagion Cowl and Contagion Visor.
- Add the emote picker for granting selected emote items to server characters.

## [1.0.19]

- Copy Windows Explorer paths for WSL backup folders while retaining Linux paths for other devices.
- Keep backup mirroring working when an older manager image is no longer available.

## [1.0.18]

- Set up browser HTTPS from Settings, download the public certificate and follow device trust instructions before switching connections.
- Let Docker Owners and Admins adjust Live Map refresh timing and control live collection and snapshots.
- Restore SQL editor access for Docker Owners.

## [1.0.17]

- Remove the Windows-only Widget mode entry from the Docker portal.

- Show the Docker portal version in the sidebar footer.
- Restore character-linked Player accounts and the Player Portal alongside Owner and Admin access.

## [1.0.16]

- Clear the completed-update message and Reload portal button once the updated portal is loaded.

## [1.0.15]

- Notify portal users when a DST Docker update is available, with a direct link to update settings.
- Detect the private host address during browser setup without requiring the desktop launcher.
- Add a direct Funcom account link to the service-token step.
- Show clearly labelled setup links without listing Docker bridge addresses.
- Provide the current Owner-creation link from the hosting window when no Owner account exists.
- Keep failed server preparation from being reported as successful when containers were only partly prepared.

## [1.0.14]

- Reuse the existing portal installation when the installer is run under a different Linux user, keeping desktop hosting and browser updates connected.
- Prevent another installation folder from taking over the same portal.
- Explain an unavailable host updater without incorrectly suggesting that public releases require GitHub sign-in.
- Make public installation commands the primary README instructions.

## [1.0.13]

- Keep Shut down host and Create desktop shortcut available on supported WSL hosts after installation.
- Prepare the host connection before the management portal first starts.
- Clarify optional installation count sharing, what is shared, and how connection IP addresses are handled.

## [1.0.12]

- Compare installed and latest DST Docker versions in Settings and update the portal from the browser after stopping the battlegroup.
- Show update progress, reconnect after the portal restarts, and confirm the installed version while retaining saved server data and accounts.
- Load and save the Docker anonymous usage preference from Settings.
- Report successful server-settings saves without a missing-backup-path error.
- Match map settings to the Windows layout with Map and Settings file selectors and full-width vertical setting rows.

## [1.0.11]

- Keep setup pages scrollable so Back and Next stay reachable in short browser windows.
- Support mouse-wheel and keyboard scrolling through the wizard on desktop and narrow screens.

## [1.0.10]

- Show the detected Docker IP during first-run setup and fill the Private / LAN server address automatically.
- Preserve saved and manually entered addresses, keep private detection out of Public / External, and offer retry when detection is unavailable.

## [1.0.9]

- Hold Installation check until official game files finish downloading and verifying, then enable Next automatically.
- Offer Private / LAN and Public / External in server setup, with a required address, matching guidance and a review of the selected access.

## [1.0.8]

- Guide fresh installations through numbered setup stages with Back/Next controls and a settings review before preparing the server.
- Keep the management portal hidden until setup finishes, with saved progress and clear errors when preparation needs attention.

## [1.0.7]

- Recover SteamCMD 0x6 download failures automatically with manifest cleanup and bounded retries.
- Prepare fresh WSL imports and continue Docker installation after a confirmed distribution restart.
- Avoid imported Ubuntu first-boot setup stalls while preserving existing WSL settings.
- Add anonymous installation counting with a Settings opt-out, six-hour reporting and a manual refresh tool.

## [1.0.6]

- Keep manual Warm independent of Follow Overmap: enabling Warm selects Keep running, and disabling it selects On demand.
- Keep the Warm toggle and map mode controls consistent when switching between manual and automatic warming.

## [1.0.5]

- Configure private or public player access, detect the public IP, and show the Docker address to use for router forwarding.
- Use TCP 31982 and UDP 7777Ã¢â‚¬â€œ7810 for player connections and propagate address changes across the game services.
- Confirm before applying player-access changes that restart the server.
- Configure the WSL LAN address and explicitly choose the same-PC public-IP loopback target from Settings.
- Keep loopback controls visible during refreshes and reopen the console through a reachable local address.
- Collapse the map list and access additional map tools near the top of the page.
- Repair local backup mirror folder preparation and show Configuring consistently during map startup.

## [1.0.4]

- Keep Game.ini and Engine.ini global, with separate Custom Server Settings for each Hagga and Deep Desert partition.
- Update Tank compatibility for Funcom 1.5.20.2.
- Show current player counts and server update availability on Server Overview.
- Use current memory usage when admitting map starts and show the final result of map operations.
- Clarify map startup modes and WSL storage capacity.

## [1.0.3]

- Keep stopped containers from blocking backup imports.
- Show original filenames for newly imported backups in backup lists and restore choices.
- Clarify required game ports and optional browser access.

## [1.0.2]

- Keep Overmap first in the Game Servers list.
- Set a lower WSL RAM ceiling from Settings, with changes applied at the next WSL restart.
- Choose a preferred Windows browser for the desktop launcher without changing the system default.
- Sort maps by name, status, players, mode, RAM usage or swap usage.
- Document a Chrome video playback workaround for simultaneous portal and video use.

## [1.0.1]

- Fix server update staging and recovery, including Tank compatibility with Funcom 1.5.20.1.
- Show update progress, console output and retained results through Details.
- Simplify map settings with inline resource editors, preserved drafts and feedback beside each action.
- Apply supported RAM, CPU and swap changes live, and save settings while maps run.
- Remove redundant confirmations and fix hosting-menu prompts and shutdown status.
- Add optional Tailscale private access and public HTTPS Funnel access with shareable links and map QR codes.
- Align Docker CI with its Linux runtime.

## [1.0.0]

- Host Dune Awakening servers on Linux and Windows WSL with setup and administration in the browser.
- Manage map memory, startup modes and global or per-map gameplay settings.
- Manage players, bases, vehicles, backups, server updates and scheduled restarts.
- Sign in with Owner and Admin accounts over HTTP, with optional HTTPS.
- Start hosting from a Windows desktop icon and shut down the battlegroup, containers and WSL from Commands.
