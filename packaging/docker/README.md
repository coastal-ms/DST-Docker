# DST Docker development preview

Run from a Linux host or inside WSL with Docker Engine and Docker Compose available:

```sh
sh bin/dst-docker up
```

Open the authenticated URL printed when the application is ready. Windows users open that URL in their normal browser. Installation and execution stay inside Linux; this path does not download or run the DST Windows installer.

The private preview builds DST from this checkout. The first build downloads the Linux base images and frontend dependencies. It runs the application as a non-root user, keeps its filesystem read-only, and persists configuration, state and cache in named volumes. The current browser listener is host-local on port 18765 (or the next available port); remote access is a later milestone. It uses Linux host networking and is not a Docker Desktop/macOS package.

```sh
sh bin/dst-docker status
sh bin/dst-docker url
sh bin/dst-docker logs
sh bin/dst-docker down
```

Stopping removes the portal containers, preserving named data volumes. Owned game services are managed separately through the portal. Existing Windows/Hyper-V servers remain separate. The local launch token persists in protected configuration across application restarts; retrieve the link with `url`.

## Current behavior

- The existing DST shell, navigation, Server Overview and Players layout connect to the Linux backend. Docker setup occupies the existing Setup Wizard location. The separate early Docker dashboard remains an internal development scaffold.
- Authenticated DST API and browser client, with Linux startup and shared product version.
- Observer reads Docker metadata and memory statistics, publishing a sanitized snapshot every ten seconds. It never accepts commands. The application has no Docker socket mount; the observer has the socket and no network interface. A read-only bind mount of a Docker socket does not itself enforce read-only API access; that boundary is implemented by the observer's fixed GET-only code.
- Explicit stale/unavailable states. Map and container usage is an observation, not a gameplay-ready or login guarantee.
- Overview and Map SpinUp include a saved Memory balancing switch. Off uses the normal startup, stock automatic-map policy and explicit Warm choices; On additionally allows ordinary empty on-demand maps to unload. Changing the switch does not restart the world. Memory admission and occupied-map protection apply in both modes. New installations default to Off.
- Optional `DST_OBSERVE_PROJECT` restricts observations to one Compose project. Only official Funcom self-hosting image names are included.
- Independent Valve SteamCMD download of the official Linux self-host package, with image-manifest verification and persistent asset storage.
- Guided creation of a separate PostgreSQL database using the packaged official image. Official schema migration runs only after a persistent, verified backup, with the application database role demoted after migration.
- Native PostgreSQL transport preserves the existing SQL results and transaction behavior. Qualified player workflows use the shared validation, backup and maintenance safeguards; remaining workflows stay gated while their adapters are unfinished.
- World layout derives all 35 stock maps and partitions from the installed official definition. Generated credentials stay local. The application talks to a typed Unix control service and never receives the Docker socket.
- Owned message queues with independently generated TLS certificates; real TLS verification is tested separately from container health. Durable operation state keeps status available during longer setup work.
- Server Overview uses the existing responsive card layout, current-pod semantics, duration formatting and shared external port checker with the configured Docker ports. Shutdown maps remain in Lifecycle controls and disappear from the Overview table. Failed refreshes keep the last snapshot with a visible error and recover after successful polling.
- The existing File Browser application opens from the usual Web interfaces link. It mounts only this world's Saved volumes, keeps `/srv/UserSettings` as the familiar root, and exposes other prepared maps under `Maps`. Its pinned upstream image runs without root or command execution and binds only to loopback. The launcher loads it and normal world startup reconnects it; file data and its own settings persist separately.
- Native director, gateway, text router and initial game-process adapters use the official images. Their preparation, start and stop controls require the user's local service token.
- The independent native stack has passed a real Windows game-client join and character persistence check. Both initial maps report fresh game-ready heartbeats. This is a hosting milestone; complete application parity remains unfinished.
- Backups can be restored into a separate generated database for verification. The rehearsal preserves the live database and removes its temporary database only after success.
- Authoritative shared server INIs, retail settings and startup values use the existing settings pages with native file transport, backups, conflict detection and readback. Server review works independently of player-PC files. In a local Chrome or Edge browser, Browse can explicitly select the player's config folder for that browser session; reviewed client writes use the existing INI merger, prepare and verify original-file backups, reject intervening edits, and read back changed files. The browser cannot detect a running game, so the player must close Dune before writing client files. Other browser/file-transfer workflows remain unfinished.
- Scheduled restarts run inside the Docker service independently of the browser, with an explicit time zone, persisted operation identity and overlap protection. The existing opt-in update checkbox dispatches the native update controller when a newer build is available, or a normal restart when current. Unknown versions block before stopping the world. Background execution, exact build/request correlation and readiness handling passed against an isolated Unix-protocol fixture. Live scheduled game acceptance and future-version compatibility remain pending.
- The usual Update command stages the official package separately, verifies a fresh database backup, runs the official migration, and replaces stopped components while retaining their previous generation and Saved volumes. A running world checks map readiness before publishing its gateway; an intentionally stopped world stays stopped. Recovery uses the recorded jobs and package journal, and refuses to restore a stale database over observed new player progress. Manual same-build application passed on the local running test world; a disposable cluster also passed failure recovery after migration and component replacement. This does not establish compatibility with an unreleased future schema.
- The existing Overview and Commands log exports download ZIP archives through the browser. Battlegroup and operator logs are scoped to this installation, streamed with known credential patterns masked, and accompanied by a report of any unavailable or truncated sources. Each source is limited to 128 MiB; the three newest completed archives are retained.
- Native game adapters include all stock shared authentication values and direct privilege-dropped process execution. Graceful stop signals are confined to the identified game process in its owned container; saved volumes and prior stopped containers survive adapter replacement.
- The game wrapper sets the `dune` user's HOME and XDG configuration path before privilege-dropped startup. Keeping root's HOME caused per-user INI overrides to be skipped; the corrected process and 125-slot setting have actual game-client acceptance.

## Still under development

This is a runnable development preview, not a complete Docker release. Native backup/restore and interrupted-restore recovery, automatic demand/idle map lifecycle, memory admission, native Atlas observations and several player workflows have local qualification. Full map coverage, remote access, Solo adapters, unattended future-version acceptance, additional scheduling and client-browser workflows, and remaining application workflows are unfinished. The intended distribution is one install command from WSL Ubuntu on Windows or directly from Linux, followed by setup in the browser; that installer and clean-machine/upgrade qualification are still pending. The released UI and route inventory are the parity baseline; rendering a page or passing transport tests does not establish workflow parity. VM-data import is lower priority.

This work has not been published. Do not present the preview as production-ready or claim Defender results or comparative memory savings without measurement.
