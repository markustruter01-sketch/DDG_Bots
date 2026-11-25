Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' 1. Gracefully terminate any old zombie instances to avoid port conflicts
On Error Resume Next
WshShell.Run "taskkill /F /FI ""WINDOWTITLE eq DDG Night Glass Server*""", 0, True
WshShell.Run "taskkill /F /FI ""WINDOWTITLE eq DDG Video Watcher*""", 0, True
On Error Goto 0

' 2. Start Ollama silently if not already running
WshShell.Environment("PROCESS")("OLLAMA_HOST") = "127.0.0.1:11434"
WshShell.Environment("PROCESS")("OLLAMA_KEEP_ALIVE") = "10m"
WshShell.Environment("PROCESS")("OLLAMA_MODELS") = "F:\DDG_Video_Studio\models\ollama"

Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")
Dim localAppData
localAppData = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
Dim ollamaPath
ollamaPath = localAppData & "\Programs\Ollama\ollama.exe"

If fso.FileExists(ollamaPath) Then
    WshShell.Run """" & ollamaPath & """ serve", 0, False
End If

' 3. Detect Python executable
Dim studioRoot
studioRoot = "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio"
Dim pyExe
pyExe = studioRoot & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyExe) Then
    pyExe = studioRoot & "\.venv\Scripts\python.exe"
    If Not fso.FileExists(pyExe) Then
        pyExe = "C:\Python313\pythonw.exe"
        If Not fso.FileExists(pyExe) Then
            pyExe = "pythonw"
        End If
    End If
End If

' 4. Launch Dashboard Server & Watcher in 100% SILENT BACKGROUND (window style 0 = Hidden)
WshShell.CurrentDirectory = studioRoot
WshShell.Run """" & pyExe & """ dashboard\server.py", 0, False
WshShell.Run """" & pyExe & """ -m studio.pipeline watch", 0, False

' 5. Wait 3 seconds for server to bind port, then open browser
WScript.Sleep 3000
WshShell.Run "http://127.0.0.1:8765"
