"""
Controlador do navegador usando Playwright.
Gerencia sessão, login e navegação no Tinder.
"""

import asyncio
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config import (
    get_settings, BROWSER_DATA_DIR,
    TINDER_URL, TINDER_APP_URL, TINDER_MATCHES_URL
)
from utils.logger import get_logger, log_file_only, console_log
from utils.helpers import async_random_delay

logger = get_logger(__name__)


class BrowserController:
    """Controla o navegador para automação do Tinder."""
    
    def __init__(self, headless: bool = None):
        self.settings = get_settings()
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._is_initialized = False
        # headless override: se passado explicitamente, usa esse valor;
        # caso contrário, usa a configuração do settings
        self._headless = headless if headless is not None else self.settings.browser_headless
    
    async def initialize(self) -> None:
        """Inicializa o navegador com perfil persistente."""
        if self._is_initialized:
            return
        
        mode_label = "headless" if self._headless else "visível"
        console_log(f"Inicializando navegador ({mode_label})...")
        
        self.playwright = await async_playwright().start()
        
        # IMPORTANTE: Usar diretório próprio do projeto para evitar conflito
        # com o Chrome já aberto. A sessão do Tinder precisará ser feita
        # novamente neste perfil separado.
        user_data_dir = str(BROWSER_DATA_DIR / "playwright_profile")
        
        # Criar diretório se não existir
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        
        log_file_only(f"Usando perfil em: {user_data_dir}")
        
        # Lançar navegador com perfil persistente
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=self._headless,
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--start-maximized"
            ]
        )
        
        # Usar página existente ou criar nova
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        
        self._is_initialized = True
        console_log("Navegador inicializado com sucesso")
    
    async def close(self) -> None:
        """Fecha o navegador."""
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        
        self._is_initialized = False
        log_file_only("Navegador fechado")
    
    async def navigate_to(self, url: str) -> None:
        """Navega para uma URL."""
        if not self._is_initialized:
            await self.initialize()
        
        log_file_only(f"Navegando para: {url}")
        await self.page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)  # Aguardar carregamento completo
    
    async def is_logged_in(self) -> bool:
        """Verifica se está logado no Tinder (sem navegar)."""
        try:
            # Verificar se há elementos de perfil logado na página atual
            element = await self.page.query_selector(
                '[data-testid="profileCard"], .profileCard, [class*="matchListItem"], a[href*="/app/matches"]'
            )
            if element:
                log_file_only("Usuário está logado no Tinder")
                return True
        except:
            pass
        
        # Verificar se está na página de login
        try:
            login_element = await self.page.query_selector(
                'text="Log in", text="Entrar", [data-testid="loginButton"], button:has-text("Log in")'
            )
            if login_element:
                console_log("⚠️ Usuário NÃO está logado - página de login detectada")
                return False
        except:
            pass
        
        return False
    
    async def wait_for_login(self, timeout: int = 300) -> bool:
        """
        Aguarda o usuário fazer login manualmente.
        NÃO navega - apenas espera na página atual.
        
        Args:
            timeout: Tempo máximo de espera em segundos (padrão: 5 minutos)
            
        Returns:
            True se login foi bem-sucedido
        """
        console_log("⏳ Aguardando login manual...")
        console_log("👆 Faça login no navegador que abriu e aguarde...")
        
        try:
            # Aguardar até que elementos do app apareçam (indica login)
            await self.page.wait_for_selector(
                '[data-testid="profileCard"], .profileCard, [class*="matchListItem"], a[href*="/app/matches"], [class*="navBar"]',
                timeout=timeout * 1000
            )
            console_log("✅ Login detectado com sucesso!")
            return True
        except:
            console_log("❌ Timeout aguardando login")
            return False
    
    async def navigate_to_matches(self) -> None:
        """Navega para a página de matches."""
        await self.navigate_to(TINDER_MATCHES_URL)
        await async_random_delay(0.5, 1)
    
    async def navigate_to_matches_if_needed(self) -> bool:
        """
        Navega para matches apenas se não estiver na página.
        
        Returns:
            True se navegou, False se já estava na página
        """
        current_url = self.page.url
        if "/app/matches" in current_url or "/app/recs" in current_url:
            logger.debug("Já está na página de matches, pulando navegação")
            return False
        
        await self.navigate_to_matches()
        return True
    
    async def navigate_to_match_if_needed(self, match_id: str) -> bool:
        """
        Navega para o chat de um match apenas se não estiver lá.
        
        Args:
            match_id: ID do match no Tinder
            
        Returns:
            True se navegou, False se já estava na página
        """
        current_url = self.page.url
        if f"/messages/{match_id}" in current_url:
            logger.debug(f"Já está na página do chat {match_id}, pulando navegação")
            return False
        
        await self.page.goto(f"https://tinder.com/app/messages/{match_id}")
        await self.page.wait_for_load_state("networkidle")
        return True
    
    async def navigate_to_my_profile(self) -> None:
        """Navega para o meu perfil."""
        # Clicar no ícone de perfil
        try:
            profile_button = await self.page.query_selector(
                '[data-testid="profileLink"], a[href*="/app/profile"]'
            )
            if profile_button:
                await profile_button.click()
                await self.page.wait_for_load_state("networkidle")
                await async_random_delay(0.5, 1)
                log_file_only("Navegou para meu perfil")
        except Exception as e:
            logger.error(f"Erro ao navegar para perfil: {e}")
    
    async def get_page_content(self) -> str:
        """Retorna o HTML da página atual."""
        return await self.page.content()
    
    async def screenshot(self, name: str) -> str:
        """Captura screenshot da página."""
        path = BROWSER_DATA_DIR / f"screenshots/{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path))
        return str(path)
    
    async def execute_script(self, script: str) -> any:
        """Executa JavaScript na página."""
        return await self.page.evaluate(script)


# Instância singleton
_browser: Optional[BrowserController] = None


def get_browser(headless: bool = None) -> BrowserController:
    """Retorna instância singleton do controlador.
    
    Args:
        headless: Se passado, força modo headless/visível.
                  Se None, usa configuração do settings.
    """
    global _browser
    if _browser is None:
        _browser = BrowserController(headless=headless)
    return _browser


def reset_browser():
    """Reseta o singleton do browser (para permitir recriar com modo diferente)."""
    global _browser
    _browser = None
