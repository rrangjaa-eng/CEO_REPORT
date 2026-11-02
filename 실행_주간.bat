@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
python --version >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
) else (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    echo Python 3.8 이상이 필요합니다.
    echo https://www.python.org/downloads/ 에서 설치하고, 설치 첫 화면에서 'Add python.exe to PATH'를 선택하세요.
    pause
    exit /b 1
)
%PY% 보고서.py 주간 %*
set "RC=%ERRORLEVEL%"
echo.
echo 결과 파일은 출력 폴더에 있습니다.
pause
exit /b %RC%
