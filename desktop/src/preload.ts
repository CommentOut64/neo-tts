import { contextBridge, ipcRenderer, webUtils } from "electron";

import type { ElectronRuntimeInfo } from "./ipc/runtimeInfo";
import {
	APP_GET_RUNTIME_INFO_CHANNEL,
	APP_OPEN_EXTERNAL_URL_CHANNEL,
	APP_REQUEST_EXIT_CHANNEL,
} from "./ipc/channels";

const runtimeInfo = ipcRenderer.sendSync(APP_GET_RUNTIME_INFO_CHANNEL) as ElectronRuntimeInfo;

contextBridge.exposeInMainWorld("neoTTS", {
	...runtimeInfo,
	requestAppExit: () => ipcRenderer.invoke(APP_REQUEST_EXIT_CHANNEL),
	openExternalUrl: (url: string) => ipcRenderer.invoke(APP_OPEN_EXTERNAL_URL_CHANNEL, url),
	getPathForFile: (file: File) => {
		try {
			const resolvedPath = webUtils.getPathForFile(file);
			return typeof resolvedPath === "string" && resolvedPath.length > 0 ? resolvedPath : null;
		} catch {
			return null;
		}
	},
});
