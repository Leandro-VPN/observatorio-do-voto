$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pidFile = Join-Path $projectRoot 'storage/server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output 'Sem serviço registrado. Se iniciou em um terminal, use Ctrl+C nele.'
    exit 0
}
$serverId = [int](Get-Content -LiteralPath $pidFile)
$server = Get-CimInstance Win32_Process -Filter "ProcessId = $serverId"
if (-not $server) {
    Write-Output 'Serviço já encerrado.'
    exit 0
}
$expectedPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if ($server.ExecutablePath -ne $expectedPython -or $server.CommandLine -notmatch '-m\s+auditabr\s+serve') {
    throw 'O PID registrado não corresponde ao serviço deste projeto; nenhuma ação executada.'
}
function Stop-ProjectTree([int]$targetId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $targetId")
    foreach ($child in $children) { Stop-ProjectTree ([int]$child.ProcessId) }
    Stop-Process -Id $targetId -ErrorAction SilentlyContinue
}
Stop-ProjectTree $serverId
Write-Output 'Painel e API encerrados. Dados preservados.'
