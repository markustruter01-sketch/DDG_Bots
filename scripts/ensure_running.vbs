' DDG Bot Studio watchdog: if the studio does not answer, start it (hidden, no browser).
' Run at logon (Startup folder) and every 5 minutes (Task Scheduler) by "Install Always-On.bat".
Option Explicit
Dim sh, fso, root, http, ok, logFile
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

ok = False
On Error Resume Next
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
http.setTimeouts 2000, 2000, 4000, 4000
http.Open "GET", "http://127.0.0.1:8765/api/health", False
http.Send
If Err.Number = 0 Then
    If http.Status = 200 Then ok = True
End If
Err.Clear
On Error GoTo 0

' The crypto paper bot writes data\crypto\state.json every few seconds. If it is older than 3 minutes, start it again
' (a second copy cannot start while the first is still running).
Dim st, pyExe
If ok Then
    st = root & "\data\crypto\state.json"
    If (Not fso.FileExists(st)) Or (DateDiff("s", fso.GetFile(st).DateLastModified, Now) > 180) Then
        pyExe = root & "\.venv\Scripts\pythonw.exe"
        If Not fso.FileExists(pyExe) Then pyExe = "pythonw"
        If Not fso.FolderExists(root & "\logs") Then fso.CreateFolder(root & "\logs")
        Set logFile = fso.OpenTextFile(root & "\logs\watchdog.log", 8, True)
        logFile.WriteLine Now & "  crypto paper bot not updating - starting it"
        logFile.Close
        sh.CurrentDirectory = root
        sh.Run """" & pyExe & """ -m crypto_paper.runner", 0, False
    End If
End If

If Not ok Then
    If Not fso.FolderExists(root & "\logs") Then fso.CreateFolder(root & "\logs")
    Set logFile = fso.OpenTextFile(root & "\logs\watchdog.log", 8, True)
    logFile.WriteLine Now & "  studio not answering - starting it"
    logFile.Close
    sh.Run "wscript.exe """ & root & "\scripts\silent_launch.vbs"" /nobrowser", 0, False
End If
