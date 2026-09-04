; NSIS Script for SwiftCut Installer

;--------------------------------
; Defines
; These are variables passed from our build script using the -D flag
!define PRODUCT_NAME "SwiftCut"
!ifndef APP_VERSION
  !define APP_VERSION "0.0.0"
!endif
!ifndef APP_DIR_NAME
  !define APP_DIR_NAME "swiftcut-v0.0.0"
!endif
!ifndef EXECUTABLE_NAME
  !define EXECUTABLE_NAME "swiftcut.exe"
!endif
!ifndef ICON_FILE
  !define ICON_FILE "swiftcut.ico"
!endif

;--------------------------------
; General

RequestExecutionLevel admin ; Request admin rights for installation
SetCompressor lzma ; Use modern, efficient compression

; Installer attributes
Name "${PRODUCT_NAME} ${APP_VERSION}"
OutFile "..\..\dist\swiftcut-v${APP_VERSION}-installer.exe"
InstallDir "$PROGRAMFILES64\${PRODUCT_NAME}"
InstallDirRegKey HKLM "Software\${PRODUCT_NAME}" "Install_Dir"
Icon "..\..\${ICON_FILE}"
UninstallIcon "..\..\${ICON_FILE}"

;--------------------------------
; Pages

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

;--------------------------------
; Installer Section

Section "MainSection" SEC01
  SetOutPath "$INSTDIR"
  
  ; Copy all files from the PyInstaller output directory
  File /r "..\..\dist\${APP_DIR_NAME}\*.*"
  
  ; Store installation folder
  WriteRegStr HKLM "Software\${PRODUCT_NAME}" "Install_Dir" "$INSTDIR"
  
  ; Write the uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "DisplayIcon" "$INSTDIR\${EXECUTABLE_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "DisplayVersion" "${APP_VERSION}"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "NoRepair" 1
  
  ; Register .ryp file type
  WriteRegStr HKCR ".ryp" "" "SwiftCut.ProjectFile"
  WriteRegStr HKCR "SwiftCut.ProjectFile" "" "SwiftCut Project File"
  WriteRegStr HKCR "SwiftCut.ProjectFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.ProjectFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .rfs file type
  WriteRegStr HKCR ".rfs" "" "SwiftCut.SketchFile"
  WriteRegStr HKCR "SwiftCut.SketchFile" "" "SwiftCut Sketch File"
  WriteRegStr HKCR "SwiftCut.SketchFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.SketchFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .rd file type (Ruida)
  WriteRegStr HKCR ".rd" "" "SwiftCut.RuidaFile"
  WriteRegStr HKCR "SwiftCut.RuidaFile" "" "Ruida Laser Cutter File"
  WriteRegStr HKCR "SwiftCut.RuidaFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.RuidaFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .png file type
  WriteRegStr HKCR ".png" "" "SwiftCut.PngFile"
  WriteRegStr HKCR "SwiftCut.PngFile" "" "PNG Image"
  WriteRegStr HKCR "SwiftCut.PngFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.PngFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .bmp file type
  WriteRegStr HKCR ".bmp" "" "SwiftCut.BmpFile"
  WriteRegStr HKCR "SwiftCut.BmpFile" "" "BMP Image"
  WriteRegStr HKCR "SwiftCut.BmpFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.BmpFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .jpeg file type
  WriteRegStr HKCR ".jpeg" "" "SwiftCut.JpegFile"
  WriteRegStr HKCR "SwiftCut.JpegFile" "" "JPEG Image"
  WriteRegStr HKCR "SwiftCut.JpegFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.JpegFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .jpg file type
  WriteRegStr HKCR ".jpg" "" "SwiftCut.JpgFile"
  WriteRegStr HKCR "SwiftCut.JpgFile" "" "JPEG Image"
  WriteRegStr HKCR "SwiftCut.JpgFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.JpgFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .svg file type
  WriteRegStr HKCR ".svg" "" "SwiftCut.SvgFile"
  WriteRegStr HKCR "SwiftCut.SvgFile" "" "SVG Image"
  WriteRegStr HKCR "SwiftCut.SvgFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.SvgFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'

  ; Register .dxf file type
  WriteRegStr HKCR ".dxf" "" "SwiftCut.DxfFile"
  WriteRegStr HKCR "SwiftCut.DxfFile" "" "DXF Drawing"
  WriteRegStr HKCR "SwiftCut.DxfFile\DefaultIcon" "" "$INSTDIR\${EXECUTABLE_NAME},0"
  WriteRegStr HKCR "SwiftCut.DxfFile\shell\open\command" "" '"$INSTDIR\${EXECUTABLE_NAME}" "%1"'
  
  ; Create Start Menu shortcuts
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\${EXECUTABLE_NAME}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall ${PRODUCT_NAME}.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

;--------------------------------
; Uninstaller Section

Section "Uninstall"
  ; Remove registry keys
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
  DeleteRegKey HKLM "Software\${PRODUCT_NAME}"
  
  ; Unregister .ryp file type
  DeleteRegKey HKCR ".ryp"
  DeleteRegKey HKCR "SwiftCut.ProjectFile"

  ; Unregister .rfs file type
  DeleteRegKey HKCR ".rfs"
  DeleteRegKey HKCR "SwiftCut.SketchFile"

  ; Unregister .rd file type (Ruida)
  DeleteRegKey HKCR ".rd"
  DeleteRegKey HKCR "SwiftCut.RuidaFile"

  ; Unregister .png file type
  DeleteRegKey HKCR ".png"
  DeleteRegKey HKCR "SwiftCut.PngFile"

  ; Unregister .bmp file type
  DeleteRegKey HKCR ".bmp"
  DeleteRegKey HKCR "SwiftCut.BmpFile"

  ; Unregister .jpeg file type
  DeleteRegKey HKCR ".jpeg"
  DeleteRegKey HKCR "SwiftCut.JpegFile"

  ; Unregister .jpg file type
  DeleteRegKey HKCR ".jpg"
  DeleteRegKey HKCR "SwiftCut.JpgFile"

  ; Unregister .svg file type
  DeleteRegKey HKCR ".svg"
  DeleteRegKey HKCR "SwiftCut.SvgFile"

  ; Unregister .dxf file type
  DeleteRegKey HKCR ".dxf"
  DeleteRegKey HKCR "SwiftCut.DxfFile"

  ; Remove the entire installation directory
  ; We delete the uninstaller first, then recursively remove its parent directory.
  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$INSTDIR"

  ; Remove shortcuts
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\*.*"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
SectionEnd
