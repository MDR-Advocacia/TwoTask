"""Ingestão automática de petições iniciais por pasta de drive (SharePoint/
OneDrive via Microsoft Graph).

Fluxo (poll incremental, sem webhook):
  APScheduler → Graph /delta da pasta → pra cada PDF novo:
    - lê o CNJ do NOME do arquivo (cnj_filename.extract_cnj_digits)
    - baixa os bytes via Graph
    - joga no IntakeService.create_intake (USER_UPLOAD)
  → persiste o delta token + marca o item como processado.

O parser de nome (cnj_filename) é puro e testável sem credencial Graph.
"""
