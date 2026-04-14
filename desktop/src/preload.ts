import { contextBridge, ipcRenderer } from "electron";

import type { ElectronRuntimeInfo } from "./ipc/runtimeInfo";
import { APP_GET_RUNTIME_INFO_CHANNEL, APP_REQUEST_EXIT_CHANNEL } from "./ipc/channels";

const runtimeInfo = ipcRenderer.sendSync(APP_GET_RUNTIME_INFO_CHANNEL) as ElectronRuntimeInfo;

contextBridge.exposeInMainWorld("neoTTS", {
	...runtimeInfo,
	requestAppExit: () => ipcRenderer.invoke(APP_REQUEST_EXIT_CHANNEL),
});
