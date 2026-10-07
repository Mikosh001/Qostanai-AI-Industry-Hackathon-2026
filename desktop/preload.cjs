const { contextBridge, ipcRenderer } = require("electron");
const commands = new Set([
  "info",
  "get-language",
  "set-language",
  "open-portal",
  "close-portal",
  "setup",
  "resolve-launch",
  "create",
  "snapshot",
  "calibrate",
  "enroll",
  "camera-stream",
  "probe",
  "activate",
  "start",
  "exam",
  "answer",
  "finish",
  "show-exam",
  "hide-exam",
  "open-dashboard",
]);
contextBridge.exposeInMainWorld("sergek", {
  invoke: (command, payload = {}) => {
    if (!commands.has(command))
      return Promise.reject(new Error("Unsupported desktop command"));
    return ipcRenderer.invoke("sergek:command", command, payload);
  },
  onLaunch: (listener) => {
    const callback = (_, payload) => listener(payload);
    ipcRenderer.on("sergek:launch", callback);
    return () => ipcRenderer.removeListener("sergek:launch", callback);
  },
});
