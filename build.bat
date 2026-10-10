@echo off
chcp 65001 >nul
setlocal

rem ===== 按你的机器修改这两行 =====
set "PY=xxx" # python完整路径
set "CONDA_BIN=xxx" # bin文件夹完整路径
rem ===============================

rem 把本环境的 Library\bin 放到 PATH 最前，否则 PyInstaller 会从 base 环境
rem 收集到不匹配的 Tcl/Tk DLL，打包后的 exe 会报 init.tcl 版本冲突。
set "PATH=%CONDA_BIN%;%PATH%"

echo === 正在打包 GitHub 下载器（单文件 exe）===
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name GitHubDownloader ^
  --add-binary "%CONDA_BIN%\libssl-3-x64.dll;." ^
  --add-binary "%CONDA_BIN%\libcrypto-3-x64.dll;." ^
  main.py

echo.
echo === 完成，exe 在 dist\GitHubDownloader.exe ===
pause
