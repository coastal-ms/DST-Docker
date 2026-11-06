$ErrorActionPreference = 'Stop'
$settings = Get-Content /data/config/DuneServer/docker-database.json -Raw | ConvertFrom-Json
if ($settings.host -ne '127.0.0.1' -or $settings.port -ne 18767) { throw 'Only the isolated fixture endpoint is allowed.' }
$env:DST_HOSTING_BACKEND = 'docker'
. /opt/dst/app/server/lib/DockerDatabase.ps1
. /opt/dst/app/server/lib/Database.ps1
. /opt/dst/app/server/lib/Gameplay.ps1
. /opt/dst/app/server/lib/GameplayPlayers.ps1
. /opt/dst/app/server/lib/PlayersWrites.ps1
$checks = [Collections.Generic.List[string]]::new()
$result = Invoke-DuneSqlQuery -Ip docker -Sql "SELECT 'Arrakis, dunes' AS name, E'line1\nline2' AS multiline, '生命' AS unicode, '' AS empty, NULL AS missing" -ReadOnly $true
if (-not $result.ok -or $result.rowCount -ne 1 -or $result.rows[0][0] -ne 'Arrakis, dunes' -or $result.rows[0][2] -ne '生命') { throw "CSV result contract failed: $($result | ConvertTo-Json -Depth 5)" }
$checks.Add('CSV parser preserves quoted values, multiline and Unicode through real Linux process transport')
$players = Get-DunePlayersLive -Ip docker
if (-not $players.ok -or @($players.players).Count -ne 1 -or $players.players[0].id -ne 101 -or $players.players[0].name -ne 'Fixture, 生命') { throw "Existing Players query failed: $($players | ConvertTo-Json -Depth 5)" }
$checks.Add('Unmodified existing Players SQL and row mapping return synthetic character through Docker')
$write = Invoke-DuneSqlQuery -Ip docker -Sql "BEGIN; UPDATE dune.player_state SET character_name='changed' WHERE player_pawn_id=101; ROLLBACK;" -ReadOnly $false -Bulk
if (-not $write.ok -or (Get-DuneSqlAffected $write) -ne 1) { throw "DML result contract failed: $($write | ConvertTo-Json -Depth 5)" }
$checks.Add('Bulk transaction and affected-row message retained')
$blocked = Invoke-DuneSqlQuery -Ip docker -Sql "UPDATE dune.player_state SET character_name='bad'" -ReadOnly $true
if ($blocked.ok -or $blocked.error -notmatch 'read-only') { throw 'Read-only UPDATE was not rejected.' }
$players = Get-DunePlayersLive -Ip docker
if ($players.players[0].name -ne 'Fixture, 生命') { throw 'Fixture changed after rollback/read-only rejection.' }
$checks.Add('Read-only write rejected and rollback leaves fixture unchanged')
$large = Invoke-DuneSqlQuery -Ip docker -Sql ("SELECT length('" + ('x' * 300000) + "') AS size") -ReadOnly $true -Bulk
if (-not $large.ok -or $large.rows[0][0] -ne '300000') { throw 'Large stdin transport failed.' }
$checks.Add('300KB SQL bypasses native command-line limits')
@{ok=$true; checks=@($checks)} | ConvertTo-Json -Depth 5
