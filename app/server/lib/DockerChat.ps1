$script:DuneDockerChatScheduler=$null

function Invoke-DuneDockerChatQueue {
    param([ValidateSet('declare','delete','drain')][string]$Action,[ValidateRange(1,25)][int]$Maximum=25)
    $reply=Invoke-DuneDockerManager -Request @{action=('chat.queue.'+$Action);maximum=$Maximum}
    if(-not $reply.ok){return @{ok=$false;message=$reply.error;messages=@()}}
    return @{ok=$true;messages=@($reply.data.messages);skipped=[bool]$reply.data.skipped;raw='ok'}
}

function Sync-DuneDockerChatQueue {
    Invoke-WithDuneLock -Name 'docker-chat-queue' -Script {
        $current=Read-DuneChatCommandsState
        $action=if($current.enabled -and (Test-DuneChatCommandsReady -State $current).ready){'declare'}else{'delete'}
        Invoke-DuneDockerChatQueue -Action $action
    }
}

function Start-DuneDockerChatScheduler {
    param([Parameter(Mandatory)][string]$ServerDir,[Threading.ManualResetEventSlim]$HttpReady)
    if($script:DuneDockerChatScheduler){return}
    if(-not $script:DuneApiLockTable){$script:DuneApiLockTable=[hashtable]::Synchronized(@{})}
    $cancel=[Threading.CancellationTokenSource]::new()
    $runspace=[runspacefactory]::CreateRunspace((New-DuneSchedulerInitialSessionState -ServerDir $ServerDir -DeferLibraryLoad))
    $runspace.Name='DuneDockerChatScheduler';$runspace.Open()
    $pipeline=[powershell]::Create();$pipeline.Runspace=$runspace
    [void]$pipeline.AddScript({param($ServerDir,$Ready,$Token,$Locks)
        if($Ready){$Ready.Wait($Token)}
        . (Join-Path $ServerDir 'HttpServer.ps1')
        foreach($source in $DuneSchedulerStartupScripts){$Token.ThrowIfCancellationRequested();. $source}
        $script:DuneApiLockTable=$Locks
        if($DuneSchedulerLogPath){Set-DuneLogPath -Path $DuneSchedulerLogPath}
        while(-not $Token.IsCancellationRequested){
            try{[void](Invoke-DuneChatCommandTick)}catch{Write-DuneLog ('Docker chat command tick: '+$_.Exception.Message) 'WARN'}
            $poll=3
            try{$poll=Get-DuneChatCommandPollSeconds}catch{}
            if($Token.WaitHandle.WaitOne([int]($poll*1000))){break}
        }
    }).AddArgument($ServerDir).AddArgument($HttpReady).AddArgument($cancel.Token).AddArgument($script:DuneApiLockTable)
    try{$handle=$pipeline.BeginInvoke();$script:DuneDockerChatScheduler=@{pipeline=$pipeline;runspace=$runspace;handle=$handle;cancel=$cancel}}
    catch{$pipeline.Dispose();$runspace.Dispose();$cancel.Dispose();throw}
}

function Stop-DuneDockerChatScheduler {
    param([ValidateRange(1,30000)][int]$WaitMs=5000)
    $job=$script:DuneDockerChatScheduler
    if(-not $job){return $true}
    $job.cancel.Cancel()
    if(-not $job.handle.AsyncWaitHandle.WaitOne([Math]::Min(1000,$WaitMs))){
        $null=$job.pipeline.BeginStop($null,$null)
        if(-not $job.handle.AsyncWaitHandle.WaitOne($WaitMs)){return $false}
    }
    try{$null=$job.pipeline.EndInvoke($job.handle)}catch [Management.Automation.PipelineStoppedException]{}catch{Write-DuneLog ('Docker chat scheduler stopped after a failure: '+$_.Exception.Message) 'WARN'}
    $job.pipeline.Dispose();$job.runspace.Close();$job.runspace.Dispose();$job.cancel.Dispose()
    $script:DuneDockerChatScheduler=$null
    return $true
}
