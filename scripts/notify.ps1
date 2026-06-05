# Pipelit AskUserQuestion 通知脚本 (Windows)
# 由 Claude Code PreToolUse hook 调用，触发系统托盘气泡提示。
#
# 用法：powershell.exe -NonInteractive -ExecutionPolicy Bypass -File notify.ps1
#       或通过 .claude/settings.json hooks 自动触发

param(
    [string]$Message = "Pipelit 需要你的输入"
)

try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.Visible = $true
    $notify.BalloonTipTitle = "Pipelit"
    $notify.BalloonTipText = $Message
    $notify.BalloonTipIcon = "Info"
    $notify.ShowBalloonTip(8000)
    Start-Sleep -Seconds 2
    $notify.Dispose()
} catch {
    # 静默降级：通知失败不影响主流程
    exit 0
}
