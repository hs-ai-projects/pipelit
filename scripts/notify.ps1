# Pipelit notify hook (Windows 11)
param(
    [string]$Message = "Claude Code is waiting for your input"
)

try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $icon = [System.Drawing.SystemIcons]::Application
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = $icon
    $notify.Visible = $true

    # Windows 11: use ShowBalloonTip via reflection to bypass deprecation warning
    $notify.BalloonTipTitle = "Pipelit"
    $notify.BalloonTipText = $Message
    $notify.ShowBalloonTip(5000)
    Start-Sleep -Milliseconds 500
    $notify.Dispose()
} catch {
    # fallback: try msg command (non-blocking)
    try { msg "$env:USERNAME" /time:10 "Pipelit: $Message" 2>$null } catch {}
    exit 0
}
