@echo off
chcp 65001 >nul
pushd "%~dp0"
set "PY="
set "FOUND="
python --version >nul 2>&1
if errorlevel 1 goto TRYPY
set "FOUND=1"
python -c "import sys; sys.exit(int(sys.version_info[:2] < (3, 8)))" >nul 2>&1
if errorlevel 1 goto TRYPY
set "PY=python"
goto RUN
:TRYPY
py -3 --version >nul 2>&1
if errorlevel 1 goto NOPY
set "FOUND=1"
py -3 -c "import sys; sys.exit(int(sys.version_info[:2] < (3, 8)))" >nul 2>&1
if errorlevel 1 goto NOPY
set "PY=py -3"
goto RUN
:NOPY
if defined FOUND goto OLDPY
echo Python 3.8 이상이 필요합니다.
echo https://www.python.org/downloads/ 에서 설치하고, 설치 첫 화면에서 'Add python.exe to PATH'를 선택하세요.
goto FAIL
:OLDPY
echo 설치된 Python 버전이 3.8보다 낮습니다. 3.8 이상이 필요합니다.
echo https://www.python.org/downloads/ 에서 새 버전을 설치하고, 설치 첫 화면에서 'Add python.exe to PATH'를 선택하세요.
:FAIL
pause
popd
exit /b 1
:RUN
echo WEHAGO 엑셀은 수집\위하고, 인트라넷 스냅숏은 수집 폴더에서 읽어 입력 폴더에 CSV를 씁니다 (빈 양식: 입력양식 폴더).
%PY% 변환.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto OK
echo 오류가 발생했습니다. 위 메시지를 확인하세요. 결과 파일이 만들어지지 않았을 수 있습니다.
goto END
:OK
echo 변환을 마쳤습니다. 입력\변환결과.txt에 원본 합계 대조가 있습니다.
:END
pause
popd
exit /b %RC%
