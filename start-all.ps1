# 启动 opencode 前端、后端和 pdf2json MCP 服务
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# bun 在 PATH 上可能是 .ps1 shim（Start-Process 无法执行），显式解析真实 bun.exe
$bunExe = Get-Command bun.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $bunExe -or -not (Test-Path $bunExe)) {
    $bunExe = Join-Path $env:USERPROFILE ".bun\bin\bun.exe"
}
if (-not (Test-Path $bunExe)) {
    Write-Error "未找到 bun.exe，请安装 Bun 或把 bun 加入 PATH"; exit 1
}

# 停止占用端口的旧进程
foreach ($port in 4096, 4444, 8000) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        Write-Host "已停止端口 $port 上的旧进程"
    }
}

# 启动后端
Start-Process -FilePath $bunExe -ArgumentList "run", "--conditions=browser", "./src/index.ts", "serve", "--port", "4096" `
    -WorkingDirectory (Join-Path $repoRoot "packages\opencode") -WindowStyle Minimized
Write-Host "后端启动中... (http://127.0.0.1:4096)"

# 启动前端
Start-Process -FilePath $bunExe -ArgumentList "dev", "--", "--port", "4444" `
    -WorkingDirectory (Join-Path $repoRoot "packages\app") -WindowStyle Minimized
Write-Host "前端启动中... (http://localhost:4444)"

# 启动 pdf2json MCP
$pdf2jsonDir = Join-Path $repoRoot "mcps\pdf2json"
$pythonExe = Join-Path $pdf2jsonDir ".venv\Scripts\python.exe"
Start-Process -FilePath $pythonExe -ArgumentList "-m", "mcp_server" `
    -WorkingDirectory $pdf2jsonDir -WindowStyle Minimized
Write-Host "pdf2json MCP 启动中... (http://127.0.0.1:8000/mcp)"

Write-Host "`n全部服务已启动:"
Write-Host "  后端:         http://127.0.0.1:4096"
Write-Host "  前端:         http://localhost:4444"
Write-Host "  pdf2json MCP: http://127.0.0.1:8000/mcp"
