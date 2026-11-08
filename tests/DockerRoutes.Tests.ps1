BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerRoutes.ps1'
}
Describe 'Docker adapter routing boundary' {
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

    It 'qualifies fleet and bounded integrity reads while preserving vehicle mutation gates' {
        foreach($path in @('/api/gameplay/vehicles','/api/gameplay/vehicles/700204/integrity')){
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
        }
        foreach($path in @('/api/gameplay/vehicles/names','/api/gameplay/vehicles/delete','/api/gameplay/vehicles/repair','/api/gameplay/vehicles/../integrity','/api/gameplay/vehicles/0/integrity')){
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeFalse
        }
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
    It 'opens only qualified market reads without enabling vendor mutations' {
        foreach($path in @('/api/gameplay/status','/api/gameplay/market/items','/api/gameplay/market/listings','/api/gameplay/market/sales','/api/gameplay/market/stats','/api/gameplay/market/categories','/api/gameplay/market/catalog')) {
            Test-DuneDockerRouteQualified -Method GET -Path $path|Should -BeTrue
            Test-DuneDockerRouteQualified -Method POST -Path $path|Should -BeFalse
        }
        Test-DuneDockerRouteQualified -Method POST -Path '/api/gameplay/market-bot/exec'|Should -BeFalse
        Test-DuneDockerRouteQualified -Method GET -Path '/api/gameplay/market/unreviewed'|Should -BeFalse
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
