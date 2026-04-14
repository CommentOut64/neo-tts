#ifndef AppId
  #define AppId "com.neo-tts.desktop"
#endif

#ifndef AppName
  #define AppName "NeoTTS"
#endif

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#ifndef AppExeName
  #define AppExeName "NeoTTS.exe"
#endif

#ifndef SourceRoot
  #define SourceRoot ""
#endif

#ifndef OutputDir
  #define OutputDir "."
#endif

#ifndef OutputBaseFilename
  #define OutputBaseFilename AppName + "-Setup-" + AppVersion
#endif

#ifndef SetupIconFile
  #define SetupIconFile ""
#endif

#expr SourceRoot = AddBackslash(SourceRoot)

#if SourceRoot == ""
  #error SourceRoot define is required.
#endif

#if SetupIconFile == ""
  #error SetupIconFile define is required.
#endif

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#SetupIconFile}
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/normal
CompressionThreads=auto
LZMANumBlockThreads=2
SolidCompression=no
WizardStyle=modern
PrivilegesRequired=admin
UsePreviousAppDir=yes
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#SourceRoot}*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
