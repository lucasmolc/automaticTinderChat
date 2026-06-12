@echo off
REM Script para executar testes do projeto

echo.
echo ========================================
echo    Automatic Tinder Chat - Testes
echo ========================================
echo.

REM Ativar ambiente virtual
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo [ERRO] Ambiente virtual nao encontrado!
    echo Execute: python -m venv .venv
    pause
    exit /b 1
)

REM Instalar dependências de teste se necessário
pip show pytest >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias de teste...
    pip install pytest pytest-asyncio pytest-cov
)

REM Executar testes
echo.
echo Executando testes...
echo.

REM Opção 1: Todos os testes
REM pytest tests/ -v

REM Opção 2: Testes com cobertura
pytest tests/ -v --cov=. --cov-report=html --cov-report=term-missing

echo.
echo ========================================
echo    Testes concluidos!
echo ========================================
echo.

REM Verificar relatório de cobertura
if exist htmlcov\index.html (
    echo Relatorio de cobertura gerado em: htmlcov\index.html
    echo.
)

pause
