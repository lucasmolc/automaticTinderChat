# Imagem base oficial do Playwright para Python — já traz os navegadores e libs.
# A tag acompanha a versão do playwright fixada em requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# Instala dependências primeiro (melhor uso de cache de camadas)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia o restante do projeto
COPY . .

# SQLite por padrão grava em /app/data (use um volume para persistir)
ENV DATABASE_URL=""
ENV BROWSER_HEADLESS=true

EXPOSE 5000

# Sobe a interface web. A automação completa exige sessão de navegador logada
# (veja docs/CONFIGURATION.md); em container, prefira o dashboard.
CMD ["python", "run_web.py"]
