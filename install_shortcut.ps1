$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopDir = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopDir "Pocket Money.lnk"
$launcherPath = Join-Path $projectDir "dist\PocketMoney\PocketMoney.exe"
$iconPath = Join-Path $projectDir "assets\pocket-money.ico"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $projectDir
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = "Pocket Money"
$shortcut.Save()

Write-Host "Pocket Money desktop shortcut created." -ForegroundColor Green
