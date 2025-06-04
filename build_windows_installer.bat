@echo off
REM Build stand-alone Cerebro installer using PyInstaller
pyinstaller --clean --noconfirm cerebro.spec
