# Tabela de associacao M2M entre Squads e tipos de tarefa foi removida
# em sqd002 (2026-05-04). O tie-break do `resolve_assistant` agora usa
# `Squad.office_external_id` ↔ `intake.office_id` em vez dessa M2M.
# Mantemos esse modulo vazio pra evitar import errors em codigo legado;
# pode ser removido no proximo cleanup.
