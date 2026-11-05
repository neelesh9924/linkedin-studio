# Desktop shortcut

The app does not create shortcuts itself. Run this once in PowerShell to put
**LinkedIn Studio** on your desktop. It points at the `.vbs` launcher (no console
window) and uses `assets\studio.ico`.

```powershell
$root  = "C:\path\to\linkedin-studio"    # the folder that holds "Launch LinkedIn Studio.vbs"
$shell = New-Object -ComObject WScript.Shell
$link  = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "LinkedIn Studio.lnk"))
$link.TargetPath       = Join-Path $env:SystemRoot "System32\wscript.exe"
$link.Arguments        = "`"$root\Launch LinkedIn Studio.vbs`""
$link.WorkingDirectory = $root
$link.IconLocation     = "$root\assets\studio.ico,0"
$link.Description      = "LinkedIn Studio"
$link.Save()
```

`GetFolderPath("Desktop")` follows OneDrive desktop redirection, so the shortcut
lands on the desktop you actually see.

For the Start menu too, run the same snippet with the first argument of
`Join-Path` changed to `([Environment]::GetFolderPath("Programs"))`.

To remove it, delete `LinkedIn Studio.lnk` from the desktop.
