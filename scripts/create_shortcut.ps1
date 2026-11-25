$WshShell = New-Object -ComObject WScript.Shell

# 1. Shortcut directly inside C:\Users\User\Desktop\DDG
$ShortcutPath1 = "C:\Users\User\Desktop\DDG\DDG Bot Studio.lnk"
$Shortcut1 = $WshShell.CreateShortcut($ShortcutPath1)
$Shortcut1.TargetPath = "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio\run_studio.bat"
$Shortcut1.WorkingDirectory = "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio"
$Shortcut1.Description = "Launch DDG Local Bot Studio (A$0/mo Self-Hosted)"

# Icon check
$IconIco = "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio\assets\app_icon.ico"
if (Test-Path $IconIco) {
    $Shortcut1.IconLocation = "$IconIco,0"
}
$Shortcut1.Save()

# 2. Shortcut directly on Desktop
$DesktopFolder = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
$ShortcutPath2 = Join-Path $DesktopFolder "DDG Bot Studio.lnk"
$Shortcut2 = $WshShell.CreateShortcut($ShortcutPath2)
$Shortcut2.TargetPath = "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio\run_studio.bat"
$Shortcut2.WorkingDirectory = "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio"
$Shortcut2.Description = "Launch DDG Local Bot Studio (A$0/mo Self-Hosted)"
if (Test-Path $IconIco) {
    $Shortcut2.IconLocation = "$IconIco,0"
}
$Shortcut2.Save()

Write-Output "Shortcuts created successfully at $ShortcutPath1 and $ShortcutPath2"
