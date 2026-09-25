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

; A test build (setup given -SkipModels or -CheckOnly) has its own name, shortcuts and
; uninstall entry, so trying it out on a PC with YuE2 Studio installed leaves that alone.
!ifdef SETUP_ARGS
  !define APPNAME "YuE2 Studio (test)"
  !define REGNAME "YuE2StudioTest"
!else
  !define SETUP_ARGS ""
  !define APPNAME "YuE2 Studio"
  !define REGNAME "YuE2Studio"
!endif
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${REGNAME}"

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${REGNAME}"   ; where per-user programs go (VS Code, Discord)
InstallDirRegKey HKCU "Software\${REGNAME}" "InstallDir"
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
; The logo on the Welcome and Finish pages, in place of NSIS's own picture (164 x 314).
!define MUI_WELCOMEFINISHPAGE_BITMAP "${STAGE}\installer-panel.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${STAGE}\installer-panel.bmp"
!define MUI_ABORTWARNING

;  An install already on this PC is updated in place: the pages say so, the folder
; page is skipped, and the Gemma choice made last time is kept (see .onInit).
Var Updating        ; 1 when this installer is updating an install already here
Var OldVersion
Var WelcomeTitle
Var WelcomeText
Var InstHeader
Var InstSubtext
Var FinishText
Var LyricsText      ; the Gemma option's description, which says when it is already here

!define MUI_WELCOMEPAGE_TITLE "$WelcomeTitle"
!define MUI_WELCOMEPAGE_TEXT "$WelcomeText"
!insertmacro MUI_PAGE_WELCOME
!define MUI_LICENSEPAGE_TEXT_TOP "Each part is used under its own terms."
!insertmacro MUI_PAGE_LICENSE "${STAGE}\terms.txt"
!insertmacro MUI_PAGE_COMPONENTS
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipWhenUpdating
!insertmacro MUI_PAGE_DIRECTORY
!define MUI_PAGE_HEADER_TEXT "$InstHeader"
!define MUI_PAGE_HEADER_SUBTEXT "$InstSubtext"
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "$FinishText"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME} now"
!define MUI_FINISHPAGE_RUN_FUNCTION StartNow
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; This installer is 32-bit, and Windows shows a 32-bit program SysWOW64 wherever it
; asks for System32, on whichever thread asks, so the 32-bit PowerShell would start.
; Sysnative is the way through to the real one.  Shortcuts are opened by Explorer,
; which is 64-bit and has no Sysnative, so they name System32.
Var PowerShell      ; for running, from here
Var PowerShellLink  ; for shortcuts

!macro FindPowerShell
  StrCpy $PowerShellLink "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  ${If} ${RunningX64}
    StrCpy $PowerShell "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  ${Else}
    StrCpy $PowerShell $PowerShellLink
  ${EndIf}
!macroend

Function un.onInit
  !insertmacro FindPowerShell
FunctionEnd

Function StartNow
  ExecShell "" "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
FunctionEnd

; An update goes where the app already is: a new folder would be a second install.
Function SkipWhenUpdating
  ${If} $Updating == 1
    Abort
  ${EndIf}
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
  WriteRegStr HKCU "Software\${REGNAME}" "InstallDir" "$INSTDIR"
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
  ; Remembered, so an update offers the same choice again.
  ${If} ${SectionIsSelected} ${SecLyrics}
    WriteRegDWORD HKCU "Software\${REGNAME}" "Lyrics" 1
  ${Else}
    WriteRegDWORD HKCU "Software\${REGNAME}" "Lyrics" 0
  ${EndIf}
  DetailPrint "Setting up. Its progress is in a separate window, which may be behind this one."
  ${If} $Updating == 1
    DetailPrint "Updating from $OldVersion to ${VERSION}: only what has changed is downloaded."
    ${If} ${SectionIsSelected} ${SecLyrics}
    ${AndIf} ${FileExists} "$INSTDIR\engine\ComfyUI\models\text_encoders\gemma4_e4b_it_int8_convrot.safetensors"
      DetailPrint "Gemma 4 is already here, so it is not downloaded again."
    ${EndIf}
  ${Else}
    DetailPrint "This takes a while: about 24 GB to download."
  ${EndIf}
  ExecWait '"$PowerShell" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\setup.ps1" -InstallDir "$INSTDIR" $1 ${SETUP_ARGS}' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Setup did not finish.$\r$\n$\r$\nThe details are in $INSTDIR\logs\install.log. Run this installer again to carry on from where it stopped." /SD IDOK
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\venv\Scripts\python.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\yue2studio.ico"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Repair ${APPNAME}.lnk" "$PowerShellLink" '-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\setup.ps1" -InstallDir "$INSTDIR"' "$INSTDIR\yue2studio.ico"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\venv\Scripts\python.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\yue2studio.ico"
SectionEnd

