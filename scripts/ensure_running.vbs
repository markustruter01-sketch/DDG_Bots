' DDG Bot Studio watchdog (28 Nov 2026): runs the guardian's check, hidden.
' Run at logon (Startup folder) and every 5 minutes (Task Scheduler) by "Install Always-On.bat".
' The guardian (studio\guardian.py) starts whatever is down and restarts the AI engine if it is frozen or can't find
' Qwen. Everything it does goes to logs\watchdog.log.
Option Explicit
Dim sh, fso, root, py
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
py = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw"
sh.CurrentDirectory = root
sh.Run """" & py & """ -m studio.guardian check", 0, False
