# SkimReel for Windows

This folder builds a Windows desktop app in addition to the existing web app. It uses the same SkimReel site and analysis API. The **Import from YouTube** desktop menu runs the existing `local-helper/skimreel_helper.py` workflow, downloads public YouTube videos locally without Firefox sign-in, and uploads them to the same analyzer; it does not replace the analysis logic.

## Build the installer and portable EXE

Requirements to build: Node.js 20 or newer, Python 3.9, Deno, and the Python packages `yt-dlp`, `requests`, and `pyinstaller`. Install them for the Python 3.9 launcher with `py -3.9 -m pip install yt-dlp requests pyinstaller`. The built app includes the YouTube helper, Deno, and the official yt-dlp executable. Users do not need Firefox or a signed-in browser profile for public videos.

From this folder:

```powershell
npm install
Set-Location ..\frontend
npm.cmd run build:desktop
Set-Location ..\skimreel-desktop
.\build-windows.ps1
npm run dist:win
```

The installer and portable executable are written to `release/`. The app opens the packaged frontend in its own window and connects to the API configured in `frontend/public/config.js`. YouTube links entered in the app automatically download locally with the bundled current yt-dlp and Deno, without browser cookies; the uploaded analysis then appears in the app's results screen.

For a local development launch, build the frontend first with `npm.cmd run build:desktop` in `../frontend`, then run `npm start` here.

The YouTube menu item is also available with **Ctrl+Shift+Y**. YouTube can still restrict some videos or connections, but Firefox sign-in is not required for public videos.
