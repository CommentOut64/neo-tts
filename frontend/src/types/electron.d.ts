export {};

declare global {
  interface Window {
    neoTTS?: {
      runtime: "electron";
      distributionKind: "installed" | "portable";
      backendOrigin: string;
      requestAppExit(): Promise<void>;
    };
  }
}
