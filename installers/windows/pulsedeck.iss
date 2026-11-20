; Inno Setup 6 script for PulseDeck.
; Built by scripts/build_windows.py, which passes the defines below.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef Arch
  #define Arch "x64"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\PulseDeck"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif
#ifndef OutputBaseName
  #define OutputBaseName "PulseDeck-Setup-x64"
#endif

#define AppName "PulseDeck"
#define AppExe "PulseDeck.exe"
#define ProgId "PulseDeck.AudioFile"

[Setup]
; Keep this AppId stable forever: it is how upgrades find the existing install.
AppId={{6F1B7C2E-4A8D-4E57-9C1F-2B5D7E3A9C40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Madhu Kumar
AppPublisherURL=https://github.com/aboycan/pulse-deck
AppSupportURL=https://github.com/aboycan/pulse-deck/issues
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=INSTALLER_LICENSE.txt
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}
SetupIconFile=..\..\src\pulsedeck\assets\icons\pulsedeck.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
AppCopyright=Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
; Windows 10 or later.
MinVersion=10.0.17763
#if Arch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "assoc"; Description: "Add PulseDeck to ""Open with"" for audio files and playlists"; GroupDescription: "File associations:"
Name: "assocdefault"; Description: "Make PulseDeck the default player for audio files"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "io.github.pulsedeck.PulseDeck"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Notifications are titled "PulseDeck" instead of the raw AppUserModelID.
Root: HKA; Subkey: "Software\Classes\AppUserModelId\io.github.pulsedeck.PulseDeck"; ValueType: string; ValueName: "DisplayName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\AppUserModelId\io.github.pulsedeck.PulseDeck"; ValueType: string; ValueName: "IconUri"; ValueData: "{app}\_internal\pulsedeck\assets\icons\pulsedeck-256.png"
; ProgID describing how PulseDeck opens files.
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "Audio file (PulseDeck)"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc
; "Open with" entries (non-intrusive) for each supported type.
#define Ext(str e) 'Root: HKA; Subkey: "Software\Classes\' + e + '\OpenWithProgids"; ValueType: string; ValueName: "' + ProgId + '"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc'
#emit Ext(".mp3")
#emit Ext(".flac")
#emit Ext(".wav")
#emit Ext(".aac")
#emit Ext(".m4a")
#emit Ext(".ogg")
#emit Ext(".oga")
#emit Ext(".opus")
#emit Ext(".wma")
#emit Ext(".aif")
#emit Ext(".aiff")
#emit Ext(".m3u")
#emit Ext(".m3u8")
; Optional: become the default handler (Windows may still ask the user to confirm).
#define Def(str e) 'Root: HKA; Subkey: "Software\Classes\' + e + '"; ValueType: string; ValueName: ""; ValueData: "' + ProgId + '"; Flags: uninsdeletevalue; Tasks: assocdefault'
#emit Def(".mp3")
#emit Def(".flac")
#emit Def(".m4a")
#emit Def(".ogg")
#emit Def(".opus")

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// User settings, playlists and the library live in %APPDATA%\PulseDeck and
// %LOCALAPPDATA%\PulseDeck. They survive upgrades and normal uninstalls; the
// uninstaller only removes them if the user explicitly says so.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Roaming, Local: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Roaming := ExpandConstant('{userappdata}\PulseDeck');
    Local := ExpandConstant('{localappdata}\PulseDeck');
    if (DirExists(Roaming) or DirExists(Local)) and not UninstallSilent() then
    begin
      if MsgBox('Do you also want to delete your PulseDeck settings, playlists and library database?' + #13#10 +
                'Your music files are never touched.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(Roaming, True, True, True);
        DelTree(Local, True, True, True);
      end;
    end;
  end;
end;
