"""
Script para analisar matches e atualizar o status awaiting_my_response
baseado em quem enviou a última mensagem.
"""

import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no path, independente de onde o script roda.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import desc

from database import Match, MatchRepository, Message, MessageRepository, get_db_manager


def main():
    db = get_db_manager()
    db.initialize()
    
    with db.get_session() as session:
        match_repo = MatchRepository(session)
        
        # Buscar todos os matches ativos (não bloqueados, não unmatch)
        matches = session.query(Match).filter(
            Match.is_blocked == False,
            Match.is_unmatched == False
        ).all()
        
        print(f"Total de matches ativos: {len(matches)}")
        
        updates_needed = []
        updated_count = 0
        
        for match in matches:
            # Buscar última mensagem
            last_msg = session.query(Message).filter(
                Message.match_id == match.id
            ).order_by(desc(Message.sent_at), desc(Message.id)).first()
            
            if last_msg:
                old_status = match.awaiting_my_response
                # Se EU enviei a última, awaiting_my_response = False (estou esperando ela responder)
                # Se ELA enviou a última, awaiting_my_response = True (tenho que responder)
                new_status = not last_msg.is_from_me
                
                if old_status != new_status:
                    from_who = "EU" if last_msg.is_from_me else match.name
                    msg_preview = (last_msg.content[:40] + "...") if last_msg.content and len(last_msg.content) > 40 else (last_msg.content or "")
                    
                    updates_needed.append({
                        'match': match,
                        'name': match.name,
                        'old': old_status,
                        'new': new_status,
                        'from_who': from_who,
                        'msg_preview': msg_preview
                    })
        
        print(f"\nMatches que precisam atualizar: {len(updates_needed)}")
        print("-" * 80)
        
        for item in updates_needed:
            print(f"  {item['name']:20} | awaiting: {item['old']} -> {item['new']} | Ultima de: {item['from_who']:15} | {item['msg_preview']}")
        
        if updates_needed:
            print("-" * 80)
            confirm = input(f"\nDeseja atualizar {len(updates_needed)} matches? (s/n): ")
            
            if confirm.lower() == 's':
                for item in updates_needed:
                    item['match'].awaiting_my_response = item['new']
                    updated_count += 1
                
                session.commit()
                print(f"\n✅ {updated_count} matches atualizados com sucesso!")
            else:
                print("\n❌ Operação cancelada.")
        else:
            print("\n✅ Todos os matches já estão com status correto!")

if __name__ == "__main__":
    main()
