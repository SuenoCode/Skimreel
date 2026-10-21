const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("skimreelDesktop", {
  startYoutubeImport: input => ipcRenderer.invoke("youtube-import:start", input),
  analyzeYoutubeLink: input => ipcRenderer.invoke("youtube-import:analyze", input),
  cancelYoutubeImport: () => ipcRenderer.invoke("youtube-import:cancel"),
  onYoutubeOutput: callback => {
    const listener = (_event, message) => callback(message)
    ipcRenderer.on("youtube-import:output", listener)
    return () => ipcRenderer.removeListener("youtube-import:output", listener)
  },
})
