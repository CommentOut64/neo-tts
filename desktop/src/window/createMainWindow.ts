import path from "node:path";

import { BrowserWindow } from "electron";

export function createMainWindow(): BrowserWindow {
	const mainWindow = new BrowserWindow({
		width: 1360,
		height: 860,
		show: false,
		autoHideMenuBar: true,
		webPreferences: {
			preload: path.join(__dirname, "..", "preload.js"),
			contextIsolation: true,
			sandbox: true,
			nodeIntegration: false,
		},
	});

	mainWindow.once("ready-to-show", () => {
		mainWindow.show();
	});

	return mainWindow;
}
