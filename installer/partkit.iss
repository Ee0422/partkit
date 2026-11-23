; Inno Setup script for PartKit. Built by .github/workflows/release.yml.
; Installs per user (no admin rights needed) into %LOCALAPPDATA%\Programs\PartKit.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0C5E7A-3F2D-4C1B-9A57-1D2E3F4A5B6C}
AppName=PartKit
AppVersion={#MyAppVersion}
AppPublisher=PartKit contributors
AppPublisherURL=https://github.com/Ee0422/partkit
DefaultDirName={autopf}\PartKit
DefaultGroupName=PartKit
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PartKit-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\PartKit.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\PartKit\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\PartKit"; Filename: "{app}\PartKit.exe"
Name: "{group}\Uninstall PartKit"; Filename: "{uninstallexe}"
Name: "{userdesktop}\PartKit"; Filename: "{app}\PartKit.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PartKit.exe"; Description: "Open PartKit now"; Flags: nowait postinstall skipifsilent
