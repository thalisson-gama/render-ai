@echo off
REM Atalho da CLI no Windows.
REM   render --project "Banheiro TG" --all
REM   render --project "Banheiro TG" --camera cena1 --quality entrega
setlocal
cd /d "%~dp0"
python cli\render.py %*
endlocal
