; Inno Setup script: wraps dist\VetClinic (made by build_portable.ps1) into dist\VetClinic-Setup.exe.
; Installs per user (no admin rights needed) so the data folder stays writable.
; Reinstalling or updating replaces the program files and never touches the data folder.

#define AppName "Vet Clinic Assistant"
#define AppVersion "1.0.3"

[Setup]
AppId={{2A2470C2-F830-4459-90BA-DBDD1CF40A22}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\VetClinic
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=VetClinic-Setup
SetupIconFile=vetclinic.ico
UninstallDisplayIcon={app}\vetclinic.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Clear the old program files on update so removed modules don't linger.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "..\dist\VetClinic\*"; Excludes: "\data\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "vetclinic.ico"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Start VetClinic.bat"; WorkingDir: "{app}"; IconFilename: "{app}\vetclinic.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Start VetClinic.bat"; WorkingDir: "{app}"; IconFilename: "{app}\vetclinic.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\Start VetClinic.bat"; WorkingDir: "{app}"; Description: "Start {#AppName} now"; Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
; Python writes cache files at runtime; remove them with the program. The data folder is kept.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"
