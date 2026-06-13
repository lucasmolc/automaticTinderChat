"""
Script de Limpeza e Correção do Banco de Dados.

Este script:
1. Identifica matches com estado inconsistente
2. Corrige flags first_message_sent vs mensagens reais
3. Remove duplicatas de mensagens
4. Gera relatório de correções

USO:
    python scripts/db_cleanup.py --dry-run    # Apenas mostra o que seria feito
    python scripts/db_cleanup.py --fix        # Aplica as correções
    python scripts/db_cleanup.py --report     # Gera relatório completo
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple

# Adicionar path do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Match, Message, get_db_manager


def analyze_inconsistencies(session) -> Dict:
    """
    Analisa inconsistências no banco de dados.
    
    Returns:
        Dict com categorias de problemas encontrados
    """
    issues = {
        "first_message_sent_without_messages": [],
        "has_messages_without_messages": [],
        "messages_without_flags": [],
        "duplicate_first_messages": [],
        "orphan_messages": [],
    }
    
    print("\n🔍 Analisando banco de dados...")
    
    # 1. Matches com first_message_sent=True mas sem mensagens minhas
    matches_with_flag = session.query(Match).filter(
        Match.first_message_sent == True
    ).all()
    
    for match in matches_with_flag:
        my_messages = session.query(Message).filter(
            Message.match_id == match.id,
            Message.is_from_me == True
        ).count()
        
        if my_messages == 0:
            issues["first_message_sent_without_messages"].append({
                "match_id": match.id,
                "tinder_match_id": match.tinder_match_id,
                "name": match.name,
                "first_message_sent": match.first_message_sent,
                "has_messages": match.has_messages,
                "my_messages_count": my_messages
            })
    
    # 2. Matches com has_messages=True mas sem nenhuma mensagem
    matches_with_has_messages = session.query(Match).filter(
        Match.has_messages == True
    ).all()
    
    for match in matches_with_has_messages:
        total_messages = session.query(Message).filter(
            Message.match_id == match.id
        ).count()
        
        if total_messages == 0:
            issues["has_messages_without_messages"].append({
                "match_id": match.id,
                "tinder_match_id": match.tinder_match_id,
                "name": match.name,
                "has_messages": match.has_messages,
                "total_messages": total_messages
            })
    
    # 3. Matches que têm mensagens minhas mas flags em False
    all_matches = session.query(Match).all()
    
    for match in all_matches:
        my_messages = session.query(Message).filter(
            Message.match_id == match.id,
            Message.is_from_me == True
        ).count()
        
        if my_messages > 0 and not match.first_message_sent:
            issues["messages_without_flags"].append({
                "match_id": match.id,
                "tinder_match_id": match.tinder_match_id,
                "name": match.name,
                "first_message_sent": match.first_message_sent,
                "my_messages_count": my_messages
            })
    
    # 4. Matches com múltiplas primeiras mensagens (duplicatas)
    for match in all_matches:
        first_messages = session.query(Message).filter(
            Message.match_id == match.id,
            Message.is_from_me == True,
            Message.message_type == "first_message"
        ).order_by(Message.sent_at).all()
        
        if len(first_messages) > 1:
            issues["duplicate_first_messages"].append({
                "match_id": match.id,
                "tinder_match_id": match.tinder_match_id,
                "name": match.name,
                "first_messages_count": len(first_messages),
                "messages": [
                    {
                        "id": m.id,
                        "content": m.content[:50] + "..." if len(m.content) > 50 else m.content,
                        "sent_at": str(m.sent_at)
                    }
                    for m in first_messages
                ]
            })
    
    # 5. Mensagens órfãs (sem match associado)
    orphan_messages = session.query(Message).filter(
        ~Message.match_id.in_(
            session.query(Match.id)
        )
    ).all()
    
    for msg in orphan_messages:
        issues["orphan_messages"].append({
            "message_id": msg.id,
            "match_id": msg.match_id,
            "content": msg.content[:50] + "..." if len(msg.content) > 50 else msg.content,
            "sent_at": str(msg.sent_at)
        })
    
    return issues


def fix_inconsistencies(session, issues: Dict, dry_run: bool = True) -> Dict:
    """
    Corrige inconsistências encontradas.
    
    Args:
        session: Sessão do banco
        issues: Dict de problemas encontrados
        dry_run: Se True, não aplica mudanças
        
    Returns:
        Dict com estatísticas de correção
    """
    stats = {
        "flags_reset": 0,
        "flags_set": 0,
        "duplicates_removed": 0,
        "orphans_removed": 0,
    }
    
    prefix = "🧪 [DRY-RUN]" if dry_run else "🔧 [FIXING]"
    
    # 1. Resetar flags de matches sem mensagens
    for issue in issues["first_message_sent_without_messages"]:
        print(f"{prefix} Resetando flags de {issue['name']} ({issue['tinder_match_id']})")
        if not dry_run:
            match = session.query(Match).filter(
                Match.id == issue["match_id"]
            ).first()
            if match:
                match.first_message_sent = False
                match.has_messages = False
        stats["flags_reset"] += 1
    
    for issue in issues["has_messages_without_messages"]:
        # Evitar duplicata se já estava na lista anterior
        already_processed = any(
            i["match_id"] == issue["match_id"] 
            for i in issues["first_message_sent_without_messages"]
        )
        if not already_processed:
            print(f"{prefix} Resetando has_messages de {issue['name']} ({issue['tinder_match_id']})")
            if not dry_run:
                match = session.query(Match).filter(
                    Match.id == issue["match_id"]
                ).first()
                if match:
                    match.has_messages = False
            stats["flags_reset"] += 1
    
    # 2. Corrigir flags de matches que têm mensagens mas flags False
    for issue in issues["messages_without_flags"]:
        print(f"{prefix} Corrigindo flags de {issue['name']} ({issue['tinder_match_id']})")
        if not dry_run:
            match = session.query(Match).filter(
                Match.id == issue["match_id"]
            ).first()
            if match:
                match.first_message_sent = True
                match.has_messages = True
        stats["flags_set"] += 1
    
    # 3. Remover mensagens duplicadas (manter a primeira)
    for issue in issues["duplicate_first_messages"]:
        # Manter a primeira mensagem (mais antiga)
        messages_to_remove = issue["messages"][1:]  # Todos exceto o primeiro
        for msg_info in messages_to_remove:
            print(f"{prefix} Removendo mensagem duplicada ID={msg_info['id']} de {issue['name']}")
            if not dry_run:
                session.query(Message).filter(
                    Message.id == msg_info["id"]
                ).delete()
            stats["duplicates_removed"] += 1
    
    # 4. Remover mensagens órfãs
    for issue in issues["orphan_messages"]:
        print(f"{prefix} Removendo mensagem órfã ID={issue['message_id']}")
        if not dry_run:
            session.query(Message).filter(
                Message.id == issue["message_id"]
            ).delete()
        stats["orphans_removed"] += 1
    
    if not dry_run:
        session.commit()
        print("\n✅ Correções aplicadas e commitadas!")
    
    return stats


def check_specific_match(session, tinder_match_id: str) -> Dict:
    """
    Verifica estado específico de um match.
    
    Args:
        session: Sessão do banco
        tinder_match_id: ID do match no Tinder
        
    Returns:
        Dict com informações detalhadas do match
    """
    match = session.query(Match).filter(
        Match.tinder_match_id == tinder_match_id
    ).first()
    
    if not match:
        return {"error": f"Match {tinder_match_id} não encontrado"}
    
    messages = session.query(Message).filter(
        Message.match_id == match.id
    ).order_by(Message.sent_at).all()
    
    my_messages = [m for m in messages if m.is_from_me]
    
    return {
        "match": {
            "id": match.id,
            "tinder_match_id": match.tinder_match_id,
            "name": match.name,
            "first_message_sent": match.first_message_sent,
            "has_messages": match.has_messages,
            "is_blocked": match.is_blocked,
            "is_unmatched": match.is_unmatched,
            "created_at": str(match.created_at),
            "last_message_at": str(match.last_message_at) if match.last_message_at else None,
        },
        "messages": {
            "total": len(messages),
            "my_messages": len(my_messages),
            "details": [
                {
                    "id": m.id,
                    "is_from_me": m.is_from_me,
                    "message_type": m.message_type,
                    "content": m.content[:100] + "..." if len(m.content) > 100 else m.content,
                    "sent_at": str(m.sent_at)
                }
                for m in messages
            ]
        },
        "consistency": {
            "flags_consistent": (
                (match.first_message_sent == (len(my_messages) > 0)) and
                (match.has_messages == (len(messages) > 0))
            ),
            "issues": []
        }
    }


def generate_report(issues: Dict, stats: Dict = None) -> str:
    """Gera relatório formatado."""
    lines = [
        "=" * 60,
        "RELATÓRIO DE INTEGRIDADE DO BANCO DE DADOS",
        f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]
    
    # Resumo
    total_issues = sum(len(v) for v in issues.values())
    lines.append(f"📊 RESUMO: {total_issues} problemas encontrados")
    lines.append("")
    
    for category, items in issues.items():
        category_name = category.replace("_", " ").title()
        lines.append(f"  • {category_name}: {len(items)}")
    
    lines.append("")
    lines.append("-" * 60)
    
    # Detalhes por categoria
    for category, items in issues.items():
        if items:
            category_name = category.replace("_", " ").upper()
            lines.append(f"\n📋 {category_name}")
            lines.append("-" * 40)
            
            for item in items[:10]:  # Limitar a 10 por categoria
                if "name" in item:
                    lines.append(f"  • {item.get('name', 'N/A')} ({item.get('tinder_match_id', 'N/A')})")
                    for k, v in item.items():
                        if k not in ["name", "tinder_match_id", "messages"]:
                            lines.append(f"    - {k}: {v}")
                else:
                    lines.append(f"  • {item}")
            
            if len(items) > 10:
                lines.append(f"  ... e mais {len(items) - 10} itens")
    
    # Estatísticas de correção (se disponíveis)
    if stats:
        lines.append("")
        lines.append("-" * 60)
        lines.append("\n🔧 CORREÇÕES APLICADAS")
        for k, v in stats.items():
            lines.append(f"  • {k.replace('_', ' ').title()}: {v}")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Script de limpeza do banco de dados")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que seria feito sem aplicar")
    parser.add_argument("--fix", action="store_true", help="Aplica as correções")
    parser.add_argument("--report", action="store_true", help="Gera relatório completo")
    parser.add_argument("--check-match", type=str, help="Verifica match específico por tinder_match_id")
    
    args = parser.parse_args()
    
    if not any([args.dry_run, args.fix, args.report, args.check_match]):
        parser.print_help()
        return
    
    db = get_db_manager()
    
    with db.get_session() as session:
        if args.check_match:
            # Verificar match específico
            print(f"\n🔍 Verificando match: {args.check_match}")
            result = check_specific_match(session, args.check_match)
            
            import json
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        
        # Analisar inconsistências
        issues = analyze_inconsistencies(session)
        
        if args.report or args.dry_run:
            report = generate_report(issues)
            print(report)
            
            # Salvar relatório
            report_path = f"logs/db_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            os.makedirs("logs", exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\n📄 Relatório salvo em: {report_path}")
        
        if args.dry_run:
            print("\n🧪 MODO DRY-RUN - Simulando correções...")
            stats = fix_inconsistencies(session, issues, dry_run=True)
            print(f"\n📊 Resumo do que seria corrigido:")
            for k, v in stats.items():
                print(f"  • {k}: {v}")
        
        if args.fix:
            print("\n⚠️  ATENÇÃO: Você está prestes a modificar o banco de dados!")
            confirm = input("Digite 'CONFIRMAR' para continuar: ")
            
            if confirm == "CONFIRMAR":
                print("\n🔧 Aplicando correções...")
                stats = fix_inconsistencies(session, issues, dry_run=False)
                
                report = generate_report(issues, stats)
                print(report)
                
                # Salvar relatório pós-correção
                report_path = f"logs/db_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"\n📄 Relatório de correção salvo em: {report_path}")
            else:
                print("❌ Operação cancelada.")


if __name__ == "__main__":
    main()
