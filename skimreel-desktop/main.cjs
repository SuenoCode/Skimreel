const { app, BrowserWindow, Menu, ipcMain, shell, session } = require("electron")
const path = require("node:path")
const { spawn } = require("node:child_process")
const fs = require("node:fs")

let mainWindow
let importWindow
let helperProcess

function frontendPath(file) {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, "frontend")
    : path.resolve(__dirname, "../frontend/dist")
  return path.join(base, file)
}

function helperPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "helper", "SkimReelYouTube.exe")
    : path.resolve(__dirname, "build/helper/SkimReelYouTube.exe")
}

function toolPath(file) {
  return app.isPackaged
    ? path.join(process.resourcesPath, "tools", file)
    : path.resolve(__dirname, "build/tools", file)
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 960,
    minHeight: 680,
    backgroundColor: "#181b1c",
    title: "SkimReel",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  // Load the packaged app code so the desktop-only local YouTube import path is
  // always active. Its runtime config still points at the existing API.
  mainWindow.loadFile(frontendPath("index.html"))
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://") || url.startsWith("http://")) shell.openExternal(url)
    return { action: "deny" }
  })
}

function openYoutubeImport() {
  if (importWindow && !importWindow.isDestroyed()) return importWindow.focus()
  importWindow = new BrowserWindow({
    width: 520,
    height: 640,
    resizable: false,
    parent: mainWindow,
    modal: true,
    title: "Import from YouTube · SkimReel",
    backgroundColor: "#181b1c",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  importWindow.loadFile(path.join(__dirname, "youtube-import.html"))
  importWindow.on("closed", () => { importWindow = null })
}

function buildMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: "SkimReel", submenu: [
      { label: "Home", click: () => mainWindow?.focus() },
      { label: "Import from YouTube…", accelerator: "Ctrl+Shift+Y", click: openYoutubeImport },
      { type: "separator" },
      { role: "quit" },
    ] },
    { label: "View", submenu: [ { role: "reload" }, { role: "togglefullscreen" }, { role: "toggledevtools" } ] },
  ]))
}

function youtubeInput(input) {
  const url = String(input.url || "").trim()
  let parsed
  try { parsed = new URL(/^https?:\/\//i.test(url) ? url : `https://${url}`) }
  catch { throw new Error("Enter a valid YouTube URL.") }
  if (!["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"].includes(parsed.hostname)) {
    throw new Error("Enter a YouTube video URL.")
  }
  return parsed.href
}

function launchYoutubeHelper(event, input, desktopHandoff) {
  if (helperProcess) throw new Error("A YouTube import is already running.")
  const url = youtubeInput(input)
  const helper = helperPath()
  const args = [url, "--length", String(input.length), "--count", String(input.count), "--quality", String(input.quality),
    "--yt-dlp-executable", toolPath("yt-dlp.exe"), "--deno-path", toolPath("deno.exe")]
  if (desktopHandoff) args.push("--desktop-handoff")
  const denoDir = app.isPackaged ? path.join(process.resourcesPath, "tools") : path.resolve(__dirname, "build/tools")
  helperProcess = spawn(helper, args, { windowsHide: true, env: { ...process.env, PYTHONUNBUFFERED: "1", PATH: `${denoDir}${path.delimiter}${process.env.PATH || ""}` } })
  const send = (type, text) => {
    if (!event.sender.isDestroyed()) event.sender.send("youtube-import:output", { type, text })
  }
  return new Promise((resolve, reject) => {
    let settled = false
    let stdoutBuffer = ""
    let errorOutput = ""
    const finish = (error, result) => {
      if (settled) return
      settled = true
      if (error) reject(error)
      else resolve(result)
    }
    helperProcess.stdout.setEncoding("utf8")
    helperProcess.stderr.setEncoding("utf8")
    helperProcess.stdout.on("data", text => {
      send("info", text)
      if (!desktopHandoff) return
      stdoutBuffer += text
      const match = stdoutBuffer.match(/DESKTOP_JOB_ID:([A-Za-z0-9_-]+)/)
      if (match) finish(null, { job: match[1] })
      if (stdoutBuffer.length > 4096) stdoutBuffer = stdoutBuffer.slice(-1024)
    })
    helperProcess.stderr.on("data", text => { errorOutput += text; send("error", text) })
    helperProcess.on("error", error => {
      send("error", `Could not start the bundled YouTube helper: ${error.message}`)
      finish(error)
    })
    helperProcess.on("close", code => {
      send(code === 0 ? "success" : "error", code === 0 ? "YouTube import finished." : `Import ended with code ${code}.`)
      helperProcess = null
      if (desktopHandoff && !settled) {
        finish(new Error(errorOutput.trim() || `Local YouTube import ended with code ${code} before the analysis job started.`))
      }
    })
  })
}

app.whenReady().then(() => {
  // The packaged renderer uses the file origin. Allow its requests to the
  // configured API through CORS without weakening web security for other hosts.
  const runtimeConfig = fs.readFileSync(frontendPath("config.js"), "utf8")
  const apiBase = runtimeConfig.match(/apiBase\s*:\s*["']([^"']*)["']/)?.[1] || ""
  const apiOrigin = apiBase.replace(/\/$/, "")
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    let isApiRequest = false
    try { isApiRequest = !!apiOrigin && new URL(details.url).origin === apiOrigin }
    catch { /* non-HTTP resources do not need CORS handling */ }
    if (isApiRequest) {
      const headers = details.responseHeaders || {}
      for (const key of Object.keys(headers)) {
        if (key.toLowerCase().startsWith("access-control-allow-")) delete headers[key]
      }
      headers["Access-Control-Allow-Origin"] = ["*"]
      headers["Access-Control-Allow-Methods"] = ["GET,POST,DELETE,OPTIONS"]
      headers["Access-Control-Allow-Headers"] = ["*"]
      callback({ responseHeaders: headers })
      return
    }
    callback({ responseHeaders: details.responseHeaders })
  })
  buildMenu()
  createMainWindow()
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createMainWindow() })
})

ipcMain.handle("youtube-import:start", async (event, input) => {
  launchYoutubeHelper(event, input, false).catch(() => {})
  return { started: true }
})

ipcMain.handle("youtube-import:analyze", (event, input) => launchYoutubeHelper(event, input, true))

ipcMain.handle("youtube-import:cancel", () => {
  if (helperProcess) helperProcess.kill()
})

app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit() })
