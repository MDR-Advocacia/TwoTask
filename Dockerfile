# Conteúdo ATUALIZADO e ENXUTO para: Dockerfile

# Estágio 1: Imagem base do Python
# Usamos a imagem slim do Python 3.10 para manter o tamanho final pequeno.
FROM python:3.10-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código da aplicação para dentro do container
COPY . .

# (As instruções de build do frontend foram removidas daqui, pois agora são independentes)