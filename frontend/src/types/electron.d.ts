export {};

declare global {
  interface Window {
    neoTTS?: {
      runtime: "electron";
      requestAppExit(): Promise<void>;
    };
  }
}
