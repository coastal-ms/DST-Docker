BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerMarket.ps1'
    Import-DstLib 'GameplayBot.ps1'
    $script:oldBackend=$env:DST_HOSTING_BACKEND
    $script:oldJobs=[AppDomain]::CurrentDomain.GetData('DST.NativeMarketJobs')
    $script:marketLib=Join-Path (Get-DstRepoRoot) 'app/server/lib/DockerMarket.ps1'
    $script:botLib=Join-Path (Get-DstRepoRoot) 'app/server/lib/GameplayBot.ps1'
}
AfterAll {
    $env:DST_HOSTING_BACKEND=$script:oldBackend
    [AppDomain]::CurrentDomain.SetData('DST.NativeMarketJobs',$script:oldJobs)
}
Describe 'Native market jobs shared by worker runspaces' {
    BeforeEach {
        $env:DST_HOSTING_BACKEND='docker'
        [AppDomain]::CurrentDomain.SetData('DST.NativeMarketJobs',$null)
    }
    AfterEach { Clear-DuneDockerMarketCompletedJobs }
    It 'lets another API worker stop the active seed and persist its aborted state' {
        $path=Join-Path $TestDrive 'native-seed-state.json'
        [IO.File]::WriteAllText($path,'{"seed_progress":{"running":true,"phase":"writing"}}')
        $rs=[runspacefactory]::CreateRunspace();$rs.Open()
        $ps=[powershell]::Create();$ps.Runspace=$rs
        $null=$ps.AddScript({Start-Sleep -Seconds 30})
        $handle=$ps.BeginInvoke()
        $jobs=Get-DuneDockerMarketJobs
        $jobs['seed']=@{ps=$ps;rs=$rs;handle=$handle}
        $workerRs=[runspacefactory]::CreateRunspace();$workerRs.Open()
        $worker=[powershell]::Create();$worker.Runspace=$workerRs
        try {
            $null=$worker.AddScript({
                param($market,$bot,$state)
                . $market
                . $bot
                $script:nativeTestState=$state
                function Get-DuneBotStatePath {$script:nativeTestState}
                Stop-DuneBotSeedAsync
            }).AddArgument($script:marketLib).AddArgument($script:botLib).AddArgument($path)
            $result=@($worker.Invoke())
            $worker.HadErrors | Should -BeFalse
            $result[0].stopped | Should -BeTrue
            $jobs.ContainsKey('seed') | Should -BeFalse
            $saved=Get-Content $path -Raw | ConvertFrom-Json
            $saved.seed_progress.running | Should -BeFalse
            $saved.seed_progress.phase | Should -Be 'aborted'
        } finally {
            try {$ps.Stop();$ps.Dispose();$rs.Dispose()}catch{}
            $worker.Dispose();$workerRs.Dispose()
        }
    }
    It 'rejects duplicate seed or listing launches while either native job is active' {
        $rs=[runspacefactory]::CreateRunspace();$rs.Open()
        $ps=[powershell]::Create();$ps.Runspace=$rs
        $null=$ps.AddScript({Start-Sleep -Seconds 30});$handle=$ps.BeginInvoke()
        (Get-DuneDockerMarketJobs)['list']=@{ps=$ps;rs=$rs;handle=$handle}
        try {
            (Start-DuneBotSeedAsync -ServerDir 'invalid').running | Should -BeTrue
            (Start-DuneBotListTickAsync -ServerDir 'invalid').running | Should -BeTrue
        }finally{$ps.Stop();Clear-DuneDockerMarketCompletedJobs}
    }
    It 'allows the running listing job to perform its own relist cleanup' {
        $ready=[Threading.ManualResetEventSlim]::new($false)
        $go=[Threading.ManualResetEventSlim]::new($false)
        $rs=[runspacefactory]::CreateRunspace();$rs.Open()
        $ps=[powershell]::Create();$ps.Runspace=$rs
        $null=$ps.AddScript({
            param($lib,$ready,$go)
            . $lib
            $ready.Set();$null=$go.Wait(10000)
            @{any=(Test-DuneDockerMarketJobRunning);other=(Test-DuneDockerMarketJobRunning -ExcludeCurrentRunspace)}
        }).AddArgument($script:marketLib).AddArgument($ready).AddArgument($go)
        $handle=$ps.BeginInvoke()
        try{
            $ready.Wait(10000) | Should -BeTrue
            (Get-DuneDockerMarketJobs)['list']=@{ps=$ps;rs=$rs;handle=$handle}
            $go.Set();$result=@($ps.EndInvoke($handle))
            $result[0].any | Should -BeTrue
            $result[0].other | Should -BeFalse
            $ps.HadErrors | Should -BeFalse
        }finally{
            (Get-DuneDockerMarketJobs).Remove('list')
            try{$ps.Stop();$ps.Dispose();$rs.Dispose()}catch{}
            $ready.Dispose();$go.Dispose()
        }
    }
}
