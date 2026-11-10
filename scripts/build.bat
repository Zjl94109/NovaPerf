@echo off
REM NovaPerf 一键构建：SDK AAR + Demo APK -> dist\
setlocal
set "ROOT=%~dp0.."
if "%GRADLE_USER_HOME%"=="" set "GRADLE_USER_HOME=%USERPROFILE%\.gradle"
cd /d "%ROOT%\android" || goto :err

echo [1/3] Gradle build ...
call gradlew.bat :novaperf-sdk:assembleRelease :demo:assembleDebug --console=plain || goto :err

echo [2/3] Copy artifacts ...
if not exist "%ROOT%\dist" mkdir "%ROOT%\dist"
copy /Y "novaperf-sdk\build\outputs\aar\novaperf-sdk-release.aar" "%ROOT%\dist\NovaPerf-SDK.aar" >nul || goto :err
copy /Y "demo\build\outputs\apk\debug\demo-debug.apk" "%ROOT%\dist\NovaPerf-Demo.apk" >nul || goto :err

echo [3/3] Done.
dir "%ROOT%\dist\NovaPerf-*.aar" "%ROOT%\dist\NovaPerf-*.apk"
exit /b 0

:err
echo BUILD FAILED. 检查 JDK17 / ANDROID_HOME / android\local.properties 的 sdk.dir
exit /b 1
