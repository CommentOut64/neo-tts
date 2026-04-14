import path from "node:path";
import process from "node:process";

import { BrowserWindow } from "electron";

function resolveWindowIconPath(): string {
	const packagedResourcesPath = (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath;
	if (typeof packagedResourcesPath === "string" && packagedResourcesPath.length > 0) {
		return path.join(packagedResourcesPath, "app-runtime", "frontend-dist", "512.ico");
	}

	return path.resolve(__dirname, "..", "..", "..", "frontend", "public", "512.ico");
}

export function createMainWindow(): BrowserWindow {
	const mainWindow = new BrowserWindow({
		width: 1360,
		height: 860,
		show: false,
		autoHideMenuBar: true,
		icon: resolveWindowIconPath(),
		webPreferences: {
			preload: path.join(__dirname, "..", "preload.js"),
			contextIsolation: true,
			sandbox: true,
			nodeIntegration: false,
		},
	});

	let shown = false;
	const showOnce = () => {
		if (shown) {
			return;
		}
		shown = true;
		mainWindow.show();
	};

	mainWindow.once("ready-to-show", showOnce);
	// 页面加载失败时 `ready-to-show` 可能不会触发，此时也要显示窗口避免“进程在但窗口不见”。
	mainWindow.webContents.once("did-fail-load", showOnce);

	return mainWindow;
}
