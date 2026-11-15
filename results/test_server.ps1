$ip = [System.Net.IPAddress]::Loopback
$port = 8080
try {
    $listener = [System.Net.Sockets.TcpListener]::new($ip, $port)
    $listener.Start()
    Write-Host "TCP_LISTENER_OK"
    $listener.Stop()
} catch {
    Write-Host "TCP_LISTENER_ERR: $($_.Exception.Message)"
}
