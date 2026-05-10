; Inno Setup script for Slide Text Replacer
; Requires: Inno Setup 6+

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppName=Slide Text Replacer
AppVersion={#AppVersion}
AppPublisher=
DefaultDirName={autopf}\SlideTextReplacer
DefaultGroupName=Slide Text Replacer
UninstallDisplayIcon={app}\slide_text_replacer.exe
OutputDir=output
OutputBaseFilename=Setup_SlideTextReplacer_v{#AppVersion}
SetupIconFile=..\icon.ico
WizardImageFile=assets\banner.bmp
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Files]
; Entire PyInstaller onedir output
Source: "dist\slide_text_replacer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
; Desktop shortcut
Name: "{autodesktop}\Slide Text Replacer"; Filename: "{app}\slide_text_replacer.exe"; IconFilename: "{app}\slide_text_replacer.exe"
; Start menu group
Name: "{group}\Slide Text Replacer"; Filename: "{app}\slide_text_replacer.exe"
Name: "{group}\Uninstall Slide Text Replacer"; Filename: "{uninstallexe}"

[Registry]
; Add "Convert with Slide Text Replacer" to .pptx right-click context menu
; Uses a shell verb so it does NOT replace PowerPoint as default handler
Root: HKCR; Subkey: "SystemFileAssociations\.pptx\shell\SlideTextReplacer"; ValueType: string; ValueName: ""; ValueData: "Convert with Slide Text Replacer"; Flags: uninsdeletekey
Root: HKCR; Subkey: "SystemFileAssociations\.pptx\shell\SlideTextReplacer"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\slide_text_replacer.exe"",0"
Root: HKCR; Subkey: "SystemFileAssociations\.pptx\shell\SlideTextReplacer\command"; ValueType: string; ValueName: ""; ValueData: """{app}\slide_text_replacer.exe"" ""%1"""

[UninstallDelete]
; Clean up logs directory created at runtime
Type: filesandordirs; Name: "{app}\logs"
