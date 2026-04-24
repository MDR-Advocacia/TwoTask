# Novidades do Flow — 24 de abril de 2026

Uma leva de melhorias no módulo de **Publicações** focadas em três dores
do dia a dia: achar um processo específico, evitar agendamento duplicado
no Legal One, e não ter que rolar uma lista infinita pra escolher subtipo
de tarefa.

---

## O que ficou mais rápido

### Agora dá pra buscar um processo direto no filtro

No topo da tela "Processos com Publicações" tem um campo novo de busca
de processo com o ícone de lupa. Você pode digitar:

- O CNJ completo com máscara: `0000161-07.2026.8.05.0001`
- Só os números: `16107`
- Um fragmento qualquer do CNJ

O sistema compara só os dígitos — esquece a máscara, sempre acha.

Aplica ao dar Enter ou ao clicar fora do campo. O botão "Limpar filtros"
limpa também essa busca.

### Escolher subtipo de tarefa virou pesquisa (900 itens no catálogo)

Até ontem, quando você abria o modal de Confirmar Agendamento e ia no
campo "Subtipo de tarefa", era uma lista com os ~900 subtipos do Legal
One pra rolar. Praticamente inviável achar algo sem scroll.

Agora é uma busca inteligente. Clicando no campo:

- Abre uma caixinha com um input "Buscar por tipo ou subtipo..."
- Você digita parte do nome e a lista filtra na hora
- A busca casa tanto no **subtipo** quanto no **tipo pai** — digite "BB"
  e aparecem os subtipos sob "BB Réu", "BB Ativo" etc.
- Não se importa com acento — "publicacao" acha "Publicação"
- O campo mostra "Tipo · Subtipo" pra você confirmar o que selecionou

### Dropdown de escritório não quebra mais os nomes longos

Quem filtrava por escritório sabe: "MDR Advocacia / Área operacional /
Administrativo / Ativos" virava uma torre de texto espremida. Agora o
dropdown respeita o nome completo numa linha legível, e se passar o mouse
em cima ainda tem tooltip com o caminho inteiro.

---

## Menos erro, menos retrabalho

### O sistema avisa se a tarefa já existe no Legal One antes de agendar

Essa é a grande novidade do dia. Ao abrir o modal de Confirmar Agendamento
em um processo, o Flow consulta o Legal One automaticamente pra verificar
se **já existe uma tarefa aberta do mesmo subtipo naquele processo**.

Como funciona:

1. Ao abrir o modal, aparece um overlay "Verificando tarefas pendentes no
   Legal One..." — dura mais ou menos 1 segundo. Enquanto isso o botão
   Enviar fica bloqueado, pra garantir que você nunca agenda antes da
   verificação terminar.
2. Se o sistema achar uma tarefa pendente com o mesmo subtipo, aparece
   um **aviso vermelho bem destacado** dentro da tarefa afetada:
   - Mostra quantas tarefas existem
   - Lista cada uma com o status (Pendente, Em Andamento ou Aguardando),
     o número da tarefa e um trecho da descrição
   - Tem um botão **"Ver no L1"** que abre a tarefa direto no painel web
     do Legal One em outra aba
   - Tem um botão **"Remover tarefa"** no rodapé pra tirar esse bloco
     do envio
3. Se você decidir agendar mesmo assim (às vezes é legítimo — ex: "Manifestação"
   antiga ainda sendo tratada e outra nova pra criar), o sistema pede
   uma confirmação extra e deixa passar.

**O que conta como "tarefa existente":** status Pendente, Em Andamento e
Aguardando. Se a tarefa antiga estiver Concluída ou Cancelada, o sistema
deixa agendar normalmente — não é duplicata pra fins práticos.

**Pra processos sem vínculo (publicação avulsa):** a verificação é pulada
porque o Legal One não consegue indexar a busca sem o número do processo.

### Trilha de quem agendou cada publicação

Agora toda vez que alguém confirma um agendamento, o sistema guarda:

- Quem agendou (usuário + e-mail)
- Quando agendou (data e hora)

Na grid de Processos com Publicações, abaixo do badge `AGENDADO` aparece
a linha `por <Nome>`. Passando o mouse em cima, o tooltip mostra a
informação completa — nome, e-mail e momento exato.

Importante: publicações que já estavam com status AGENDADO antes desta
atualização não têm esse rastro (era informação que não existia no banco).
Vão aparecer sem a linha "por".

---

## O que corrigimos

### Agendar tarefa avulsa voltou a funcionar

O modal de Tarefa Avulsa estava falhando em silêncio ao enviar pro Legal
One — a API recusava o payload porque faltavam três campos obrigatórios
(status, escritório de origem e data de publicação) que o formulário
nem pede pra você preencher. O Flow agora completa esses campos
automaticamente antes de enviar.

Resultado: a tarefa passa a ser criada, o registro vira AGENDADO, e a
trilha "por <Nome>" também começa a funcionar (sem a correção de agendar,
a trilha nunca rodava).

### Verificação de duplicata estava retornando "vazio" em silêncio

Na primeira versão da checagem de duplicatas, o sistema estava pedindo
ao Legal One mais resultados por página do que ele aceita, a API
devolvia erro, e a gente engolia achando que "não tinha duplicata". Foi
ajustado pra respeitar o limite da API e a verificação passou a retornar
corretamente.

---

## Pra equipe técnica (detalhes)

Branch: `feat/prazos-iniciais`. Commits na ordem:

1. `5a5e9f4` — busca por CNJ + autoria AGENDADO + fix MultiSelect
2. Fix `status` + `originOfficeId` nos defaults do payload L1
3. Fix `publishDate` nos defaults do payload L1
4. Combobox searchable pro Subtipo de Tarefa
5. Onda 1 do check-duplicates (backend + frontend)
6. Fix `top=30` no endpoint `/Tasks` do L1
7. Overlay bloqueante + banner vermelho no modal

Migration nova: `pub002_add_scheduled_by_record.py` — adiciona
`scheduled_by_user_id`, `scheduled_by_email`, `scheduled_by_name`,
`scheduled_at` em `publicacao_registros` (FK com ON DELETE SET NULL +
índice leve).

Endpoint novo: `POST /v1/publications/groups/{lawsuit_id}/check-duplicates`.

Status IDs do L1 considerados "em aberto" pra bloquear duplicata:
`(0, 1, 2)` = Pendente, Em Andamento, Aguardando. Ajustar na constante
`L1_BLOCKING_STATUS_IDS` do service se no tenant tiver outros.

Cache interno de duplicatas: TTL 15s por `(lawsuit_id, subtypes)`.

---

## Próximos passos sugeridos

- **Onda 2 do check-duplicates:** marcar "possível duplicata" já no card
  da grid, antes mesmo de abrir o modal — roda em background conforme
  as publicações chegam classificadas.
- Admin UI pra gerenciar tipos de pedido (Prazos Iniciais).
- Dashboard de contingência agregando valores aprovisionados por processo.
- Edição inline de pedidos na tela HITL de Prazos Iniciais.
