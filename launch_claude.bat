@echo off
REM ============================================================
REM  Claude(Cowork) 실행용 런처
REM  Windows 작업 스케줄러가 절전 해제 후 이 파일을 실행하면
REM  Claude 데스크톱이 켜지고, 이어서 Cowork 예약 작업(07:15)이
REM  뉴스 브리핑을 수집/저장/카톡 발송한다.
REM ============================================================

REM 일반적인 설치 경로 (Squirrel 런처)
set CLAUDE="%LOCALAPPDATA%\AnthropicClaude\claude.exe"

if exist %CLAUDE% (
    start "" %CLAUDE%
    goto :done
)

REM 위 경로에 없으면, 시작 메뉴 바로가기에서 실제 경로를 확인해
REM 아래 줄의 경로를 본인 환경에 맞게 수정하세요.
REM 예) start "" "C:\Users\<사용자>\AppData\Local\Programs\claude\Claude.exe"
echo [경고] 기본 경로에서 Claude.exe를 찾지 못했습니다. 이 .bat의 CLAUDE 경로를 수정하세요.

:done
