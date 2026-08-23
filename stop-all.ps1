# 停止 opencode 前端、后端和 pdf2json MCP 服务
$stopped = @()

foreach ($port in 4096, 4444, 8000) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            $proc = Get-Process -Id $_ -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
                $stopped += "端口 $port - $($proc.ProcessName) (PID: $_)"
            }
        }
    }
}

if ($stopped.Count -gt 0) {
    Write-Host "已停止以下服务:"
    $stopped | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "没有发现运行中的服务"
}
