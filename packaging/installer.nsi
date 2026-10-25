Unicode true
!include "MUI2.nsh"

!define APP_NAME "一伯六十八的ASMR听译间"
!define APP_VERSION "1.1.2"
!define APP_EXE "ASMR168.exe"

Name "${APP_NAME}"
OutFile "..\release\ASMR168-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\ASMR168"
RequestExecutionLevel user
SetCompressor /SOLID zlib
Icon "..\static\app.ico"
UninstallIcon "..\static\app.ico"
VIProductVersion "1.1.2.0"
VIAddVersionKey /LANG=2052 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_NAME} 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "启动 ${APP_NAME}"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "..\dist\ASMR168\*.*"
  FileOpen $0 "$INSTDIR\.asmr168-install-marker" w
  FileWrite $0 "ASMR168 1.1.2"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\ASMR168"
  CreateShortcut "$SMPROGRAMS\ASMR168\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortcut "$SMPROGRAMS\ASMR168\卸载.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ASMR168" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ASMR168" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ASMR168" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ASMR168" "DisplayVersion" "${APP_VERSION}"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ASMR168" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ASMR168" "NoRepair" 1
SectionEnd

Section "Uninstall"
  IfFileExists "$INSTDIR\.asmr168-install-marker" +2
    Abort "未找到应用安装标记，停止卸载以保护其他文件。"
  Delete "$SMPROGRAMS\ASMR168\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\ASMR168\卸载.lnk"
  RMDir "$SMPROGRAMS\ASMR168"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ASMR168"
  ; User jobs and onboarding remain in %LOCALAPPDATA%\ASMR168.
SectionEnd
