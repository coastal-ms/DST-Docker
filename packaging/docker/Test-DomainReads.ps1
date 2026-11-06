$ErrorActionPreference = 'Stop'
$settings = Get-Content /data/config/DuneServer/docker-database.json -Raw | ConvertFrom-Json
if ($settings.host -ne '127.0.0.1' -or $settings.port -ne 18932 -or $settings.database -ne 'dune' -or $settings.allowWrites) {
    throw 'This qualification requires the separate read-only Docker development database.'
}
$env:DST_HOSTING_BACKEND = 'docker'
foreach ($library in @('app/lib/Db-Postgres.ps1','app/server/lib/DockerDatabase.ps1','app/server/lib/Database.ps1',
    'app/server/lib/Gameplay.ps1','app/server/lib/GameplayPlayers.ps1','app/server/lib/PlayersWrites.ps1',
    'app/server/lib/PlayersRead.ps1','app/server/lib/GameplayWorld.ps1','app/server/lib/PlayersAdmin.ps1',
    'app/server/lib/SoloMode.ps1','app/server/lib/Codex.ps1')) {
    . (Join-Path /opt/dst $library)
}
$probes = @(
    @{name='Players'; run={Get-DunePlayersLive -Ip docker}},
    @{name='Online state'; run={Get-DunePlayersOnlineLive -Ip docker}},
    @{name='Player summary'; run={Get-DunePlayerSummaryLive -Ip docker}},
    @{name='Factions'; run={Get-DunePlayerFactionsLive -Ip docker}},
    @{name='Specializations'; run={Get-DunePlayerSpecsLive -Ip docker}},
    @{name='Journey'; run={Get-DunePlayerJourneyLive -Ip docker -AccountId 999999}},
    @{name='Missing-character codex guard'; expectedError='Codex records are unavailable for this character.'; run={Get-DunePlayerCodexLive -Ip docker -AccountId 999999}},
    @{name='Owned cosmetics'; run={Get-DunePlayerOwnedCosmeticsLive -Ip docker -AccountId 999999}},
    @{name='Keystones'; run={Get-DunePlayerKeystonesLive -Ip docker -PlayerId 999999}},
    @{name='Vehicles'; run={Get-DunePlayerVehiclesLive -Ip docker -ControllerId 999999}},
    @{name='Dungeons'; run={Get-DunePlayerDungeonsLive -Ip docker -PlayerId 999999}},
    @{name='Trainer status'; run={Get-DunePlayerTrainerStatusLive -Ip docker -AccountId 999999}},
    @{name='Inventory detail'; run={Get-DunePlayerDetailLive -Ip docker -PawnId 999999 -ControllerId 999999}},
    @{name='Bases'; run={Get-DuneBasesLive -Ip docker}},
    @{name='Storage'; run={Get-DuneStorageLive -Ip docker}},
    @{name='Storage items'; run={Get-DuneStorageItemsLive -Ip docker -ContainerId 999999}},
    @{name='Blueprints'; run={Get-DuneBlueprintsLive -Ip docker}}
)
$results = @(foreach ($probe in $probes) {
    try {
        $result = & $probe.run
        if ($probe.expectedError) {
            @{name=$probe.name; ok=(-not $result.ok -and $result.error -ceq $probe.expectedError); error=$(if (-not $result.ok -and $result.error -ceq $probe.expectedError) { '' } else { [string]$result.error })}
        } else { @{name=$probe.name; ok=[bool]$result.ok; error=[string]$result.error} }
    } catch {
        $expected = $probe.expectedError -and $_.Exception.Message -ceq $probe.expectedError
        @{name=$probe.name; ok=[bool]$expected; error=$(if ($expected) { '' } else { $_.Exception.Message })}
    }
})
$failed = @($results | Where-Object { -not $_.ok })
@{scope='Empty official Docker schema: existing native read queries, not populated-character acceptance'; checks=$results; passed=$results.Count-$failed.Count; failed=$failed.Count} | ConvertTo-Json -Depth 5
if ($failed.Count) { exit 1 }
