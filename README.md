# DDG Local Bot Studio (A$0/Month Self-Hosted Video & Bot Suite)

Completely standalone and **100% isolated** from all live DDG GitHub repositories (`Doomsday Daycare`, `DDG_GodsEyeView`, `LOADMWorkflow`, `quant-terminal`, `DDG-Hypest`, `ddg-control`, `cattle-dog-coffee`).

## Quickstart (5 Minutes)
1. **Install local free AI + Python accelerators (one-time):**
   ```powershell
   powershell -ExecutionPolicy Bypass -File "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio\scripts\setup_local_env.ps1"
   ```
2. **Copy your supplied official brand media into `assets\`:**
   - `DDG Intro 15s (Share).mp4`
   - `DDG Reel Outro 3s (1080x1920).mp4`
   - `DDG Site Loader 5s (1920x1080).webm`
   - `freya_avatar_white.png` *(already faces left — never flip)*
   - *(Already copied cleanly: `DDG_Logo_New.png` & `Threads_of_Empire_Cover_1_Percent_v01.png`)*
3. **Launch Dashboard + Inbox Watcher:**
   Run `scripts\run_studio.bat`, then open `http://127.0.0.1:8765` in your browser.
4. **Daily Workflow:**
   - Drop raw Streamlabs 1080p60 recordings into **`F:\DDG_Video_Studio\01_Raw_Inbox\`**.
   - Studio automatically pauses whenever `UnrealEditor.exe` or `Streamlabs Desktop.exe` is running.
   - Review the fast low-res preview, `G0–G11` preflight gates, before/after blur strips, and draft YT/X/IG copy at `http://127.0.0.1:8765`.
   - Click **Approve Export** (blocked automatically if ANY preflight gate failed!).

## Run Tests Anytime
```powershell
python -m unittest discover -s "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio\tests" -v
```
