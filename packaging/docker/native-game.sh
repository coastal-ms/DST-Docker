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
ln -sfn "$settings" "$config"
# The custom retail INI is a runtime projection of the same authoritative
# file shown in File Browser and Server Settings. Absence clears an old copy.
runtime="$saved/Config/LinuxServer"
mkdir -p "$runtime"
if [ -L "$settings/UserServerCustomSettings.ini" ] || [ -L "$runtime/ServerCustomSettings.ini" ]; then
    echo 'The server settings projection needs review.' >&2
    exit 1
fi
if [ -f "$settings/UserServerCustomSettings.ini" ]; then
    temporary=$(mktemp "$runtime/.dst-server-settings.XXXXXX")
    cp "$settings/UserServerCustomSettings.ini" "$temporary"
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
