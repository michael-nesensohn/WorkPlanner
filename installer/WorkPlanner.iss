; Installationsprogramm für WorkPlanner (Inno Setup 6). Gebaut mit dev-build.ps1.
; Installationsort: C:\Projects\SW-Tools\<Programmname>\<Dateien>

; Die Vorgaben lassen sich beim Kompilieren überschreiben (/DName=Wert). Das nutzen nur Testläufe: So
; berührt ein Test weder die echte Installation noch deren Daten (andere ID, anderer Name, kein Prozess-Kill).
#ifndef AppName
  #define AppName "WorkPlanner"
#endif
#define AppExe "WorkPlanner.exe"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef AppGuid
  #define AppGuid "3466363E-66F1-4135-A259-4D81F081E265"
#endif
#ifndef OutDir
  #define OutDir "..\dist\installer"
#endif

[Setup]
; Feste ID: Damit erkennt ein neuerer Installer die vorhandene Installation und aktualisiert sie.
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName=C:\Projects\SW-Tools\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
; Keine Administratorrechte nötig: installiert wird in einen Ordner, der dem Benutzer gehört.
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\workplanner.ico
; MIT-Lizenz: wird im Installer angezeigt und mitinstalliert
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "startmenuicon"; Description: "Eintrag im Startmenü anlegen (mit Deinstallieren)"; GroupDescription: "Verknüpfungen:"
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; GroupDescription: "Verknüpfungen:"; Flags: unchecked
Name: "autostart"; Description: "Mit Windows starten (nur als Symbol im Tray)"; GroupDescription: "Start:"; Flags: unchecked

[InstallDelete]
; Alte Programmbibliothek vor jedem Update entfernen: sonst bleiben nicht mehr gelieferte Pakete (z. B. ein früher
; mitgepacktes numpy) liegen und werden von Python trotzdem gefunden. Die Daten liegen woanders (DATADIR).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\WorkPlanner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Handbuch (PDF): „Hilfe → Handbuch öffnen“ und Startmenü
Source: "..\docs\WorkPlanner-Handbuch.pdf"; DestDir: "{app}\Handbuch"; Flags: ignoreversion

[Icons]
; Startmenü: Ordner „WorkPlanner“ mit Programm und Deinstallation (Programme → WorkPlanner)
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startmenuicon
Name: "{group}\{#AppName} Handbuch"; Filename: "{app}\Handbuch\WorkPlanner-Handbuch.pdf"; Tasks: startmenuicon
Name: "{group}\{#AppName} deinstallieren"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Autostart nur für das eigene Konto (kein Admin nötig); „--tray“ = ohne sichtbares Fenster starten.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --tray"; Tasks: autostart; Flags: uninsdeletevalue

[UninstallDelete]
; wird vom Installer geschrieben (siehe CurStepChanged), kennt der Deinstaller deshalb nicht von selbst
Type: files; Name: "{app}\installiert.json"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} jetzt starten"; Flags: nowait postinstall skipifsilent
; Update aus dem Programm („Hilfe → Über WorkPlanner / Updates“) ruft den Installer mit /RELAUNCH=1: danach neu starten
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: RelaunchRequested

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Wie die anderen Werkzeuge in C:\Projects\SW-Tools: kleine Markierungsdatei mit Version und Zeitpunkt.
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\installiert.json'),
      '{' + #13#10 + '  "version": "{#AppVersion}",' + #13#10 +
      '  "installed": "' + GetDateTimeString('yyyy/mm/dd hh:nn', '-', ':') + '"' + #13#10 + '}', False);
end;

function RelaunchRequested(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function DataDir(): String;
begin
  // Hier liegt die Datenbank (Zeiteinträge, Projekte, Einstellungen). /DATADIR=... ist nur für Testläufe gedacht.
  Result := ExpandConstant('{param:DATADIR|}');
  if Result = '' then
    Result := ExpandConstant('{userappdata}\{#AppName}');
end;

function IsUpdate(): Boolean;
begin
  // Update = es gibt schon eine Installation (Eintrag in „Apps & Features“ oder die Programmdatei im Zielordner).
  Result := RegKeyExists(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#AppGuid}' + '}_is1')
            or FileExists(ExpandConstant('{app}\{#AppExe}'));
end;

procedure StartWithEmptyDatabase();
var
  Db, Stamp: String;
begin
  // Neuinstallation: WorkPlanner soll leer starten. Eine vorhandene Datenbank (z. B. von einer früheren
  // Installation, deren Daten beim Deinstallieren stehen blieben) wird nicht gelöscht, sondern beiseite gelegt.
  Db := DataDir() + '\workplanner.db';
  if FileExists(Db) then
  begin
    Stamp := GetDateTimeString('yyyymmdd-hhnnss', #0, #0);
    RenameFile(Db, Db + '.vorher-' + Stamp);
    if FileExists(Db + '-journal') then
      RenameFile(Db + '-journal', Db + '-journal.vorher-' + Stamp);
  end;
end;

procedure StopRunningApp();
var
  ResultCode: Integer;
begin
#ifndef TestBuild
  // Läuft WorkPlanner (z. B. im Tray), lassen sich seine Dateien nicht ersetzen/löschen.
  // Eine laufende Zeiterfassung geht dabei nicht verloren: Sie steht in der Datenbank.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#AppExe} /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
#endif
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  // Update: die vorhandene Datenbank bleibt unberührt. Neuinstallation: leere Datenbank.
  if not IsUpdate() then
    StartWithEmptyDatabase();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Autostart-Eintrag entfernen, auch wenn WorkPlanner ihn selbst (in den Stammdaten) angelegt hat.
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
    // Die Zeiteinträge bleiben standardmäßig erhalten; löschen nur auf ausdrücklichen Wunsch.
    Dir := DataDir();
    if (not UninstallSilent()) and DirExists(Dir) then
      if MsgBox('Sollen auch Ihre gespeicherten Zeiteinträge und Einstellungen gelöscht werden?' + #13#10 +
                '(' + Dir + ')' + #13#10#13#10 +
                'Mit „Nein“ bleiben sie erhalten, z. B. für eine spätere Neuinstallation.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dir, True, True, True);
  end;
end;
