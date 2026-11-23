@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH. Instale o Python 3 e tente novamente.
    pause
    exit /b 1
)

python -c "import serial, PySide6" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias pela primeira vez ^(pyserial, PySide6^)...
    python -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar as dependencias. Verifique sua conexao/permissoes.
        pause
        exit /b 1
    )
)

start "" pythonw "%~dp0ModbusTool.py"
