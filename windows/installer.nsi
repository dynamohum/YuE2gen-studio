; YuE2 Studio for Windows: a small installer.  It carries our own files, shows the
; terms, and runs setup.ps1, which checks the PC and fetches the rest from each
; part's publisher.  Per user, into %LOCALAPPDATA%, so no administrator prompt.
;
; Built by windows/build.sh:  makensis /DVERSION=x.y.z /DSTAGE=<staged files> installer.nsi

Unicode true
!include "MUI2.nsh"
!include "Sections.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!ifndef VERSION
  !error "VERSION is not defined"
!endif
!ifndef STAGE
  !error "STAGE is not defined"
!endif
!ifndef OUTFILE
  !define OUTFILE "YuE2Studio-Setup-${VERSION}.exe"
!endif

!ifndef SETUP_ARGS
  !define SETUP_ARGS ""   ; a test build passes -SkipModels
!endif

!define APPNAME "YuE2 Studio"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\YuE2Studio"

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\YuE2Studio"   ; where per-user programs go (VS Code, Discord)
InstallDirRegKey HKCU "Software\YuE2Studio" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${APPNAME} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${APPNAME} installer"
VIAddVersionKey "LegalCopyright" "Apache License 2.0"

!define MUI_ICON "${STAGE}\yue2studio.ico"
!define MUI_UNICON "${STAGE}\yue2studio.ico"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Install ${APPNAME}"
!define MUI_WELCOMEPAGE_TEXT "${APPNAME} writes and covers songs with the YuE2 music model, on this PC.$\r$\n$\r$\nThis installer is small. It checks that this PC can run YuE2 (an NVIDIA RTX 30-series card or newer), then downloads the rest from each part's publisher: about 22 GB, most of it the models. A download that breaks off carries on where it stopped when you run the installer again.$\r$\n$\r$\nYou need about 40 GB of free space."
!insertmacro MUI_PAGE_WELCOME
!define MUI_LICENSEPAGE_TEXT_TOP "Each part is used under its own terms."
!insertmacro MUI_PAGE_LICENSE "${STAGE}\terms.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME} now"
!define MUI_FINISHPAGE_RUN_FUNCTION StartNow
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var PowerShell

Function .onInit
  ${DisableX64FSRedirection}
  StrCpy $PowerShell "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
FunctionEnd

Function un.onInit
  ${DisableX64FSRedirection}
  StrCpy $PowerShell "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
FunctionEnd

Function StartNow
  ExecShell "" "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
FunctionEnd

Section "${APPNAME}" SecCore
  SectionIn RO
  ; What setup.ps1 will put on disk, so the page shows the real figure: the engine,
  ; the app and the models other than Gemma.
  AddSize 15000000
  SetOutPath "$INSTDIR"
  ; A running copy holds its files open.  Only its own programs are stopped, never
  ; this installer, which may be running from the same folder.
  nsExec::Exec '"$PowerShell" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -like $\'$INSTDIR\*$\' -and $$_.Name -in $\'python.exe$\',$\'pythonw.exe$\',$\'ffmpeg.exe$\',$\'ffprobe.exe$\' } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force }"'
  Pop $0
  RMDir /r "$INSTDIR\studio"
  File /r "${STAGE}\studio"
  File "${STAGE}\setup.ps1"
  File "${STAGE}\launcher.py"
  File "${STAGE}\yue2studio.ico"
  File "${STAGE}\LICENSE"
  File "${STAGE}\THIRD_PARTY_NOTICES.md"
  File "${STAGE}\terms.txt"
  WriteRegStr HKCU "Software\YuE2Studio" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "Publisher" "YuE2 Studio"
  WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "$INSTDIR\yue2studio.ico"
  WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${REGKEY}" "URLInfoAbout" "https://github.com/dynamohum/YuE2gen-studio"
  WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${REGKEY}" "EstimatedSize" 36000000
SectionEnd

Section "Lyric drafts (Gemma 4)" SecLyrics
  AddSize 7900000
  ; No files: setup.ps1 is told whether to fetch Gemma.  Without it, lyric drafts and
  ; song analysis need an external LLM, set in Settings.
SectionEnd

Section "-Setup"
  ${If} ${SectionIsSelected} ${SecLyrics}
    StrCpy $1 ""
  ${Else}
    StrCpy $1 "-NoLyrics"
  ${EndIf}
  DetailPrint "Setting up: a window shows the progress. This takes a while."
  ExecWait '"$PowerShell" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\setup.ps1" -InstallDir "$INSTDIR" $1 ${SETUP_ARGS}' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Setup did not finish.$\r$\n$\r$\nThe details are in $INSTDIR\logs\install.log. Run this installer again to carry on from where it stopped." /SD IDOK
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\venv\Scripts\python.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\yue2studio.ico"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Repair ${APPNAME}.lnk" "$PowerShell" '-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\setup.ps1" -InstallDir "$INSTDIR"' "$INSTDIR\yue2studio.ico"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\venv\Scripts\python.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\yue2studio.ico"
SectionEnd

LangString DESC_Core ${LANG_ENGLISH} "The app, the engine (ComfyUI), and the YuE2 models."
LangString DESC_Lyrics ${LANG_ENGLISH} "Gemma 4, for lyric drafts and song analysis on this PC. Leave it out if you intend to configure an external LLM. This will save 8 GB."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} $(DESC_Core)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecLyrics} $(DESC_Lyrics)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  nsExec::Exec '"$PowerShell" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -like $\'$INSTDIR\*$\' -and $$_.Name -in $\'python.exe$\',$\'pythonw.exe$\',$\'ffmpeg.exe$\',$\'ffprobe.exe$\' } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force }"'
  Pop $0
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "Software\YuE2Studio"

  MessageBox MB_YESNO|MB_ICONQUESTION "Keep your library (songs, takes and corpora) and the downloaded models (about 18 GB), so installing again does not download them again?" /SD IDYES IDYES keep
    RMDir /r "$INSTDIR"
    Goto done
  keep:
    ; The models go where setup.ps1 looks for them on a reinstall.
    Rename "$INSTDIR\engine\ComfyUI\models" "$INSTDIR\models-kept"
    RMDir /r "$INSTDIR\engine"
    RMDir /r "$INSTDIR\venv"
    RMDir /r "$INSTDIR\python"
    RMDir /r "$INSTDIR\tools"
    RMDir /r "$INSTDIR\downloads"
    RMDir /r "$INSTDIR\studio"
    RMDir /r "$INSTDIR\state"
    Delete "$INSTDIR\setup.ps1"
    Delete "$INSTDIR\launcher.py"
    Delete "$INSTDIR\terms.txt"
    Delete "$INSTDIR\LICENSE"
    Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
    Delete "$INSTDIR\yue2studio.ico"
    RMDir /r "$INSTDIR\logs"
    Delete "$INSTDIR\Uninstall.exe"
  done:
SectionEnd
