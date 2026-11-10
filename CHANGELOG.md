# DST Docker changelog

## Unreleased

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
