#!/usr/bin/env python3
"""
Automatic Tinder Chat - Tinder Automation
==========================================

Script principal que:
1. Cria e configura ambiente virtual automaticamente
2. Instala dependências
3. Carrega variáveis de ambiente
4. Executa a aplicação
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).parent.absolute()
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"


def print_banner():
    """Exibe banner da aplicação."""
    banner = """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║    🔥 AUTOMATIC TINDER CHAT - TINDER AUTOMATION 🔥        ║
    ║                                                           ║
    ║    Automação inteligente para Tinder com AI               ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


def check_python_version():
    """Verifica se a versão do Python é compatível."""
    if sys.version_info < (3, 9):
        print("❌ Python 3.9 ou superior é necessário!")
        print(f"   Versão atual: {sys.version}")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detectado")


def setup_venv():
    """Cria e configura o ambiente virtual."""
    print("\n📦 Configurando ambiente virtual...")
    
    if not VENV_DIR.exists():
        print("   Criando .venv...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        print("   ✅ Ambiente virtual criado")
    else:
        print("   ✅ Ambiente virtual já existe")
    
    # Determinar caminhos do venv
    if sys.platform == "win32":
        python_path = VENV_DIR / "Scripts" / "python.exe"
        pip_path = VENV_DIR / "Scripts" / "pip.exe"
    else:
        python_path = VENV_DIR / "bin" / "python"
        pip_path = VENV_DIR / "bin" / "pip"
    
    return python_path, pip_path


def install_dependencies(pip_path: Path):
    """Instala dependências do requirements.txt."""
    print("\n📥 Instalando dependências...")
    
    if not REQUIREMENTS_FILE.exists():
        print("   ⚠️ requirements.txt não encontrado!")
        return
    
    # Atualizar pip
    subprocess.run(
        [str(pip_path), "install", "--upgrade", "pip"],
        capture_output=True
    )
    
    # Instalar requirements
    result = subprocess.run(
        [str(pip_path), "install", "-r", str(REQUIREMENTS_FILE)],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("   ✅ Dependências instaladas com sucesso")
    else:
        print("   ⚠️ Algumas dependências podem ter falhado:")
        print(result.stderr[:500] if result.stderr else "")
    
    # Instalar Playwright browsers
    print("\n🌐 Instalando navegadores do Playwright...")
    python_path = pip_path.parent / "python.exe" if sys.platform == "win32" else pip_path.parent / "python"
    result = subprocess.run(
        [str(python_path), "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print("   ✅ Playwright configurado")
    else:
        print("   ⚠️ Playwright pode precisar ser instalado manualmente:")
        print("      python -m playwright install chromium")


def setup_env_file():
    """Configura arquivo .env se não existir."""
    print("\n⚙️ Verificando configurações...")
    
    if not ENV_FILE.exists():
        if ENV_EXAMPLE_FILE.exists():
            shutil.copy(ENV_EXAMPLE_FILE, ENV_FILE)
            print("   ⚠️ Arquivo .env criado a partir do exemplo")
            print("   ⚠️ IMPORTANTE: Configure suas variáveis no .env antes de usar!")
            print(f"   📄 Arquivo: {ENV_FILE}")
        else:
            print("   ❌ Arquivo .env.example não encontrado!")
    else:
        print("   ✅ Arquivo .env encontrado")


def check_env_variables():
    """Verifica se variáveis críticas estão configuradas."""
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
    
    required_vars = ["OPENAI_API_KEY"]
    missing = []
    
    for var in required_vars:
        value = os.getenv(var, "")
        if not value or value.startswith("sk-sua-chave"):
            missing.append(var)
    
    if missing:
        print("\n⚠️ ATENÇÃO: Variáveis não configuradas:")
        for var in missing:
            print(f"   - {var}")
        print("\n   Configure o arquivo .env antes de continuar!")
        return False
    
    return True


def run_application(python_path: Path, mode: str = "web"):
    """Executa a aplicação no modo especificado."""
    print(f"\n🚀 Iniciando aplicação (modo: {mode})...")
    
    if mode == "web":
        # Executar servidor web
        subprocess.run([
            str(python_path),
            "-c",
            """
from web.app import run_web_server
print("\\n🌐 Iniciando interface web...")
print("   Acesse: http://localhost:5000")
print("   Painel de Controle: http://localhost:5000/control")
print("   Pressione Ctrl+C para encerrar\\n")
run_web_server(host='0.0.0.0', port=5000, debug=True)
            """
        ], cwd=str(PROJECT_ROOT))
    
    elif mode == "automation":
        # Executar automação contínua
        interval = 10  # minutos padrão
        
        # Verificar se há argumentos de intervalo
        if len(sys.argv) > 2:
            try:
                interval = int(sys.argv[2])
            except ValueError:
                pass
        
        subprocess.run([
            str(python_path),
            "-c",
            f"""
import asyncio
from automation import run_automation

print('''
╔═══════════════════════════════════════════════════════════╗
║    🔄 AUTOMAÇÃO CONTÍNUA INICIADA                         ║
╠═══════════════════════════════════════════════════════════╣
║  O sistema irá:                                           ║
║  - Verificar novos matches periodicamente                 ║
║  - Enviar primeiras mensagens para novos matches          ║
║  - Responder mensagens pendentes                          ║
║  - Detectar WhatsApp e encontros                          ║
║                                                           ║
║  Intervalo entre ciclos: {interval} minutos               ║
║  Pressione Ctrl+C para encerrar graciosamente             ║
║  Ou pare pela interface web: http://localhost:5000/control║
╚═══════════════════════════════════════════════════════════╝
''')

result = asyncio.run(run_automation(interval_minutes={interval}))
print(f"\\nResultado final: {{result}}")
            """
        ], cwd=str(PROJECT_ROOT))
    
    elif mode == "reset":
        # Forçar reset do estado
        subprocess.run([
            str(python_path),
            "-c",
            """
from automation.state_manager import get_state_manager
state_manager = get_state_manager()
state_manager.force_reset()
print("✅ Estado resetado com sucesso!")
print("   Agora você pode iniciar a automação normalmente.")
            """
        ], cwd=str(PROJECT_ROOT))
    
    elif mode == "sync":
        # Executar apenas sincronização
        subprocess.run([
            str(python_path),
            "-c",
            """
import asyncio
from automation import sync_matches_only
result = asyncio.run(sync_matches_only())
print(f"Resultado: {result}")
            """
        ], cwd=str(PROJECT_ROOT))
    
    elif mode == "reports":
        # Gerar relatórios
        subprocess.run([
            str(python_path),
            "-c",
            """
from reports import generate_report
result = generate_report()
print(f"Relatório gerado: {result.get('report_path', 'N/A')}")
            """
        ], cwd=str(PROJECT_ROOT))


def main():
    """Função principal."""
    print_banner()
    
    # Verificar Python
    check_python_version()
    
    # Configurar ambiente
    python_path, pip_path = setup_venv()
    
    # Verificar se é primeira execução (sem pacotes instalados)
    try:
        subprocess.run(
            [str(python_path), "-c", "import customtkinter"],
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError:
        # Primeira execução - instalar dependências
        install_dependencies(pip_path)
    
    # Configurar .env
    setup_env_file()
    
    # Determinar modo de execução
    mode = "web"  # Padrão é web
    
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--automation", "-a", "--continuous", "-c", "--daemon", "-d"]:
            mode = "automation"
        elif arg in ["--reports", "-r"]:
            mode = "reports"
        elif arg in ["--sync", "-s"]:
            mode = "sync"
        elif arg in ["--reset", "--force-reset"]:
            # Forçar reset do estado (limpa locks travados)
            mode = "reset"
        elif arg in ["--help", "-h"]:
            print("""
Uso: python main.py [opção] [argumentos]

Opções:
    (sem opção)         Inicia interface web (padrão)
    --automation, -a    🔄 Executa automação contínua
                        Argumento opcional: intervalo em minutos (padrão: 10)
                        Exemplo: python main.py -a 15
    --sync, -s          Sincroniza matches apenas
    --reports, -r       Gera relatórios
    --reset             🔧 Força reset do estado (limpa locks travados)
    --help, -h          Mostra esta ajuda
    
🔄 Modo Automação (--automation):
   - Roda indefinidamente até Ctrl+C ou parada via web
   - Verifica novos matches a cada ciclo
   - Responde mensagens pendentes automaticamente
   - Detecta WhatsApp e encontros
   - Ideal para deixar rodando 24/7
   - Pode ser parado pela interface web
   
🔧 Reset (--reset):
   - Use se o script disser que já está rodando quando não está-
   - Limpa estados travados de execuções anteriores
    
Interface Web: http://localhost:5000
Painel de Controle: http://localhost:5000/control
            """)
            return
    
    # Verificar variáveis de ambiente (apenas aviso, não bloqueia)
    # check_env_variables()
    
    # Executar aplicação
    run_application(python_path, mode)


if __name__ == "__main__":
    main()
