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

#ifndef ReleaseId
  #define ReleaseId "v0.0.0"
#endif

#ifndef BootstrapVersion
  #define BootstrapVersion "0.0.0"
#endif

#ifndef UpdateAgentVersion
  #define UpdateAgentVersion "0.0.0"
#endif

#ifndef RuntimeVersion
  #define RuntimeVersion "runtime-v0"
#endif

#ifndef ModelsVersion
  #define ModelsVersion "models-v0"
#endif

#ifndef PretrainedModelsVersion
  #define PretrainedModelsVersion "pretrained-models-v0"
#endif

#ifndef StateRoot
  #define StateRoot "state"
#endif

#ifndef PackagesRoot
  #define PackagesRoot "packages"
#endif

#ifndef CurrentStateRelativePath
  #define CurrentStateRelativePath StateRoot + "\\current.json"
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
DefaultDirName={localappdata}\Programs\{#AppName}
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
PrivilegesRequired=lowest
UsePreviousAppDir=yes
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Dirs]
Name: "{app}\{#StateRoot}"

[Files]
Source: "{#SourceRoot}*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function JsonEscape(const Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

function BuildCurrentStateJson(): String;
begin
  Result :=
    '{'#13#10 +
    '  "schemaVersion": 1,'#13#10 +
    '  "distributionKind": "installed",'#13#10 +
    '  "channel": "stable",'#13#10 +
    '  "releaseId": "{#ReleaseId}",'#13#10 +
    '  "packages": {'#13#10 +
    '    "bootstrap": {'#13#10 +
    '      "version": "{#BootstrapVersion}",'#13#10 +
    '      "root": "' + JsonEscape(ExpandConstant('{app}\{#PackagesRoot}\bootstrap\{#BootstrapVersion}')) + '"'#13#10 +
    '    },'#13#10 +
    '    "update-agent": {'#13#10 +
    '      "version": "{#UpdateAgentVersion}",'#13#10 +
    '      "root": "' + JsonEscape(ExpandConstant('{app}\{#PackagesRoot}\update-agent\{#UpdateAgentVersion}')) + '"'#13#10 +
    '    },'#13#10 +
    '    "shell": {'#13#10 +
    '      "version": "{#ReleaseId}",'#13#10 +
    '      "root": "' + JsonEscape(ExpandConstant('{app}\{#PackagesRoot}\shell\{#ReleaseId}')) + '"'#13#10 +
    '    },'#13#10 +
    '    "app-core": {'#13#10 +
    '      "version": "{#ReleaseId}",'#13#10 +
    '      "root": "' + JsonEscape(ExpandConstant('{app}\{#PackagesRoot}\app-core\{#ReleaseId}')) + '"'#13#10 +
    '    },'#13#10 +
    '    "runtime": {'#13#10 +
    '      "version": "{#RuntimeVersion}",'#13#10 +
    '      "root": "' + JsonEscape(ExpandConstant('{app}\{#PackagesRoot}\runtime\{#RuntimeVersion}')) + '"'#13#10 +
    '    },'#13#10 +
    '    "models": {'#13#10 +
    '      "version": "{#ModelsVersion}",'#13#10 +
    '      "root": "' + JsonEscape(ExpandConstant('{app}\{#PackagesRoot}\models\{#ModelsVersion}')) + '"'#13#10 +
    '    },'#13#10 +
    '    "pretrained-models": {'#13#10 +
    '      "version": "{#PretrainedModelsVersion}",'#13#10 +
    '      "root": "' + JsonEscape(ExpandConstant('{app}\{#PackagesRoot}\pretrained-models\{#PretrainedModelsVersion}')) + '"'#13#10 +
    '    }'#13#10 +
    '  },'#13#10 +
    '  "paths": {'#13#10 +
    '    "userDataRoot": "' + JsonEscape(ExpandConstant('{localappdata}\NeoTTS')) + '",'#13#10 +
    '    "exportsRoot": "' + JsonEscape(ExpandConstant('{userdocs}\NeoTTS\Exports')) + '"'#13#10 +
    '  }'#13#10 +
    '}'#13#10;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    SaveStringToFile(ExpandConstant('{app}\{#CurrentStateRelativePath}'), BuildCurrentStateJson(), False);
  end;
end;
