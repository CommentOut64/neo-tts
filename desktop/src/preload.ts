import { contextBridge, ipcRenderer } from "electron";

import { APP_REQUEST_EXIT_CHANNEL } from "./ipc/channels";

contextBridge.exposeInMainWorld("neoTTS", {
	runtime: "electron" as const,
	requestAppExit: () => ipcRenderer.invoke(APP_REQUEST_EXIT_CHANNEL),
});
