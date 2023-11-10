[Setup]
// Add the custom wizard page to the installation
//WizardImageFile=wizard.bmp
//WizardSmallImageFile=smallwiz.bmp

AppName=Matrix <> Meshtastic Relay (Lite)
AppVersion={#AppVersion}
DefaultDirName={userpf}\M2M Lite
DefaultGroupName=M2MLite
UninstallFilesDir={app}
OutputDir=.
OutputBaseFilename=M2M-Lite_setup
PrivilegesRequiredOverridesAllowed=dialog commandline

[Files]
Source: "dist\m2mlite.exe"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs; AfterInstall: AfterInstall(ExpandConstant('{app}'));

[Icons]
Name: "{group}\M2M Lite"; Filename: "{app}\m2mlite.bat"
Name: "{group}\M2M Lite Config"; Filename: "{app}\config.yaml"; IconFilename: "{sys}\notepad.exe"; WorkingDir: "{app}"; Parameters: "config.yaml";

[Run]
Filename: "{app}\m2mlite.bat"; Description: "Launch M2M Lite"; Flags: nowait postinstall

[Code]
var
  TokenInfoLabel: TLabel;
  TokenInfoLink: TNewStaticText;
  MatrixPage : TInputQueryWizardPage;
  OverwriteConfig: TInputOptionWizardPage;
  MatrixMeshtasticPage : TInputQueryWizardPage;
  MeshtasticPage : TInputQueryWizardPage;
  OptionsPage : TInputOptionWizardPage;
  Connection: string;

procedure TokenInfoLinkClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  if not ShellExec('', 'open', TNewStaticText(Sender).Caption, '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
  begin
    // handle failure if necessary
  end;
end;

procedure InitializeWizard;
begin
  OverwriteConfig := CreateInputOptionPage(wpWelcome,
    'Configure the relay', 'Create new configuration',
    '', False, False);
  MatrixPage := CreateInputQueryPage(OverwriteConfig.ID, 
      'Matrix Setup', 'Configure Matrix Settings',
      'Enter the settings for your Matrix server.');
  MeshtasticPage := CreateInputQueryPage(MatrixPage.ID, 
      'Meshtastic Setup', 'Configure Meshtastic Settings',
      'Enter the settings for connecting with your Meshtastic radio.');
  MatrixMeshtasticPage := CreateInputQueryPage(MeshtasticPage.ID, 
      'Matrix <> Meshtastic Setup', 'Configure Matrix <> Meshtastic Settings',
      'Connect a Matrix room with a Meshtastic radio channel.');
  OptionsPage := CreateInputOptionPage(MatrixMeshtasticPage.ID, 
      'Additional Options', 'Provide additional optios',
      'Set logging and broadcast options, you can keep the defaults.', False, False);
  
  OverwriteConfig.Add('Generate configuration (overwrite any current config files)');
  OverwriteConfig.Values[0] := True;

  TokenInfoLabel.Caption := 'For instructions on where to find your access token, visit:';


