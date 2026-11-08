BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerRoutes.ps1'
}
Describe 'Docker adapter routing boundary' {
    It 'permits exact native Owner diagnostics and rename writes through the desktop-host boundary' {
        Test-DuneDockerOwnerHostRoute -Method POST -Path '/api/diagnostics/bundle'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method POST -Path '/api/diagnostics/bundle'|Should -BeTrue
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerOwnerHostRoute -Method $method -Path '/api/diagnostics/bundle'|Should -BeFalse}
        Test-DuneDockerOwnerHostRoute -Method POST -Path '/api/diagnostics/vm-health'|Should -BeFalse
        Test-DuneDockerOwnerHostRoute -Method POST -Path '/api/server/name'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method POST -Path '/api/server/name'|Should -BeTrue
        Test-DuneDockerOwnerHostRoute -Method PUT -Path '/api/server/name'|Should -BeFalse
    }
    It 'connects player status and bookmarks without exposing other player-portal methods' {
        Test-DuneDockerRouteQualified -Method GET -Path '/api/player-portal/status'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method POST -Path '/api/player-portal/status'|Should -BeFalse
        foreach($method in @('GET','POST','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/player-portal/teleports'|Should -BeTrue}
        Test-DuneDockerRouteQualified -Method PUT -Path '/api/player-portal/teleports'|Should -BeFalse
        Test-DuneDockerRouteQualified -Method GET -Path '/api/player-portal/teleports/extra'|Should -BeFalse
        Test-DuneDockerRouteQualified -Method POST -Path '/api/pods/prune-terminal-director'|Should -BeFalse
    }
    It 'keeps shared world, inspection and broker tools on their existing methods' {
        foreach($path in @('/api/gameplay/coriolis/set-farm-seed','/api/gameplay/coriolis/set-map-seed','/api/gameplay/coriolis/set-partition-seed','/api/gameplay/vehicles/spawn','/api/gameplay/chat/whisper')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeFalse
            Test-DuneDockerRouteQualified -Method POST -Path ($path+'/extra')|Should -BeFalse
        }
        foreach($path in @('/api/gameplay/coriolis/seeds','/api/gameplay/storage/owner-debug')){
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
        }
        foreach($method in @('GET','PUT')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/welcome-back'|Should -BeTrue}
        Test-DuneDockerRouteQualified -Method DELETE -Path '/api/gameplay/welcome-back'|Should -BeFalse
    }
    It 'connects existing SQL-backed player tools without opening adjacent routes' {
        foreach($path in @('/api/gameplay/players/delete-account','/api/gameplay/players/delete-tutorials','/api/gameplay/players/wipe-codex','/api/gameplay/players/grant-all-tech','/api/gameplay/players/progression-unlock','/api/gameplay/players/progression-reverse','/api/gameplay/players/faction/reset')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path $path|Should -BeFalse}
            Test-DuneDockerRouteQualified -Method POST -Path ($path+'/extra')|Should -BeFalse
        }
    }
    It 'opens only the three exact native contract mutation methods' {
        foreach($path in @('/api/gameplay/players/contract/complete','/api/gameplay/players/contracts/complete','/api/gameplay/players/contracts/reverse')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path $path|Should -BeFalse}
            Test-DuneDockerRouteQualified -Method POST -Path ($path+'/extra')|Should -BeFalse
        }
    }
    It 'bounds native purchase snapshot and restore routes to exact existing methods' {
        foreach($path in @('/api/gameplay/players/fresh-start/snapshots','/api/gameplay/players/fresh-start/snapshots-path')){
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
        }
        foreach($path in @('/api/gameplay/players/fresh-start/snapshot','/api/gameplay/players/fresh-start/restore','/api/gameplay/players/fresh-start/restore-skip-npe')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeFalse
            Test-DuneDockerRouteQualified -Method POST -Path ($path+'/extra')|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/fresh-start/wipe'|Should -BeFalse
    }
    It 'bounds native augment maximization to the exact existing write method' {
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/max-augment-attributes'|Should -BeTrue
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/players/max-augment-attributes'|Should -BeFalse}
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/max-augment-attributes/extra'|Should -BeFalse
    }
    It 'opens only the exact native orphaned-building-piece repair write' {
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/repair-orphaned-building-pieces'|Should -BeTrue
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/players/repair-orphaned-building-pieces'|Should -BeFalse}
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/repair-orphaned-building-pieces/extra'|Should -BeFalse
    }
    It 'qualifies exact native character tag write methods' {
        foreach($path in @('/api/gameplay/players/tags','/api/gameplay/players/update-tags')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method DELETE -Path $path|Should -BeFalse
            Test-DuneDockerRouteQualified -Method POST -Path ($path+'/extra')|Should -BeFalse
        }
    }
    It 'allows only the exact startup preference write through the native Owner host exception' {
        Test-DuneDockerOwnerHostRoute -Method PUT -Path '/api/gameconfig/retail-startup-sync'|Should -BeTrue
        foreach($method in @('GET','POST','DELETE')){Test-DuneDockerOwnerHostRoute -Method $method -Path '/api/gameconfig/retail-startup-sync'|Should -BeFalse}
        foreach($path in @('/api/gameconfig/retail-startup-sync/extra','/api/gameconfig','/api/gameconfig/retail-server-settings')){Test-DuneDockerOwnerHostRoute -Method PUT -Path $path|Should -BeFalse}
    }

    It 'bounds account administration to exact IDs and keeps login-mode changes closed' {
        foreach($method in @('GET','POST')){Test-DuneDockerAccountManagementRoute -Method $method -Path '/api/remote-access/portal-accounts'|Should -BeTrue}
        foreach($method in @('PUT','DELETE')){Test-DuneDockerAccountManagementRoute -Method $method -Path ('/api/remote-access/portal-accounts/'+('a'*32))|Should -BeTrue}
        foreach($suffix in @('reset-password','revoke-sessions')){Test-DuneDockerAccountManagementRoute -Method POST -Path ('/api/remote-access/portal-accounts/'+('a'*32)+'/'+$suffix)|Should -BeTrue}
        foreach($path in @('/api/remote-access/portal-account-mode','/api/remote-access/portal-accounts/verify-owner','/api/remote-access/portal-accounts/../reset-password')){Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse}
        Test-DuneDockerRouteQualified -Method PUT -Path '/api/remote-access/portal-account-mode'|Should -BeFalse
    }

    It 'qualifies exact base and storage adapters without broad prefixes' {
        foreach($path in @('/api/gameplay/blueprints/export','/api/gameplay/bases/export')){Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue}
        foreach($path in @('/api/gameplay/blueprints/import','/api/gameplay/storage/repair-all','/api/gameplay/storage/rename','/api/gameplay/storage/give-item','/api/gameplay/storage/give-items','/api/gameplay/storage/delete-item','/api/gameplay/storage/set-item-stack','/api/gameplay/bases/destroy-claim')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method DELETE -Path $path|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/storage/delete-all'|Should -BeFalse
    }

    It 'allows only native server INI backup list, download and delete methods' {
        Test-DuneDockerRouteQualified -Method GET -Path '/api/gameconfig/ini-backups'|Should -BeTrue
        foreach($path in @('/api/gameconfig/ini-backups/download','/api/gameconfig/ini-backups/delete')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method DELETE -Path '/api/gameconfig/ini-backups'|Should -BeFalse
    }

    It 'qualifies fleet reads and exact name changes while preserving other vehicle mutation gates' {
        foreach($path in @('/api/gameplay/vehicles','/api/gameplay/vehicles/700204/integrity')){
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/vehicles/names'|Should -BeTrue
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/vehicles/names'|Should -BeFalse}
        foreach($path in @('/api/gameplay/vehicles/names/extra','/api/gameplay/vehicles/repair','/api/gameplay/vehicles/../integrity','/api/gameplay/vehicles/0/integrity')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeFalse
        }
    }

    It 'bounds native Owner deletion to exact methods and queue IDs without broad host exceptions' {
        foreach($path in @('/api/gameplay/vehicles/delete','/api/gameplay/vehicles/deletions','/api/gameplay/vehicles/deletions/process')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerOwnerHostRoute -Method POST -Path $path|Should -BeTrue
        }
        Test-DuneDockerRouteQualified -Method GET -Path '/api/gameplay/vehicles/deletions'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method DELETE -Path ('/api/gameplay/vehicles/deletions/'+('a'*32))|Should -BeTrue
        foreach($path in @('/api/gameplay/vehicles/delete/all','/api/gameplay/vehicles/deletions/process/extra','/api/gameplay/vehicles/deletions/../process','/api/console','/api/db/query')){
            Test-DuneDockerOwnerHostRoute -Method POST -Path $path|Should -BeFalse
        }
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/vehicles/delete'|Should -BeFalse}
        Test-DuneDockerRouteQualified -Method DELETE -Path '/api/gameplay/vehicles/deletions/not-an-id'|Should -BeFalse
    }

    It 'opens the existing module repair adapter without other vehicle write methods' {
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/repair-vehicle'|Should -BeTrue
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/players/repair-vehicle'|Should -BeFalse}
        foreach($path in @('/api/gameplay/players/repair-vehicle/all','/api/gameplay/vehicles/repair')){Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse}
    }
    It 'opens only the exact native refuel method' {
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/refuel-vehicle'|Should -BeTrue
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/players/refuel-vehicle'|Should -BeFalse}
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/refuel-vehicle/all'|Should -BeFalse
    }

    It 'allows derived inventory reads and refresh without opening arbitrary item methods' {
        foreach($path in @('/api/v1/inventory/players','/api/v1/inventory/items','/api/v1/inventory/items/occurrences','/api/v1/inventory/items/DT_Resource(1).Test/occurrences')) {
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method DELETE -Path $path|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method POST -Path '/api/v1/inventory/refresh'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method GET -Path '/api/v1/inventory/items/../occurrences'|Should -BeFalse
        Test-DuneDockerRouteQualified -Method POST -Path '/api/v1/inventory/items'|Should -BeFalse
    }
    It 'keeps market inspection separate from explicit bot methods' {
        foreach($path in @('/api/gameplay/status','/api/gameplay/market/items','/api/gameplay/market/listings','/api/gameplay/market/sales','/api/gameplay/market/stats','/api/gameplay/market/categories','/api/gameplay/market/catalog')) {
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/market-bot/exec'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method GET -Path '/api/gameplay/market/unreviewed'|Should -BeFalse
    }

    It 'bounds native market automation to existing exact methods' {
        foreach($path in @('/api/gameplay/market-bot/status','/api/gameplay/market-bot/config','/api/gameplay/market-bot/balance','/api/gameplay/market-bot/vendor-snapshot')){Test-DuneDockerMarketBotRoute -Method GET -Path $path|Should -BeTrue}
        Test-DuneDockerMarketBotRoute -Method PUT -Path '/api/gameplay/market-bot/config'|Should -BeTrue
        foreach($path in @('/api/gameplay/market-bot/config/reset','/api/gameplay/market-bot/exec','/api/gameplay/market-bot/tick','/api/gameplay/market-bot/balance','/api/gameplay/market-bot/clear-listings','/api/gameplay/market-bot/clear-legacy-listings','/api/gameplay/market-bot/tick/list','/api/gameplay/market-bot/clear-error','/api/gameplay/market-bot/seed','/api/gameplay/market-bot/seed/abort')){Test-DuneDockerMarketBotRoute -Method POST -Path $path|Should -BeTrue}
        foreach($path in @('/api/gameplay/market-bot/exec/extra','/api/gameplay/market-bot/tick/all','/api/gameplay/market-bot/arbitrary','/api/gameplay/market-bot/../exec')){Test-DuneDockerMarketBotRoute -Method POST -Path $path|Should -BeFalse}
        foreach($method in @('GET','PUT','DELETE')){Test-DuneDockerMarketBotRoute -Method $method -Path '/api/gameplay/market-bot/exec'|Should -BeFalse}
    }
    It 'exposes only the native browser backup routes and bounded download identities' {
        foreach($path in @('/api/db/backup-schedule','/api/db/backup-history','/api/db/backup-dump-pods')){Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue}
        Test-DuneDockerRouteQualified -Method POST -Path '/api/docker/backup-import'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method GET -Path ('/api/docker/backup-exports/'+('a'*32))|Should -BeTrue
        Test-DuneDockerRouteQualified -Method GET -Path '/api/docker/backup-exports/../manager.sock'|Should -BeFalse
        Test-DuneDockerRouteQualified -Method POST -Path '/api/db/backup-upload'|Should -BeFalse
    }
    It 'allows only typed resource reads and updates' {
        Test-DuneDockerRouteQualified -Method GET -Path '/api/docker/resources' | Should -BeTrue
        Test-DuneDockerRouteQualified -Method PUT -Path '/api/docker/resources' | Should -BeTrue
        Test-DuneDockerRouteQualified -Method POST -Path '/api/docker/resources' | Should -BeFalse
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameconfig/landclaim-timer' | Should -BeFalse
    }
    It 'keeps native reads and typed mutations available' -TestCases @(
        @{Method='GET';Path='/api/status'},
        @{Method='GET';Path='/api/links'},
        @{Method='GET';Path='/api/gameplay/item-packages'},
        @{Method='PUT';Path='/api/gameplay/item-packages'},
        @{Method='DELETE';Path='/api/gameplay/item-packages'},
        @{Method='POST';Path='/api/gameplay/players/journey/reset'},
        @{Method='POST';Path='/api/restart-schedule/check-update'},
        @{Method='POST';Path='/api/docker/client-files/transform'},
        @{Method='POST';Path='/api/gameplay/players/set-item-water'},
        @{Method='POST';Path='/api/gameplay/players/reset-all-specs'},
        @{Method='POST';Path='/api/gameplay/players/set-weapon-ammo'},
        @{Method='POST';Path='/api/maps/deepdesert/start'},
        @{Method='POST';Path='/api/map-spinup/SH_HarkoVillage'}
        @{Method='POST';Path='/api/map-spinup/CB_Story_DestroyedZanovar/party-sharing'},
        @{Method='POST';Path='/api/maps/restart-pods'}
        @{Method='GET';Path='/api/gameconfig/time-of-day'},
        @{Method='POST';Path='/api/gameconfig/time-of-day/stage'},
        @{Method='POST';Path='/api/gameconfig/time-of-day/restore'},
        @{Method='GET';Path='/api/gameconfig/deep-desert-pvp'},
        @{Method='GET';Path='/api/gameconfig/landclaim-timer'},
        @{Method='PUT';Path='/api/gameconfig/landclaim-timer'},
        @{Method='PUT';Path='/api/gameconfig/deep-desert-pvp'},
        @{Method='GET';Path='/api/gameconfig/base-backup-guard'},
        @{Method='PUT';Path='/api/gameconfig/base-backup-guard'}
        @{Method='GET';Path='/api/restart-schedule'},
        @{Method='PUT';Path='/api/restart-schedule'}
        @{Method='POST';Path='/api/restart-schedule/test-discord'}
    ) {
        param($Method,$Path)
        Test-DuneDockerRouteQualified -Method $Method -Path $Path | Should -BeTrue
    }
    It 'does not open unported methods, arbitrary maps or path suffixes' -TestCases @(
        @{Method='DELETE';Path='/api/gameplay/players'},
        @{Method='POST';Path='/api/gameplay/item-packages'},
        @{Method='PATCH';Path='/api/commands/layout'},
        @{Method='POST';Path='/api/maps/other/start'},
        @{Method='POST';Path='/api/maps/deepdesert/start/extra'},
        @{Method='GET';Path='/api/maps/deepdesert/start'},
        @{Method='POST';Path='/api/map-spinup/../other'},
        @{Method='POST';Path='/api/map-spinup/SH_HarkoVillage/party-sharing'},
        @{Method='POST';Path='/api/system/reveal-config'}
        @{Method='GET';Path='/api/docker/client-files/transform'},
        @{Method='POST';Path='/api/docker/client-files/transform/other'}
    ) {
        param($Method,$Path)
        Test-DuneDockerRouteQualified -Method $Method -Path $Path | Should -BeFalse
    }
}

Describe 'Native Landsraad method boundary' {
    It 'qualifies exact read and write methods without widening neighboring paths' {
        foreach($suffix in @('overview','player-contributions','rewards','term-control')){
            $path='/api/gameplay/landsraad/'+$suffix
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
        }
        foreach($suffix in @('set-contribution','set-thresholds','set-reward-tier','set-term-control','restart-bg')){
            $path='/api/gameplay/landsraad/'+$suffix
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeFalse
            Test-DuneDockerRouteQualified -Method POST -Path ($path+'/extra')|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/landsraad/reset'|Should -BeFalse
    }
}

Describe 'Native chat command route boundary' {
    It 'opens only settings and exact bookmark methods' {
        foreach($method in @('GET','PUT')){Test-DuneDockerRouteQualified -Method $method -Path '/api/gameplay/chat-commands'|Should -BeTrue}
        foreach($suffix in @('teleports','teleports/capture')){
            foreach($method in @('POST','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path ('/api/gameplay/chat-commands/'+$suffix)|Should -BeTrue}
            Test-DuneDockerRouteQualified -Method PUT -Path ('/api/gameplay/chat-commands/'+$suffix)|Should -BeFalse
        }
        foreach($path in @('/api/gameplay/chat-commands/exec','/api/gameplay/chat-commands/teleports/extra')){Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse}
    }
}

Describe 'Native player coordinate method boundary' {
    It 'opens only exact destination read teleport and respawn methods' {
        Test-DuneDockerRouteQualified -Method GET -Path '/api/gameplay/players/teleport-destinations'|Should -BeTrue
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/players/teleport-destinations'|Should -BeFalse
        foreach($suffix in @('teleport-to-player','teleport-to-location','set-respawn')){
            $path='/api/gameplay/players/'+$suffix
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method DELETE -Path $path|Should -BeFalse
            Test-DuneDockerRouteQualified -Method POST -Path ($path+'/extra')|Should -BeFalse
        }
    }
}
