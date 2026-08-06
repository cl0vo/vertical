#define MyAppName "ARARA Factory"
#define MyAppVersion "0.11.1"
#define MyAppPublisher "ARARA"
#define MyAppExeName "ARARA-Factory.exe"

[Setup]
AppId={{F13BF67D-816D-45EA-8C72-75FA431AFA7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ARARA Factory
DefaultGroupName=ARARA Factory
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer-output
OutputBaseFilename=ARARA-Factory-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName=ARARA Factory
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce
Name: "desktopbatch"; Description: "Создать ярлык часовой записи"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
Source: "..\dist\ARARA-Factory\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ARARA Factory"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\ARARA Factory — часовая запись"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--batch"
Name: "{autodesktop}\ARARA Factory"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autodesktop}\ARARA Factory — часовая запись"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--batch"; Tasks: desktopbatch

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить ARARA Factory"; Flags: nowait postinstall
