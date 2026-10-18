@echo off
rem One WhatsApp phone pass (join <=1 group, read unread groups, push leads).
rem Manual run. The 2h schedule is wa_loop.py (Startup-folder shortcut) - see wa_phone.py.
cd /d "%~dp0"
"C:\Users\Administrator\anaconda3\python.exe" -X utf8 main.py --wa-pass >> wa_pass.log 2>&1
