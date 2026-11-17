Describe 'Docker test runner discovery' {
    It 'uses existing test filenames with exact case on every platform' {
        $root = $PSScriptRoot
        $tokens = $null
        $errors = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $root 'Run-DockerTests.ps1'), [ref]$tokens, [ref]$errors)
        $errors | Should -BeNullOrEmpty
        $names = @($ast.FindAll({ param($node)
            $node -is [Management.Automation.Language.StringConstantExpressionAst] -and
            $node.Value -match '^[A-Za-z]+\.Tests\.ps1$'
        }, $true) | ForEach-Object Value)
        $names.Count | Should -BeGreaterThan 0
        $files = @(Get-ChildItem -LiteralPath $root -File | ForEach-Object Name)
        foreach ($name in $names) {
            $files | Should -Contain $name
            @($files | Where-Object { $_ -ceq $name }).Count | Should -Be 1
        }
    }
}
