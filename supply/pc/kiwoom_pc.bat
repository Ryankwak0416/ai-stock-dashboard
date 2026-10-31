@echo off
chcp 65001 >nul
REM 키움 REST 수집 — PC 전용 (키움에 IP 를 등록한 PC 에서 실행, 경로 D)
REM 1회 설정 (명령 프롬프트, 새 창부터 적용):
REM   setx KIWOOM_APPKEY "앱키"
REM   setx KIWOOM_SECRETKEY "시크릿키"
REM   pip install requests
REM 작업 스케줄러: 평일 18:45 에 이 파일 실행 → Actions 18:50 수집이 supply\kiwoom.json 을 합친다.
REM 조회 TR 만 부른다(주문·계좌 API 없음). 키 값은 파일에 남기지 않는다.
cd /d "%~dp0\..\.."
git pull --rebase --autostash origin main || goto :err
python supply\collect_supply.py --kiwoom-only || goto :err
git add supply\kiwoom.json
git diff --cached --quiet && goto :eof
git commit -m "kiwoom pc data %date%"
git push origin main || goto :err
goto :eof
:err
echo [키움 PC 수집] 실패 — 위 메시지를 확인
exit /b 1
