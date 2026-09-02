; Inno Setup script for KumoCam.
; Build the PyInstaller folder first (pyinstaller packaging/kumocam.spec),
; then compile this script:  iscc packaging\kumocam.iss
; Output: packaging\Output\KumoCam-Setup-<version>.exe

#define MyAppName "KumoCam"
#ifndef MyAppVersion
  #define MyAppVersion "0.11.1"
#endif
#define MyAppPublisher "Marcelo Souza / Kumodot.art"
#define MyAppURL "https://github.com/kumodot/kumocam"
#define MyAppExeName "KumoCam.exe"

[Setup]
AppId={{8C1B2E9A-7F44-4C1D-9B7E-3A5C0D1E2F04}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputBaseFilename=KumoCam-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\KumoCam\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