LangString DESC_Core ${LANG_ENGLISH} "The app, the engine (ComfyUI), and the YuE2 models."
LangString DESC_Lyrics ${LANG_ENGLISH} "Gemma 4, for lyric drafts and song analysis on this PC. Leave it out if you intend to configure an external LLM. This will save an 8 GB download."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} $(DESC_Core)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecLyrics} $LyricsText
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; After the sections, so their names can be used here.
Function .onInit
  !insertmacro FindPowerShell
  StrCpy $Updating 0
  ReadRegStr $OldVersion HKCU "${REGKEY}" "DisplayVersion"
  ReadRegStr $0 HKCU "Software\${REGNAME}" "InstallDir"
  ${If} $OldVersion != ""
  ${AndIf} $0 != ""
  ${AndIf} ${FileExists} "$0\launcher.py"
    StrCpy $Updating 1
    StrCpy $INSTDIR $0
  ${EndIf}

  ${If} $Updating == 1
    ${If} $OldVersion == "${VERSION}"
      StrCpy $WelcomeTitle "Reinstall ${APPNAME} ${VERSION}"
      StrCpy $WelcomeText "${APPNAME} ${VERSION} is already installed on this PC. This installs it again over itself, which can repair a copy that has stopped working.$\r$\n$\r$\nYour library, settings, LoRAs and models are kept, and anything already in place is not downloaded again.$\r$\n$\r$\nIf ${APPNAME} is running, it is closed first."
      StrCpy $InstHeader "Reinstalling ${APPNAME}"
      StrCpy $FinishText "${APPNAME} ${VERSION} has been installed again.$\r$\n$\r$\nYour library and settings are as you left them."
    ${Else}
      StrCpy $WelcomeTitle "Update ${APPNAME}"
      StrCpy $WelcomeText "${APPNAME} $OldVersion is installed on this PC. This updates it to ${VERSION}.$\r$\n$\r$\nYour library, settings, LoRAs and models are kept, and only what has changed is downloaded, so it takes minutes rather than hours.$\r$\n$\r$\nIf ${APPNAME} is running, it is closed first."
      StrCpy $InstHeader "Updating ${APPNAME}"
      StrCpy $FinishText "${APPNAME} has been updated from $OldVersion to ${VERSION}.$\r$\n$\r$\nYour library and settings are as you left them."
    ${EndIf}
    StrCpy $InstSubtext "Only what has changed is downloaded. The setup window may be behind this one."
    StrCpy $LyricsText "$(DESC_Lyrics)"
    ; Only the app itself is new: the engine and the models are already here.
    SectionSetSize ${SecCore} 100000
    ; Gemma as chosen last time: kept if it is here, left out if it was left out.
    ReadRegDWORD $1 HKCU "Software\${REGNAME}" "Lyrics"
    ${If} ${FileExists} "$INSTDIR\engine\ComfyUI\models\text_encoders\gemma4_e4b_it_int8_convrot.safetensors"
      ; Already downloaded: said plainly, so nobody fears another 8 GB.
      SectionSetSize ${SecLyrics} 0
      SectionSetText ${SecLyrics} "Gemma 4 (installed)"
      StrCpy $LyricsText "Gemma 4 is already on this PC, so nothing is downloaded for it. Leave it ticked to keep using it for lyric drafts and song analysis. Unticking it does not remove it."
    ${ElseIf} $1 != 1
      ; Left out when installing, most likely for an external LLM: it stays out
      ; unless ticked now, and the page says why it is not ticked.
      !insertmacro UnselectSection ${SecLyrics}
      StrCpy $LyricsText "Gemma 4 was left out when ${APPNAME} was installed, so lyric drafts and song analysis use the external LLM set in Settings. It stays out unless you tick it; ticking it downloads about 8 GB."
    ${EndIf}
  ${Else}
    StrCpy $WelcomeTitle "Install ${APPNAME}"
    StrCpy $LyricsText "$(DESC_Lyrics)"
    StrCpy $WelcomeText "${APPNAME} writes and covers songs with the YuE2 music model, on this PC.$\r$\n$\r$\nThis installer is small. It checks that this PC can run YuE2 (an NVIDIA RTX 30-series card or newer), then downloads the rest from each part's publisher: about 24 GB, most of it the models. A download that breaks off carries on where it stopped when you run the installer again.$\r$\n$\r$\nA separate window shows the setup's progress; it may open behind this one.$\r$\n$\r$\nYou need about 40 GB of free space."
    StrCpy $InstHeader "Installing ${APPNAME}"
    StrCpy $InstSubtext "The setup window shows its progress, and may be behind this one."
    StrCpy $FinishText "${APPNAME} has been installed on this PC."
  ${EndIf}
FunctionEnd

Section "Uninstall"
  nsExec::Exec '"$PowerShell" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -like $\'$INSTDIR\*$\' -and $$_.Name -in $\'python.exe$\',$\'pythonw.exe$\',$\'ffmpeg.exe$\',$\'ffprobe.exe$\' } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force }"'
  Pop $0
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "Software\${REGNAME}"

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
