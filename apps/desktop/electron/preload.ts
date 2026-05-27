import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("workMemoryApp", {
  platform: process.platform,
  electron: process.versions.electron,
});
