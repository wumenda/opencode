# 启动 opencode 后端和前端服务
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# 停止占用端口的旧进程
foreach ($port in 4096, 4444) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        Write-Host "已停止端口 $port 上的旧进程"
    }
}

# 启动后端
Start-Process -FilePath "bun" -ArgumentList "run,--conditions=browser,./src/index.ts,serve,--port,4096" `
    -WorkingDirectory (Join-Path $repoRoot "packages\opencode") -WindowStyle Minimized
Write-Host "后端启动中... (http://127.0.0.1:4096)"

# 启动前端
Start-Process -FilePath "bun" -ArgumentList "x,vite,--port,4444" `
    -WorkingDirectory (Join-Path $repoRoot "packages\app") -WindowStyle Minimized
Write-Host "前端启动中... (http://localhost:4444)"

# 等待端口就绪
Start-Sleep -Seconds 5

$ok = $true
foreach ($port in 4096, 4444) {
    if (-not (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue)) {
        Write-Host "警告: 端口 $port 未就绪"
        $ok = $false
    }
}

if ($ok) {
    Write-Host "`n全部服务已启动:"
    Write-Host "  后端: http://127.0.0.1:4096"
    Write-Host "  前端: http://localhost:4444"
} else {
    Write-Host "`n部分服务启动失败，请检查对应窗口的日志"
}
