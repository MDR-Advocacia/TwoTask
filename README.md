# TwoTask - Orquestrador de Tarefas para Legal One

**TwoTask** é uma aplicação SaaS que visa centralizar o serviço de orquestração de agendamentos automáticos via API para o CRM LegalOne. O sistema reduz o trabalho manual de agendamentos e permite, a partir de diversas fontes de dados, promover agilidade no processo de agendamento, seja individualmente ou em lote.

---

## 📋 Índice

- [Principais Funcionalidades](#-principais-funcionalidades)
- [🛠️ Stack de Tecnologias](#-stack-de-tecnologias)
- [🚀 Como Começar](#-como-começar)
  - [Pré-requisitos](#pré-requisitos)
  - [Instalação e Execução](#instalação-e-execução)
- [⚙️ Variáveis de Ambiente](#️-variáveis-de-ambiente)
- [📁 Estrutura do Projeto](#-estrutura-do-projeto)
- [🔌 Documentação da API](#-documentação-da-api)
  - [Autenticação](#autenticação)
  - [Endpoint Principal de Lote](#endpoint-principal-de-lote)

---

## ✨ Principais Funcionalidades

* **Painel de Administração:** Gerenciamento centralizado de Setores, Squads e Usuários, permitindo a configuração de equipes e suas permissões.
* **Agendamento em Lote via API:** Endpoints robustos para integrações externas (fontes `Onesid` e `Onerequest`) para criação de tarefas em massa de forma programática.
* **Agendamento em Lote por Planilha:** Interface de usuário intuitiva para upload de arquivos `.xlsx`, facilitando agendamentos em grande escala para usuários não técnicos.
* **Dashboard de Acompanhamento:** Visualização em tempo real do status de todas as execuções de lote, com detalhes de sucesso e falha para cada item processado.
* **Sistema de Autenticação:** Acesso seguro à plataforma com tokens JWT, garantindo que apenas usuários autorizados acessem a interface e os endpoints.
* **Arquitetura Baseada em Estratégias:** O backend é construído com o Padrão de Projeto Strategy, permitindo que novas fontes de criação de tarefas (como `Onesid`, `Planilha`, `Onerequest`) sejam adicionadas de forma limpa e modular, sem impactar a lógica existente.

---

## 🛠️ Stack de Tecnologias

O projeto é uma aplicação full-stack moderna, containerizada com Docker.

### **Backend**

* **Linguagem:** Python 3.10
* **Framework:** FastAPI
* **Banco de Dados:** PostgreSQL
* **ORM:** SQLAlchemy com Alembic para migrações
* **Validação de Dados:** Pydantic
* **Autenticação:** JWT (JSON Web Tokens)
* **Servidor:** Uvicorn

### **Frontend**

* **Framework:** React 18
* **Linguagem:** TypeScript
* **Build Tool:** Vite
* **Estilização:** Tailwind CSS
* **Componentes UI:** shadcn/ui
* **Roteamento:** React Router

---

## 🚀 Como Começar

Siga os passos abaixo para configurar e executar o projeto em seu ambiente local.

### Pré-requisitos

* [Docker](https://www.docker.com/get-started)
* [Docker Compose](https://docs.docker.com/compose/install/)

### Instalação e Execução

1.  **Clone o repositório:**
    ```bash
    git clone <URL_DO_SEU_REPOSITORIO>
    cd onetask
    ```

2.  **Configure as Variáveis de Ambiente:**
    Crie um arquivo `.env` na raiz do projeto, copiando o exemplo de `.env.example` (que você deve criar). Preencha com as credenciais necessárias. Veja a seção [Variáveis de Ambiente](#️-variáveis-de-ambiente) para mais detalhes.

3.  **Suba os containers com Docker Compose:**
    O comando a seguir irá construir as imagens do backend e do frontend, e iniciar todos os serviços (API, UI e Banco de Dados).

    ```bash
    docker-compose up --build
    ```

4.  **Acesse a aplicação:**
    * **Frontend:** Abra seu navegador e acesse `http://localhost:8080`
    * **Backend (Documentação da API):** Acesse `http://localhost:8000/docs`

5.  **(Opcional) Crie o primeiro usuário administrador:**
    Se for a primeira vez executando o projeto, pode ser necessário criar um usuário inicial para acessar o sistema. Execute o script `create_user.py` dentro do container da API.

    ```bash
    docker-compose exec api python create_user.py "Nome do Admin" "admin@email.com" "senha_forte" --is_admin
    ```
---

## ⚙️ Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto com as seguintes variáveis:

```env
# Configuração do Banco de Dados
DATABASE_URL=postgresql://user:password@db:5432/dbname

# Configurações da API Legal One
LEGAL_ONE_API_URL=[https://api.legalone.com.br](https://api.legalone.com.br)
LEGAL_ONE_CLIENT_ID=seu_client_id
LEGAL_ONE_CLIENT_SECRET=seu_client_secret
LEGAL_ONE_USERNAME=seu_usuario
LEGAL_ONE_PASSWORD=sua_senha

# Configurações de Autenticação JWT
SECRET_KEY=sua_chave_secreta_muito_longa_e_segura
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60