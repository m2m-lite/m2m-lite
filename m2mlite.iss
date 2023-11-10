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

  MatrixPage.Add('Homeserver: (example: https://matrix.org)', False);
  MatrixPage.Add('Bot User ID (example: @mybotuser:matrix.org)', False);
  MatrixPage.Add('Access Token (example: syt_bWvzaGjvdD1_PwsXoZgGItImVxBIZbBK_1XZVW8)', False);

  TokenInfoLabel := TLabel.Create(WizardForm);
  TokenInfoLabel.Caption := 'For instructions on where to find your access token, visit:';
  TokenInfoLabel.Parent := MatrixPage.Surface;
  TokenInfoLabel.Left := 0;
  TokenInfoLabel.Top := MatrixPage.Edits[2].Top + MatrixPage.Edits[2].Height + 8;

  TokenInfoLink := TNewStaticText.Create(WizardForm);
  TokenInfoLink.Caption := 'https://t2bot.io/docs/access_tokens/';
  TokenInfoLink.Cursor := crHand;
  TokenInfoLink.Font.Color := clBlue;
  TokenInfoLink.Font.Style := [fsUnderline];
  TokenInfoLink.OnClick := @TokenInfoLinkClick;
  TokenInfoLink.Parent := MatrixPage.Surface;
  TokenInfoLink.Left := TokenInfoLabel.Left;
  TokenInfoLink.Top := TokenInfoLabel.Top + TokenInfoLabel.Height;


  MatrixPage.Edits[0].Hint := 'https://example.matrix.org';
  MatrixPage.Edits[1].Hint := '@botuser:example.matrix.org';
  MatrixPage.Edits[2].Hint := 'reaalllllyloooooongsecretttttcodeeeeeeforrrrbot';

  MeshtasticPage.Add('Connection Type (network or serial)?', False);
  MeshtasticPage.Add('Serial Port (if serial):', False);
  MeshtasticPage.Add('Hostname/IP (If network):', False);
  MeshtasticPage.Add('Meshnet Name:', False);
  MeshtasticPage.Edits[0].Hint := 'serial or network';
  MeshtasticPage.Edits[1].Hint := 'serial port (if serial)';
  MeshtasticPage.Edits[2].Hint := 'hostname/IP (if network)';
  MeshtasticPage.Edits[3].Hint := 'Name for radio Meshnet';


  MatrixMeshtasticPage.Add('Matrix Room ID/Alias (example: !someroomid:example.matrix.org)', False);
  MatrixMeshtasticPage.Add('Meshtastic Channel # (0 is Primary, 1-7 Secondary)', False);
  MatrixMeshtasticPage.Edits[0].Hint := '!someroomid:example.matrix.org';
  MatrixMeshtasticPage.Edits[1].Hint := '0-7 (default 0)';

  OptionsPage.Add('Debug Logging Mode');
  OptionsPage.Add('Radio broadcasts enabled');
  OptionsPage.Values[0] := False;
  OptionsPage.Values[1] := True;
end;

function BoolToStr(Value : Boolean): String;
begin
  if Value then
    result := 'true'
  else
    result := 'false';
end;

{ Skips config setup pages if needed}
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if PageID = OverwriteConfig.ID then
      Result := False
  else
      Result := Not OverwriteConfig.Values[0];
end;

procedure AfterInstall(sAppDir: string);
var
    config: string;
    connection_type: string;
    serial_port: string;
    host: string;
    log_level: string;
    batch_file: string;
begin
    If Not OverwriteConfig.Values[0] then
      Exit;

    if (FileExists(sAppDir+'/config.yaml')) then
    begin
        RenameFile(sAppDir+'/config.yaml', sAppDir+'/config-old.yaml');
    end;

    connection_type := MeshtasticPage.Values[0];
    serial_port := MeshtasticPage.Values[1];
    host := MeshtasticPage.Values[2];

    if OptionsPage.Values[0] then
    begin
        log_level := 'debug';
    end
    else
    begin
        log_level := 'info';
    end;

    config := 'matrix:' + #13#10 +
              '  homeserver: "' + MatrixPage.Values[0] + '"' +  #13#10 +
              '  bot_user_id: "' + MatrixPage.Values[1] + '"' + #13#10 +
              '  access_token: "' + MatrixPage.Values[2] + '"' + #13#10 +
              'matrix_rooms:' + #13#10 +
              '  - id: "' + MatrixMeshtasticPage.Values[0] + '"' + #13#10 +
              '    meshtastic_channel: ' + MatrixMeshtasticPage.Values[1] + #13#10 +
              'meshtastic:' + #13#10 +
              '  connection_type: "' + connection_type + '"' + #13#10 +
              '  serial_port: "' + serial_port + '"' + #13#10 +
              '  host: "' + host + '"' + #13#10 +
              '  meshnet_name: "' + MeshtasticPage.Values[3] + '"' + #13#10 +
              '  broadcast_enabled: ' + BoolToStr(OptionsPage.Values[1]) + #13#10 +
              'logging:' + #13#10 +
              '  level: "' + log_level + '"' + #13#10;

    if Not SaveStringToFile(sAppDir+'/config.yaml', config, false) then
    begin
        MsgBox('Could not create config file "config.yaml". Close any applications that may have it open and re-run setup', mbInformation, MB_OK);
    end;

    batch_file := '"' + sAppDir+ '\m2mlite.exe" config.yaml ' + #13#10 +
                  'pause';

    if Not SaveStringToFile(sAppDir+'/m2mlite.bat', batch_file, false) then
    begin
        MsgBox('Could not create batch file "m2mlite.bat". Close any applications that may have it open and re-run setup', mbInformation, MB_OK);
    end;


end;
