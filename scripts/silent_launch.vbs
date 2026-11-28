' DDG Bot Studio - start everything hidden (28 Nov 2026: the guardian does the work). /nobrowser skips the dashboard.
Option Explicit
Dim sh, fso, root, py, args, i
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
py = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw"
args = " --browser"
For i = 0 To WScript.Arguments.Count - 1
    If LCase(WScript.Arguments(i)) = "/nobrowser" Then args = ""
Next
sh.CurrentDirectory = root
sh.Run """" & py & """ -m studio.guardian start" & args, 0, False
