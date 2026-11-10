#!/bin/sh
set -eu
# Arguments remain separate through the user switch. Never print credentials.
saved=/home/dune/server/DuneSandbox/Saved
settings="$saved/UserSettings"
config='/home/dune/.config/Epic/Unreal Engine/Engine/Config'
if [ ! -d "$settings" ] || [ -L "$settings" ]; then
    echo 'The authoritative UserSettings directory is missing or unsupported. No defaults were substituted.' >&2
    exit 1
fi
mkdir -p '/home/dune/.config/Epic/Unreal Engine/Engine'
if [ -e "$config" ] && [ ! -L "$config" ]; then
    echo 'The game configuration directory needs review; existing files were preserved.' >&2
    exit 1
fi
# Per-partition settings are independent snapshots, selected at process start.
# Global edits stay the fallback for files without a map override. Never point
# a running game's INI directory directly at mutable shared settings.
case "${SERVER_INDEX:-}" in ''|*[!0-9]*) echo 'A map partition is required for settings.' >&2; exit 1;; esac
overrides="$settings/.dst-map-settings/$SERVER_INDEX/UserSettings"
effective="$saved/.dst-effective-settings"
for directory in "$settings/.dst-map-settings" "$settings/.dst-map-settings/$SERVER_INDEX" "$overrides" "$effective"; do
    if [ -L "$directory" ] || { [ -e "$directory" ] && [ ! -d "$directory" ]; }; then
        echo 'The map settings directory needs review.' >&2; exit 1
    fi
done
mkdir -p "$effective"
for name in UserGame.ini UserEngine.ini UserServerCustomSettings.ini; do
    source="$settings/$name"
    if [ -L "$overrides/$name" ] || [ -L "$source" ] || [ -L "$effective/$name" ]; then
        echo 'The map settings file needs review.' >&2; exit 1
    fi
    for candidate in "$overrides/$name" "$source" "$effective/$name"; do
        if [ -e "$candidate" ] && [ ! -f "$candidate" ]; then
            echo 'The map settings file is not a regular file.' >&2; exit 1
        fi
    done
    if [ -f "$overrides/$name" ]; then source="$overrides/$name"; fi
    if [ -f "$source" ]; then
        temporary=$(mktemp "$effective/.dst-settings.XXXXXX")
        cp "$source" "$temporary"; chmod 600 "$temporary"; mv -f "$temporary" "$effective/$name"
    else
        rm -f "$effective/$name"
    fi
done
ln -sfn "$effective" "$config"
# The custom retail INI is a runtime projection of the same authoritative
# file shown in File Browser and Server Settings. Absence clears an old copy.
runtime="$saved/Config/LinuxServer"
mkdir -p "$runtime"
if [ -L "$effective/UserServerCustomSettings.ini" ] || [ -L "$runtime/ServerCustomSettings.ini" ]; then
    echo 'The server settings projection needs review.' >&2
    exit 1
fi
if [ -f "$effective/UserServerCustomSettings.ini" ]; then
    temporary=$(mktemp "$runtime/.dst-server-settings.XXXXXX")
    cp "$effective/UserServerCustomSettings.ini" "$temporary"
    chmod 600 "$temporary"
    mv -f "$temporary" "$runtime/ServerCustomSettings.ini"
else
    rm -f "$runtime/ServerCustomSettings.ini"
fi
if [ -L "$settings/.dst-startup-exec-commands" ]; then
    echo 'The startup settings projection needs review.' >&2
    exit 1
fi
if [ -f "$settings/.dst-startup-exec-commands" ]; then
    commands=
    IFS= read -r commands < "$settings/.dst-startup-exec-commands" || [ -z "$commands" ]
    if [ -n "$commands" ]; then set -- "$@" "-ExecCmds=$commands"; fi
fi
chown -R dune:nogroup "$saved" /home/dune/.config
update-ca-certificates >/dev/null 2>&1
cd /home/dune/server
# The stock wrapper leaves a waiting shell above the native process. Exec the
# same packaged binary after dropping privileges so shutdown signals reach it.
binary=/home/dune/server/DuneSandbox/Binaries/Linux/DuneSandboxServer-Linux-Shipping
chmod +x "$binary"
# setpriv changes credentials without applying a login user's environment.
# Unreal resolves its per-user INI layer through HOME; retaining /root here
# silently skips the authoritative UserGame.ini/UserEngine.ini directory.
export HOME=/home/dune USER=dune LOGNAME=dune XDG_CONFIG_HOME=/home/dune/.config
exec setpriv --reuid=dune --regid=nogroup --init-groups "$binary" DuneSandbox "$@"
