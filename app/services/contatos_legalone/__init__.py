"""Modulo Atualizacao de Contatos LegalOne.

Enriquece contatos ja' existentes no Legal One (achados pelo CPF/CNPJ) com
telefones, e-mail e endereco vindos de um CSV. Ver ESTUDO-API-CONTATOS-LEGALONE.md.

Submodulos:
- l1_contacts: wrapper fino sobre LegalOneApiClient (find, GET/POST nav
  properties phones/emails/addresses, resolve cityId).
- csv_parser: parseia o CSV Dossie -> linhas normalizadas.
- batch_service: orquestra criacao/preview/serializacao de lotes.
- enrich_worker: worker periodico que processa os itens (com modo dry-run).
"""
