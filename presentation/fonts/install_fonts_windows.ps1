# Устанавливает шрифты презентации для текущего пользователя (без прав администратора).
# Запуск: правый клик → «Выполнить с помощью PowerShell» или: powershell -ExecutionPolicy Bypass -File install_fonts_windows.ps1
$dest = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Get-ChildItem -Path $PSScriptRoot -Filter *.ttf | ForEach-Object {
  Copy-Item $_.FullName -Destination $dest -Force
  New-ItemProperty -Path "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts" -Name "$($_.BaseName) (TrueType)" -Value (Join-Path $dest $_.Name) -PropertyType String -Force | Out-Null
  Write-Host "installed $($_.Name)"
}
Write-Host "Готово. Перезапустите PowerPoint."
