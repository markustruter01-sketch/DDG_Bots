' DDG Bot Studio - start everything hidden. Pass /nobrowser to skip opening the dashboard.
' 26 Nov 2026: one video watcher only (the server runs its own); paths found from this file's location.
Option Explicit
Dim sh, fso, root, ollamaPath, pyExe, openBrowser, i
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

openBrowser = True
For i = 0 To WScript.Arguments.Count - 1
    If LCase(WScript.Arguments(i)) = "/nobrowser" Then openBrowser = False
Next

' 1. Start Ollama (does nothing if it is already running)
sh.Environment("PROCESS")("OLLAMA_HOST") = "127.0.0.1:11434"
sh.Environment("PROCESS")("OLLAMA_KEEP_ALIVE") = "10m"
sh.Environment("PROCESS")("OLLAMA_MODELS") = "F:\DDG_Video_Studio\models\ollama"
ollamaPath = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Ollama\ollama.exe"
If fso.FileExists(ollamaPath) Then sh.Run """" & ollamaPath & """ serve", 0, False

' 2. Pick Python
pyExe = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyExe) Then pyExe = root & "\.venv\Scripts\python.exe"
If Not fso.FileExists(pyExe) Then pyExe = "pythonw"

' 3. Start the dashboard server hidden (it also watches the video inbox)
sh.CurrentDirectory = root
sh.Run """" & pyExe & """ dashboard\server.py", 0, False

' 4. Open the dashboard
If openBrowser Then
    WScript.Sleep 3000
    sh.Run "http://127.0.0.1:8765"
End If
