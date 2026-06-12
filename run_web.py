"""
Script para iniciar o servidor web.
Execute com: python run_web.py
"""

import sys
import os

# Adicionar diretório ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import run_web_server

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Servidor Web - Automatic Tinder Chat")
    parser.add_argument("--host", default="0.0.0.0", help="Host do servidor (default: 0.0.0.0)")
    parser.add_argument("--port", "-p", type=int, default=5000, help="Porta do servidor (default: 5000)")
    parser.add_argument("--debug", "-d", action="store_true", help="Modo debug")
    
    args = parser.parse_args()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           🌐 AUTOMATIC TINDER CHAT - WEB INTERFACE           ║
╠══════════════════════════════════════════════════════════════╣
║  Acesse: http://localhost:{args.port}                            ║
║  Pressione Ctrl+C para encerrar                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    run_web_server(host=args.host, port=args.port, debug=args.debug)
