# UTF-8
if ($PSVersionTable.PSVersion.Major -lt 6) {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
}

$EngineRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $EngineRoot ".venv\Scripts\python.exe"
$Port = 8765

if (-not (Test-Path $Python)) {
    Write-Error "未找到 Python：$Python`n请先执行：python -m venv .venv；pip install -e ."
    exit 1
}

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $listeners) {
    $procId = $conn.OwningProcess
    if ($procId -and $procId -ne 0) {
        Write-Host "  停止占用端口 $Port 的旧进程 (PID $procId)…" -ForegroundColor Yellow
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 400
    }
}

Write-Host ""
Write-Host "  NovelScript Web Portal" -ForegroundColor Cyan
Write-Host "  工作台：  http://127.0.0.1:$Port/" -ForegroundColor Green
Write-Host "  新建项目：http://127.0.0.1:$Port/create.html" -ForegroundColor Green
Write-Host "  健康检查：http://127.0.0.1:$Port/api/health" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  按 Ctrl+C 停止" -ForegroundColor DarkGray
Write-Host ""

& $Python (Join-Path $PSScriptRoot "server.py") $Port