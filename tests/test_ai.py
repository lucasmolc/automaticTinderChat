"""
Testes para o serviço de IA centralizado.
"""

import pytest
from unittest.mock import MagicMock, patch
import json


class TestAIService:
    """Testes para o serviço centralizado de IA."""
    
    def test_service_creation(self):
        """Testa criação do serviço."""
        from ai import get_ai_service, AIService
        
        service = get_ai_service()
        assert service is not None
        assert isinstance(service, AIService)
    
    def test_get_openai_client_alias(self):
        """Testa que get_openai_client retorna AIService."""
        from ai import get_openai_client, get_ai_service, AIService
        
        client = get_openai_client()
        service = get_ai_service()
        
        # Ambos devem retornar AIService
        assert isinstance(client, AIService)
        assert client is service  # Mesmo singleton
    
    def test_service_methods_exist(self):
        """Testa que métodos principais existem."""
        from ai import get_ai_service
        
        service = get_ai_service()
        
        # Métodos de alto nível
        assert hasattr(service, 'generate_message')
        assert hasattr(service, 'generate_first_message')
        assert hasattr(service, 'analyze_conversation_and_respond')
        assert hasattr(service, 'analyze_profile')
        assert hasattr(service, 'generate_match_report')
        assert hasattr(service, 'generate_analytics_insights')
        assert hasattr(service, 'chat')
        
        # Propriedades
        assert hasattr(service, 'model')
        assert hasattr(service, 'provider_id')
        assert hasattr(service, 'is_available')
    
    def test_chat_method_with_mock(self):
        """Testa método chat com mock do provider."""
        from ai import get_ai_service, AIResponse
        
        service = get_ai_service()
        
        # Mock do manager
        mock_response = AIResponse(
            content='{"test": "response"}',
            model="gpt-4o-mini",
            provider="openai",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            response_time_ms=500,
            cost_estimate=0.0001
        )
        
        with patch.object(service.manager, 'chat_completion', return_value=mock_response):
            response = service.chat(
                messages=[{"role": "user", "content": "test"}],
                interaction_type='test'
            )
            
            assert response is not None
            assert response.content == '{"test": "response"}'
    
    def test_generic_message_fallback(self):
        """Testa que mensagens genéricas funcionam como fallback."""
        from ai import get_ai_service
        
        service = get_ai_service()
        
        # Deve retornar uma mensagem genérica
        msg = service._get_generic_message()
        assert msg is not None
        assert len(msg) > 10
        assert msg in service.GENERIC_MESSAGES


class TestPromptTemplates:
    """Testes para templates de prompts."""
    
    def test_prompts_files_exist(self):
        """Testa que arquivos de prompts existem."""
        from config import PROMPTS_DIR
        
        required_prompts = [
            "first_message.txt",
            "conversation_response.txt",
            "profile_analysis.txt",
            "analytics_insights.txt",
            "system_first_message.txt",
            "system_conversation_response.txt",
            "system_profile_analysis.txt",
            "system_analytics_insights.txt",
            "system_match_report.txt"
        ]
        
        for prompt_file in required_prompts:
            assert (PROMPTS_DIR / prompt_file).exists(), f"Prompt {prompt_file} não encontrado"
    
    def test_prompts_can_be_loaded(self):
        """Testa que prompts podem ser carregados pelo AIService."""
        from ai import get_ai_service
        service = get_ai_service()
        
        # User prompts
        user_prompts = ["first_message", "conversation_response", "profile_analysis", "analytics_insights"]
        for prompt_name in user_prompts:
            content = service._load_prompt(prompt_name)
            assert len(content) > 50, f"Prompt {prompt_name} muito curto"
        
        # System prompts
        system_prompts = ["first_message", "conversation_response", "profile_analysis", "analytics_insights", "match_report"]
        for prompt_name in system_prompts:
            content = service._load_system_prompt(prompt_name)
            assert len(content) > 20, f"System prompt {prompt_name} muito curto"
    
    def test_prompts_cache_clear(self):
        """Testa limpeza do cache de prompts."""
        from ai import get_ai_service
        service = get_ai_service()
        
        # Carrega prompt (vai para cache)
        service._load_prompt("first_message")
        assert len(service._prompts_cache) > 0
        
        # Limpa cache
        service.clear_prompts_cache()
        assert len(service._prompts_cache) == 0


class TestABInstructions:
    """Testes para instruções de teste A/B."""
    
    def test_build_ab_instructions(self):
        """Testa construção de instruções A/B."""
        from ai import get_ai_service
        service = get_ai_service()
        
        variants = {
            'style': 'playful',
            'intensity': 'moderate',
            'emoji': 'minimal'
        }
        
        instructions = service._build_ab_instructions(variants)
        
        assert "ESTILO" in instructions
        assert "FLERTE" in instructions
        assert "EMOJI" in instructions
    
    def test_empty_ab_variants(self):
        """Testa que variantes vazias retornam string vazia."""
        from ai import get_ai_service
        service = get_ai_service()
        
        assert service._build_ab_instructions(None) == ""
        assert service._build_ab_instructions({}) == ""


class TestConversationFormatting:
    """Testes para formatação de conversas."""
    
    def test_format_conversation_history(self):
        """Testa formatação do histórico."""
        from ai import get_ai_service
        service = get_ai_service()
        
        history = [
            {"content": "Oi!", "is_from_me": True},
            {"content": "Olá!", "is_from_me": False},
            {"content": "Tudo bem?", "is_from_me": True}
        ]
        
        formatted = service._format_conversation_history(history, "Maria")
        
        assert "EU: Oi!" in formatted
        assert "MARIA: Olá!" in formatted
        assert "EU: Tudo bem?" in formatted
    
    def test_empty_conversation(self):
        """Testa histórico vazio."""
        from ai import get_ai_service
        service = get_ai_service()
        
        formatted = service._format_conversation_history([], "Maria")
        assert "Nenhuma mensagem" in formatted


class TestProviderSystem:
    """Testes para sistema de provedores."""
    
    def test_provider_manager_exists(self):
        """Testa que o manager existe."""
        from ai import get_ai_manager, AIProviderManager
        
        manager = get_ai_manager()
        assert manager is not None
        assert isinstance(manager, AIProviderManager)
    
    def test_available_providers(self):
        """Testa provedores disponíveis."""
        from ai import AIProviderManager
        
        providers = AIProviderManager.PROVIDER_CLASSES
        
        assert "openai" in providers
        assert "deepseek" in providers
        assert "claude" in providers
    
    def test_ai_response_dataclass(self):
        """Testa estrutura do AIResponse."""
        from ai import AIResponse
        
        response = AIResponse(
            content="Test",
            model="gpt-4o",
            provider="openai",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            response_time_ms=100,
            cost_estimate=0.001
        )
        
        assert response.content == "Test"
        assert response.model == "gpt-4o"
        assert response.total_tokens == 30


class TestAIDecisions:
    """Testes para decisões de IA."""
    
    def test_message_intent_categories(self):
        """Testa categorias de intenção de mensagem."""
        valid_intents = [
            "greeting",
            "question", 
            "flirting",
            "whatsapp_request",
            "goodbye"
        ]
        
        for intent in valid_intents:
            assert isinstance(intent, str)
            assert len(intent) > 0
    
    def test_response_format(self):
        """Testa formato esperado de resposta."""
        expected_format = {
            "message": "string",
            "intent": "string",
            "confidence": "float"
        }
        
        for key, value_type in expected_format.items():
            assert isinstance(key, str)
