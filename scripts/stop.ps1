# 停止 opencode 后端和前端服务，释放端口
# 递归杀掉进程树（bun 会 spawn 子进程，端口可能被子进程持有）

function Stop-ProcessTree($processId) {
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $processId }
    foreach ($child in $children) {
        Stop-ProcessTree $child.ProcessId
    }
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}

$stopped = @()

foreach ($port in 4096, 4444) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            $proc = Get-Process -Id $_ -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-ProcessTree $_
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

# 等待端口释放（最多 10 秒）
$ports = 4096, 4444
for ($i = 0; $i -lt 20; $i++) {
    $busy = $false
    foreach ($port in $ports) {
        if (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) {
            $busy = $true
            break
        }
    }
    if (-not $busy) { break }
    Start-Sleep -Milliseconds 500
}

if ($busy) {
    Write-Host "`n警告: 部分端口仍被占用:"
    foreach ($port in $ports) {
        if (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) {
            Write-Host "  端口 $port 仍被占用"
        }
    }
} else {
    Write-Host "`n所有端口已释放"
}
