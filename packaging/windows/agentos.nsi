; AgentOS Windows installer — NSIS (MUI2 wizard).
; Built by packaging/build-windows-installer.sh:
;   makensis -DVERSION=<ver> -DWHEEL=<path-to-wheel> -DOUTDIR=<dist> agentos.nsi
;
; Wizard pages: Welcome → Licence → Components → Directory → Install → Finish.
; Per-user install (no UAC): files in $LOCALAPPDATA\AgentOS, shortcuts and the
; run-at-login entry in HKCU. The install step runs bootstrap.ps1, which finds
; or installs Python and builds the private venv — the installer prompts for
; what the system doesn't have, it never assumes.

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"

Name "AgentOS ${VERSION}"
OutFile "${OUTDIR}\AgentOS-Setup-${VERSION}-windows-x64.exe"
Unicode True
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\AgentOS"
InstallDirRegKey HKCU "Software\AgentOS" "InstallDir"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "AgentOS ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "AgentOS is your machine, with a brain — a local-first AI desktop.$\r$\n$\r$\nThis wizard decides where AgentOS goes and how it starts. If Python isn't on this PC, the installer sets it up for you. Product setup (your agent's name, model, autonomy) happens on first launch, inside AgentOS.$\r$\n$\r$\nClick Next to continue."
!define MUI_FINISHPAGE_RUN "wscript.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS '"$INSTDIR\agentos-app.vbs"'
!define MUI_FINISHPAGE_RUN_TEXT "Open AgentOS now"
!define MUI_FINISHPAGE_TEXT "AgentOS is installed.$\r$\n$\r$\nFirst launch opens the setup wizard (agent name, model provider, autonomy). The command line is available as:$\r$\n  $INSTDIR\agentos.cmd"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var OllamaFlag

Section "AgentOS core (required)" SecCore
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "${WHEEL}"
  File "bootstrap.ps1"
  DetailPrint "Setting up Python + environment (this can take a few minutes)…"
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\bootstrap.ps1" -InstallDir "$INSTDIR" $OllamaFlag'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONEXCLAMATION "The Python setup step reported a problem (code $0).$\r$\nYou can re-run it later:$\r$\npowershell -ExecutionPolicy Bypass -File $\"$INSTDIR\bootstrap.ps1$\" -InstallDir $\"$INSTDIR$\""
  ${EndIf}
  WriteRegStr HKCU "Software\AgentOS" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentOS" "DisplayName" "AgentOS"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentOS" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentOS" "Publisher" "AgentOS"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentOS" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentOS" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentOS" "NoRepair" 1
SectionEnd

Section "Start Menu shortcuts" SecStartMenu
  CreateDirectory "$SMPROGRAMS\AgentOS"
  CreateShortcut "$SMPROGRAMS\AgentOS\AgentOS.lnk" "wscript.exe" '"$INSTDIR\agentos-app.vbs"' "" "" SW_SHOWNORMAL "" "Open the AgentOS desktop"
  CreateShortcut "$SMPROGRAMS\AgentOS\AgentOS Terminal.lnk" "cmd.exe" '/k "$INSTDIR\agentos.cmd" --help' "" "" SW_SHOWNORMAL "" "AgentOS command line"
  CreateShortcut "$SMPROGRAMS\AgentOS\Uninstall AgentOS.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\AgentOS.lnk" "wscript.exe" '"$INSTDIR\agentos-app.vbs"' "" "" SW_SHOWNORMAL "" "Open the AgentOS desktop"
SectionEnd

Section "Start the AgentOS server at login" SecLogin
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AgentOSServer" 'wscript.exe "$INSTDIR\agentos-server.vbs"'
SectionEnd

Section "Ollama — run AI models locally" SecOllama
  ; The flag is read by bootstrap.ps1 (SecCore runs after .onSelChange fills it).
SectionEnd

Function .onInit
  StrCpy $OllamaFlag "-InstallOllama"   ; SecOllama defaults to selected
FunctionEnd

Function .onSelChange
  ${If} ${SectionIsSelected} ${SecOllama}
    StrCpy $OllamaFlag "-InstallOllama"
  ${Else}
    StrCpy $OllamaFlag ""
  ${EndIf}
FunctionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "The AgentOS application: a private Python environment in the install folder. Finds or installs Python 3.10+ automatically."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "AgentOS in the Start Menu."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "A shortcut on the Desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecLogin} "Start the AgentOS server in the background when you sign in, so the desktop is instantly available."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecOllama} "Install Ollama (via winget) to run AI models locally. Skip if you'll use cloud API keys."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AgentOSServer"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentOS"
  DeleteRegKey HKCU "Software\AgentOS"
  Delete "$SMPROGRAMS\AgentOS\*.lnk"
  RMDir "$SMPROGRAMS\AgentOS"
  Delete "$DESKTOP\AgentOS.lnk"
  RMDir /r "$INSTDIR"
  ; ~/.agentos (config, database, memory) is deliberately kept — it's the
  ; user's data. Deleting AgentOS should not delete what it learned.
SectionEnd
