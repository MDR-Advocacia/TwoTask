
-----

# OneTask - Serviço de Integração Legal One

**Versão:** 1.2.0
**Status:** Em Desenvolvimento Ativo
**Estimativa de Horas Trabalhadas:** 12 horas

## 1\. Descrição do Projeto

O **OneTask** é um serviço de integração e automação projetado para otimizar a criação e o gerenciamento de tarefas no **Thomson Reuters Legal One**.

A aplicação funciona como uma ponte inteligente entre eventos externos (como novas publicações) e o Legal One, aplicando regras de negócio internas para atribuir tarefas às equipes (SQUADS) corretas. Além da automação, o projeto inclui um painel de controle web para visualização de dados e interação manual.

## 2\. Funcionalidades Implementadas

  * **API de Automação:** Endpoint principal (`/api/v1/trigger/task`) que recebe um gatilho (ex: número de processo) e orquestra todo o fluxo de criação de tarefas.
  * **Integração com API de SQUADS:** Conecta-se a uma API interna (Supabase) para buscar a estrutura de SQUADS da empresa, mantendo os dados em cache para otimizar a performance.
  * **Lógica de Negócio para Atribuição:** O `OrchestrationService` analisa os dados do processo no Legal One (como o "Responsável Principal") para identificar a SQUAD correspondente e atribuir a tarefa a um membro, de acordo com as regras de negócio.
  * **Painel de Controle Web (`/dashboard`):**
      * **Visualização de SQUADS:** Exibe em tempo real a composição de todas as equipes, líderes e membros.
      * **Criação Manual de Tarefas:** Permite que um usuário insira um ou mais números de processo em um formulário para disparar o fluxo de criação de tarefas manualmente.

## 3\. Como Configurar e Rodar o Projeto

### Pré-requisitos

  * Python 3.10+
  * Pip (gerenciador de pacotes Python)
  * Acesso às credenciais da API do Legal One e da API de SQUADS.

### Passos para Instalação

1.  **Clone o repositório:**

    ```bash
    git clone <url-do-seu-repositorio>
    cd onetask
    ```

2.  **Crie e ative um ambiente virtual (Recomendado):**

    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Instale as dependências:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure as Variáveis de Ambiente:**
    Crie um arquivo chamado `.env` na raiz do projeto (no mesmo nível do `main.py`) e preencha com as suas credenciais. Use o exemplo abaixo como base:

    ```env
    # Credenciais da API do Thomson Reuters Legal One
    LEGAL_ONE_BASE_URL="https://api.legalone.thomsonreuters.com/v1"
    LEGAL_ONE_CLIENT_ID="SEU_CLIENT_ID_AQUI"
    LEGAL_ONE_CLIENT_SECRET="SEU_CLIENT_SECRET_AQUI"

    # URL e Chave da API de Squads (Supabase)
    SQUADS_API_URL="URL_DA_SUA_API_DE_SQUADS"
    SUPABASE_ANON_KEY="SUA_CHAVE_ANON_DO_SUPABASE_AQUI"
    ```

### Como Executar

1.  Com o ambiente virtual ativado e o arquivo `.env` configurado, inicie o servidor com o Uvicorn:

    ```bash
    uvicorn main:app --reload
    ```

2.  A aplicação estará disponível em `http://127.0.0.1:8000`.

3.  Acesse o painel de controle em `http://127.0.0.1:8000/dashboard`.

## 4\. Endpoints Principais

  * **`GET /dashboard`**: Renderiza o painel de controle web.
  * **`POST /api/v1/trigger/task`**: Endpoint principal para iniciar a criação de uma tarefa.
  * **`GET /api/v1/squads`**: Fornece os dados das squads para o frontend do painel.
  * **`POST /api/v1/admin/refresh-squads`**: Força a atualização do cache de squads a partir da API externa.