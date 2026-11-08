# Qualified Docker surfaces. Authentication, ownership and local-only checks
# still run in the shared dispatcher; this gate only selects native adapters.
function Test-DuneDockerRouteQualified {
    param([string]$Method,[string]$Path)
    if($Path.StartsWith('/api/docker/file-browser/',[StringComparison]::Ordinal) -and $Method -in @('GET','HEAD','POST','PUT','PATCH','DELETE')){return $true}
    if($Method -eq 'GET' -and $Path -cmatch '^/api/docker/backup-exports/[a-f0-9]{32}$'){return $true}
    if($Method -eq 'POST' -and $Path -eq '/api/docker/backup-import'){return $true}
    if($Method -eq 'GET' -and $Path -in @('/api/db/backup-schedule','/api/db/backup-history','/api/db/backup-dump-pods')){return $true}
    if($Method -eq 'PUT' -and $Path -eq '/api/db/backup-schedule'){return $true}
    if($Method -eq 'POST' -and $Path -in @('/api/db/backup-delete','/api/db/prune-backup-dump-pods')){return $true}
    if($Path -eq '/api/docker/setup'){return $true}
    if($Method -eq 'GET' -and $Path -in @('/api/gameplay/status','/api/gameplay/market/items','/api/gameplay/market/listings','/api/gameplay/market/sales','/api/gameplay/market/stats','/api/gameplay/market/categories','/api/gameplay/market/catalog')){return $true}
    if($Method -eq 'GET' -and ($Path -in @('/api/v1/inventory/players','/api/v1/inventory/items','/api/v1/inventory/items/occurrences') -or $Path -cmatch '^/api/v1/inventory/items/[A-Za-z0-9_][A-Za-z0-9_().-]{0,199}/occurrences$')){return $true}
    if($Method -eq 'POST' -and $Path -eq '/api/v1/inventory/refresh'){return $true}
    if($Method -eq 'GET' -and ($Path -eq '/api/gameplay/vehicles' -or $Path -cmatch '^/api/gameplay/vehicles/[1-9][0-9]{0,15}/integrity$')){return $true}
    if($Method -eq 'GET' -and $Path -eq '/api/gameconfig/ini-backups'){return $true}
    if($Method -eq 'POST' -and $Path -in @('/api/gameconfig/ini-backups/download','/api/gameconfig/ini-backups/delete')){return $true}
    if($Method -eq 'GET' -and $Path -in @('/api/gameplay/blueprints/export','/api/gameplay/bases/export')){return $true}
    if($Method -eq 'POST' -and $Path -in @('/api/gameplay/blueprints/import','/api/gameplay/storage/repair-all','/api/gameplay/storage/rename','/api/gameplay/storage/give-item','/api/gameplay/storage/give-items','/api/gameplay/storage/delete-item','/api/gameplay/storage/set-item-stack','/api/gameplay/bases/destroy-claim')){return $true}
    if($Method -eq 'GET' -and $Path -in @('/api/v1/maps/catalog','/api/v1/maps/deep-desert','/api/v1/maps/deep-desert/layers/active-spice','/api/v1/maps/deep-desert/layers/public-poi')){return $true}
    if($Path -eq '/api/gameconfig/regis-tanks' -and $Method -in @('GET','PUT')){return $true}
    if($Path -eq '/api/gameconfig/regis-tanks/recover' -and $Method -eq 'POST'){return $true}
    if($Path -eq '/api/gameplay/vehicles/regis-tanks' -and $Method -in @('GET','POST')){return $true}
    if($Method -eq 'POST' -and $Path -in @('/api/docker/owner/setup','/api/portal-auth/login','/api/portal-auth/logout','/api/portal-auth/change-password')){return $true}
    if($Path -eq '/api/docker/resources' -and $Method -in @('GET','PUT')){return $true}
    if($Path -eq '/api/docker/memory-balancing' -and $Method -in @('GET','PUT')){return $true}
    if($Method -eq 'GET' -and $Path -cmatch '^/api/docker/log-exports/[a-f0-9]{32}$'){return $true}
    if($Method -eq 'POST'){
        if($Path -eq '/api/docker/client-files/transform'){return $true}
        if($Path -eq '/api/restart-schedule/check-update'){return $true}
        if($Path -eq '/api/map-spinup/CB_Story_DestroyedZanovar/party-sharing'){return $true}
        if($Path -cmatch '^/api/map-spinup/[A-Za-z0-9_]+$'){return $true}
        if($Path -match '^/api/commands/run/[a-z0-9-]+$|^/api/maps/(deepdesert|arakeen|harkovillage|survival|overmap)/(start|stop)$'){return $true}
    }
    if($Method -eq 'GET' -and $Path -match '^/api/maps/(deepdesert|arakeen|harkovillage|survival|overmap)$'){return $true}
    switch($Method){
        GET {return $Path -in @(
            '/api/ping',
            '/api/version',
            '/api/status',
            '/api/links',
            '/api/gameconfig',
            '/api/gameconfig/schema',
            '/api/gameconfig/retail-startup-sync',
            '/api/gameconfig/defaults',
            '/api/gameconfig/retail-server-settings',
            '/api/gameconfig/backups',
            '/api/gameconfig/experimental/categories',
            '/api/gameconfig/experimental/category',
            '/api/gameconfig/experimental/search',
            '/api/gameconfig/time-of-day',
            '/api/gameconfig/deep-desert-pvp',
            '/api/gameconfig/base-backup-guard',
            '/api/gameconfig/landclaim-timer',
            '/api/restart-schedule',
            '/api/map-spinup',
            '/api/installation',
            '/api/v1/platform/status',
            '/api/v1/capabilities',
            '/api/portal-auth/status',
            '/api/db/info',
            '/api/commands',
            '/api/gameplay/players',
            '/api/gameplay/players/online',
            '/api/gameplay/players/summary',
            '/api/gameplay/players/factions',
            '/api/gameplay/players/specs',
            '/api/gameplay/players/journey',
            '/api/gameplay/players/cosmetics-owned',
            '/api/gameplay/players/keystones',
            '/api/gameplay/players/vehicles',
            '/api/gameplay/players/dungeons',
            '/api/gameplay/players/trainer-status',
            '/api/gameplay/players/codex',
            '/api/gameplay/players/detail',
            '/api/gameplay/players/stats',
            '/api/gameplay/players/tags',
            '/api/gameplay/players/events',
            '/api/catalog/items',
            '/api/catalog/cosmetics',
            '/api/catalog/vehicle-kits',
            '/api/catalog/character-defs',
            '/api/v1/maps/atlas/view',
            '/api/v1/maps/atlas/resource',
            '/api/gameplay/players/partitions',
            '/api/gameplay/players/trainers',
            '/api/gameplay/players/main-quests',
            '/api/gameplay/tags/catalog',
            '/api/gameplay/contracts',
            '/api/gameplay/progression/presets',
            '/api/gameplay/augments/catalog',
            '/api/gameplay/bases',
            '/api/gameplay/storage',
            '/api/gameplay/storage/items',
            '/api/gameplay/blueprints',
            '/api/gameplay/item-packages',
            '/api/gameplay/players/char-xp',
            '/api/gameplay/players/reserve-recovery',
            '/api/gameplay/players/base-water-summary',
            '/api/gameplay/players/export',
            '/api/gameplay/players/player-ids'
        )}
        POST {return $Path -in @(
            '/api/broadcasts/generic',
            '/api/broadcasts/shutdown',
            '/api/v1/maps/atlas/session',
            '/api/v1/maps/atlas/resource',
            '/api/commands/layout/reset',
            '/api/status/refresh',
            '/api/maps/restart-pods',
            '/api/gameconfig/backups/delete',
            '/api/gameconfig/backup',
            '/api/gameconfig/reload-pods',
            '/api/gameconfig/time-of-day/stage',
            '/api/gameconfig/time-of-day/restore',
            '/api/restart-schedule/test-discord',
            '/api/db/query',
            '/api/gameplay/players/rename',
            '/api/gameplay/players/give-item',
            '/api/gameplay/players/give-items',
            '/api/gameplay/players/give-solari',
            '/api/gameplay/players/fill-water',
            '/api/gameplay/players/repair-gear',
            '/api/gameplay/players/restore-destroyed',
            '/api/gameplay/players/journey/complete',
            '/api/gameplay/players/progression/apply-preset',
            '/api/gameplay/players/journey/reset',
            '/api/gameplay/players/journey/reset-story',
            '/api/gameplay/players/journey/wipe',
            '/api/gameplay/players/unlock-main-quest',
            '/api/gameplay/players/unlock-trainer',
            '/api/gameplay/players/grant-job-skills',
            '/api/gameplay/players/reset-job-skills',
            '/api/gameplay/players/set-starter-class',
            '/api/gameplay/players/grant-all-skills',
            '/api/gameplay/players/unlock-testing-stations',
            '/api/gameplay/players/codex/grant',
            '/api/gameplay/players/delete-item',
            '/api/gameplay/players/repair-item',
            '/api/gameplay/players/set-item-durability',
            '/api/gameplay/players/set-item-water',
            '/api/gameplay/players/set-item-stack',
            '/api/gameplay/players/give-scrip',
            '/api/gameplay/players/award-intel',
            '/api/gameplay/players/award-char-xp',
            '/api/gameplay/players/set-spec-level',
            '/api/gameplay/players/apply-spec-level',
            '/api/gameplay/players/give-faction-rep',
            '/api/gameplay/players/set-faction-tier',
            '/api/gameplay/players/grant-max-spec',
            '/api/gameplay/players/reset-spec',
            '/api/gameplay/players/reset-all-specs',
            '/api/gameplay/players/grant-all-keystones',
            '/api/gameplay/players/reset-all-keystones',
            '/api/gameplay/players/prepare-pattern-upgrading',
            '/api/gameplay/players/set-weapon-ammo',
            '/api/gameplay/players/kick',
            '/api/gameplay/players/set-skill-points',
            '/api/gameplay/players/clean-inventory',
            '/api/gameplay/players/reset-progression',
            '/api/gameplay/players/set-skill-module',
            '/api/gameplay/players/give-item-live',
            '/api/gameplay/players/cheat-script',
            '/api/gameplay/players/grant-live',
            '/api/gameplay/players/grant-house-swatches',
            '/api/gameplay/players/grant-building-sets',
            '/api/gameplay/players/grant-skins',
            '/api/gameplay/players/reviewed-customization',
            '/api/gameplay/players/reserve-recovery',
            '/api/gameplay/players/reserve-recovery/rollback',
            '/api/gameplay/players/fill-base-water'
        )}
        PUT {return $Path -in @('/api/commands/layout','/api/gameplay/item-packages','/api/gameconfig','/api/gameconfig/retail-server-settings','/api/gameconfig/retail-startup-sync','/api/gameconfig/deep-desert-pvp','/api/gameconfig/base-backup-guard','/api/gameconfig/landclaim-timer','/api/restart-schedule')}
        DELETE {return $Path -eq '/api/gameplay/item-packages'}
    }
    return $false
}
