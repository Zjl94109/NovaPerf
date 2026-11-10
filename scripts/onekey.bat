@echo off
REM NovaPerf 一键：构建 -> 安装 -> 真机采集 -> 诊断报告
REM 前置：adb 在 PATH；真机已开 USB 调试；Python 3.9+ 在 PATH
setlocal
set "ROOT=%~dp0.."

call "%~dp0build.bat" || exit /b 1

echo.
echo [安装] 若 ColorOS 弹出「继续安装」确认框，请在手机上点一下（adb install 会等待）。
adb install -g -r "%ROOT%\dist\NovaPerf-Demo.apk" || exit /b 1

echo.
echo [采集] 25 秒全自动负载 + 逐帧明细 ...
python "%ROOT%\cli\novaperf.py" collect --duration 25 --frames --scenario full ^
  --out "%ROOT%\examples\session_frames.jsonl" ^
  --report-out "%ROOT%\dist\NovaPerf-Report.html" || exit /b 1

echo.
echo 完成：%ROOT%\dist\NovaPerf-Report.html
start "" "%ROOT%\dist\NovaPerf-Report.html"
exit /b 0
