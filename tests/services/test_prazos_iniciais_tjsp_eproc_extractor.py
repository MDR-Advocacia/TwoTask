"""
Testes do `TjspEprocExtractor` (extractor pra Pasta Digital eSAJ com
capa CAPA PROCESSO sintética — formato dos PDFs subidos pelos
estagiários no upload manual).

Cobre os 3 layouts reais observados em produção (descritos no docstring
do `tjsp_eproc.py`) e os bugs que essa branch corrigiu:

  * `template_detector` rotear TJSP (CNJ `.8.26.`) pro extractor
    dedicado em vez do `EprocExtractor` (TJRS/TRF), porque o miolo do
    TJSP separa eventos com `Evento N` em vez de `Documento N`.
  * Valor da Causa quebrado por largura de coluna (rótulo numa linha,
    número na seguinte) sendo capturado mesmo assim.
  * Justiça gratuita aceitar `Requerida` (estado pré-deferimento, comum
    em distribuição) além de `Deferida/Indeferida`.
  * Polo passivo capturar o nome PJ corretamente em 3 layouts onde o
    pdfplumber colou as colunas (cauda PJ misturada com texto da coluna
    esquerda).
  * `integra_json` sempre incluir `texto_cru` — o eproc original deixava
    timeline vazia + nada na integra, e o classificador AJUS recebia
    "timeline=[], documents_relevantes vazios".

Usa texto sintético com a mesma estrutura dos PDFs reais (nomes/CPFs
anonimizados; CNJs com segmento `.8.26.` real pra exercitar o roteador).
"""

from __future__ import annotations

from app.services.prazos_iniciais.pdf_extractor.template_detector import (
    detect_template,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.tjsp_eproc import (
    TjspEprocExtractor,
)
from app.services.prazos_iniciais.pdf_extractor.extractors.eproc import (
    EprocExtractor,
)


# ─── Builders de texto sintético ────────────────────────────────────


def _capa_carimbo(cnj: str) -> str:
    """Página 1 do PDF — carimbo CAPA PROCESSO."""
    return (
        "Tipo documento: CAPA PROCESSO\n"
        "Evento: abertura\n"
        "PROCESSO\n"
        f"Nº {cnj}\n"
    )


def _capa_formal_marcia(cnj: str = "4006094-86.2026.8.26.0032") -> str:
    """
    Layout PDF #1 — cauda PJ colada no fim da linha do polo ativo.
    Estrutura: 'AUTOR (CPF) - Pessoa Física CONT_PJ (CNPJ) - Pessoa
    Jurídica' numa única linha, com nome inicial da PJ na linha
    anterior.
    """
    return (
        f"Nº do processo {cnj}\n"
        "Classe da ação: Procedimento Comum Cível\n"
        "Competência Cível\n"
        "Data de autuação: 30/04/2026 12:08:30\n"
        "Situação MOVIMENTO\n"
        "Órgão Julgador: Juízo Titular I - 4ª Vara Cível da Comarca de Araçatuba\n"
        "Juiz(a): RODRIGO CHAMMES\n"
        "Assuntos\n"
        "Código Descrição Principal\n"
        "061202 Cláusulas Abusivas (Direito Bancário), Cláusulas Abusivas, "
        "DIREITO DO CONSUMIDOR Sim\n"
        "Partes e Representantes\n"
        "AUTOR RÉU\n"
        "BANCO ACME S/A - EM LIQUIDACAO\n"
        "ADRIANA TESTE FIGUEIREDO (000.111.222-33) - Pessoa Física "
        "EXTRAJUDICIAL (00.000.000/0001-00) - Pessoa Jurídica\n"
        "Procurador(es):\n"
        "JAYME SILVA OLIVEIRA SP100100\n"
        "Informações Adicionais\n"
        "Chave Processo: 546427186226 Valor da Causa: R$ Nível de Sigilo do "
        "Sem Sigilo (Nível\n"
        "10.000,00 Processo: 0)\n"
        "Justiça Gratuita: Requerida Opção por Juízo 100% Digital: Sim\n"
    )


def _capa_formal_eunice(cnj: str = "4006142-41.2026.8.26.0001") -> str:
    """
    Layout PDF #2 — cauda PJ colada no fim da linha de advogado, e o
    nome inicial da PJ está em linha solta entre o autor e o advogado.
    """
    return (
        f"Nº do processo {cnj}\n"
        "Classe da ação: Procedimento Comum Cível\n"
        "Competência Cível\n"
        "Data de autuação: 25/02/2026 18:13:33\n"
        "Situação MOVIMENTO\n"
        "Órgão Julgador: Juízo Titular I - 7ª Vara Cível - Regional I - Santana\n"
        "Juiz(a): TESTE JUIZA\n"
        "Assuntos\n"
        "Código Descrição Principal\n"
        "06040102 Empréstimo consignado, Bancários, Contratos de Consumo, "
        "DIREITO DO CONSUMIDOR Sim\n"
        "Partes e Representantes\n"
        "AUTOR RÉU\n"
        "EVA TESTE SILVA (111.222.333-44) - Pessoa Física\n"
        "BANCO ACME S/A - EM LIQUIDACAO\n"
        "ANA TESTE SANTOS MG200200 EXTRAJUDICIAL (00.000.000/0001-00) - "
        "Pessoa Jurídica\n"
        "TIAGO TESTE LIMA SP300300\n"
        "Informações Adicionais\n"
        "Valor da Causa: R$ Nível de Sigilo do Sem Sigilo (Nível\n"
        "15.000,00 Processo: 0) Anexos Eletrônicos: Não há anexos\n"
        "Justiça Gratuita: Requerida\n"
    )


def _capa_formal_erisvaldo(cnj: str = "4006228-39.2025.8.26.0068") -> str:
    """
    Layout PDF #3 — cauda PJ em linha solta (caso 'fácil' que o eproc
    original já cobre, mas o teste valida que o TjspEprocExtractor
    também acerta).
    """
    return (
        f"Nº do processo {cnj}\n"
        "Classe da ação: Procedimento Comum Cível\n"
        "Competência Cível\n"
        "Data de autuação: 13/10/2025 10:10:13\n"
        "Situação BAIXADO\n"
        "Órgão Julgador: Juízo Titular I - 4ª Vara Cível da Comarca de Barueri\n"
        "Juiz(a): TESTE JUIZA BARUERI\n"
        "Assuntos\n"
        "Código Descrição Principal\n"
        "061001 Práticas Abusivas (Direito Civil), Práticas Abusivas, "
        "DIREITO DO CONSUMIDOR Sim\n"
        "Partes e Representantes\n"
        "AUTOR RÉU\n"
        "ELI TESTE FOGACA (222.333.444-55) - Pessoa Física\n"
        "BANCO ACME S/A - EM LIQUIDACAO\n"
        "EXTRAJUDICIAL (00.000.000/0001-00) - Pessoa Jurídica\n"
        "WILSON TESTE ALBUQUERQUE SP400400\n"
        "Informações Adicionais\n"
        "Valor da Causa: R$ Nível de Sigilo do Sem Sigilo (Nível\n"
        "10.216,30 Processo: 0)\n"
        "Justiça Gratuita: Requerida\n"
    )


def _separador_evento(
    n: int,
    descricao: str,
    data: str,
    usuario: str,
    cnj: str,
) -> str:
    """Página de separação típica do TJSP (entre eventos)."""
    return (
        "PÁGINA DE SEPARAÇÃO\n"
        "(Gerada automaticamente pelo sistema.)\n"
        f"Evento {n}\n"
        "Evento:\n"
        f"{descricao}\n"
        "Data:\n"
        f"{data} 10:00:00\n"
        "Usuário:\n"
        f"{usuario}\n"
        "Processo:\n"
        f"{cnj}/SP\n"
        "Sequência Evento:\n"
        f"{n}\n"
    )


def _doc_evento_1_inic(cnj: str) -> str:
    """Conteúdo da petição inicial (Evento 1, INIC1)."""
    return (
        f"Processo {cnj}/SP, Evento 1, INIC1, Página 1\n"
        "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO\n"
        "Conteúdo da petição inicial pra teste — texto bastante longo "
        "que precisa estar disponível na integra pro classificador "
        "AJUS conseguir avaliar o caso.\n"
    )


# ─── 1. Detector roteia TJSP corretamente ───────────────────────────


class TestDetector:
    def test_tjsp_capa_processo_routes_to_tjsp_eproc(self):
        """CNJ TJSP (`.8.26.`) + 'CAPA PROCESSO' deve usar TjspEprocExtractor."""
        cnj = "4006094-86.2026.8.26.0032"
        pages = [_capa_carimbo(cnj), _capa_formal_marcia(cnj)]
        extractor = detect_template(pages)
        assert isinstance(extractor, TjspEprocExtractor)

    def test_tjrs_capa_processo_keeps_eproc_original(self):
        """CNJ TJRS (`.8.21.`) + 'CAPA PROCESSO' continua no EprocExtractor."""
        cnj = "5001234-56.2025.8.21.0001"
        pages = [
            "Tipo documento: CAPA PROCESSO\n"
            "Evento: abertura\n"
            "PROCESSO\n"
            f"Nº {cnj}\n",
            f"Nº do processo {cnj}\n"
            "Classe da ação: Procedimento Comum Cível\n",
        ]
        extractor = detect_template(pages)
        assert isinstance(extractor, EprocExtractor)
        # E não é TjspEprocExtractor (subclasse não-relacionada).
        assert not isinstance(extractor, TjspEprocExtractor)


# ─── 2. Capa: valor, gratuidade, classe, vara ───────────────────────


class TestCapa:
    def test_classe_e_vara(self):
        cnj = "4006094-86.2026.8.26.0032"
        pages = [_capa_carimbo(cnj), _capa_formal_marcia(cnj)]
        res = TjspEprocExtractor().extract(pages)
        assert res.cnj_number == cnj
        assert res.capa_json["tribunal"] == "TJSP"
        assert res.capa_json["classe"] == "Procedimento Comum Cível"
        assert "Araçatuba" in res.capa_json["vara"]
        assert res.capa_json["data_distribuicao"] == "2026-04-30"

    def test_valor_causa_quebrado_por_coluna(self):
        """Valor numa linha, número na seguinte (layout 3-cols TJSP)."""
        cnj = "4006094-86.2026.8.26.0032"
        pages = [_capa_carimbo(cnj), _capa_formal_marcia(cnj)]
        res = TjspEprocExtractor().extract(pages)
        assert res.capa_json["valor_causa"] == 10000.0

        cnj2 = "4006228-39.2025.8.26.0068"
        pages2 = [_capa_carimbo(cnj2), _capa_formal_erisvaldo(cnj2)]
        res2 = TjspEprocExtractor().extract(pages2)
        assert res2.capa_json["valor_causa"] == 10216.30

    def test_justica_gratuita_aceita_requerida(self):
        """`Requerida` (estado pré-deferimento) também conta como pedido ativo."""
        cnj = "4006094-86.2026.8.26.0032"
        pages = [_capa_carimbo(cnj), _capa_formal_marcia(cnj)]
        res = TjspEprocExtractor().extract(pages)
        assert res.capa_json["justica_gratuita"] is True

    def test_assunto_codigos_variados(self):
        """Códigos de assunto do TJSP variam (6 a 10 dígitos)."""
        cnj = "4006094-86.2026.8.26.0032"
        pages = [_capa_carimbo(cnj), _capa_formal_marcia(cnj)]
        res = TjspEprocExtractor().extract(pages)
        assert "Cláusulas Abusivas" in res.capa_json["assunto"]
        assert "(061202)" in res.capa_json["assunto"]


# ─── 3. Polo passivo nos 3 layouts ──────────────────────────────────


class TestPoloPassivo:
    """
    Os 3 layouts reais observados em produção. O bug original era que
    o polo passivo vinha vazio ou com `Extrajudicial` no lugar do nome
    completo, porque pdfplumber lê o layout 2-cols sem separar as
    colunas e o regex naïve do eproc não conseguia recompor.
    """

    def test_layout_1_cauda_colada_no_polo_ativo(self):
        """PDF #1: '<autor> Pessoa Física EXTRAJUDICIAL (CNPJ) - Pessoa Jurídica'."""
        cnj = "4006094-86.2026.8.26.0032"
        pages = [_capa_carimbo(cnj), _capa_formal_marcia(cnj)]
        res = TjspEprocExtractor().extract(pages)
        passivo = res.capa_json["polo_passivo"]
        assert len(passivo) == 1, passivo
        assert "BANCO ACME" in passivo[0]["nome"].upper()
        assert "EXTRAJUDICIAL" in passivo[0]["nome"].upper()
        assert passivo[0]["documento"] == "00.000.000/0001-00"

    def test_layout_2_cauda_colada_em_advogado(self):
        """PDF #2: '<advogado> <OAB> EXTRAJUDICIAL (CNPJ) - Pessoa Jurídica'."""
        cnj = "4006142-41.2026.8.26.0001"
        pages = [_capa_carimbo(cnj), _capa_formal_eunice(cnj)]
        res = TjspEprocExtractor().extract(pages)
        passivo = res.capa_json["polo_passivo"]
        assert len(passivo) == 1, passivo
        assert "BANCO ACME" in passivo[0]["nome"].upper()
        assert "EXTRAJUDICIAL" in passivo[0]["nome"].upper()
        # E os advogados foram pro polo ativo (Eunice — autora).
        ativo = res.capa_json["polo_ativo"]
        assert len(ativo) == 1
        nomes_advs = " ".join(ativo[0]["advogados"]).upper()
        assert "ANA TESTE SANTOS" in nomes_advs
        assert "TIAGO TESTE LIMA" in nomes_advs

    def test_layout_3_cauda_em_linha_solta(self):
        """PDF #3: 'EXTRAJUDICIAL (CNPJ) - Pessoa Jurídica' isolada."""
        cnj = "4006228-39.2025.8.26.0068"
        pages = [_capa_carimbo(cnj), _capa_formal_erisvaldo(cnj)]
        res = TjspEprocExtractor().extract(pages)
        passivo = res.capa_json["polo_passivo"]
        assert len(passivo) == 1, passivo
        assert "BANCO ACME" in passivo[0]["nome"].upper()
        assert "EXTRAJUDICIAL" in passivo[0]["nome"].upper()
        # Polo ativo correto.
        ativo = res.capa_json["polo_ativo"]
        assert len(ativo) == 1
        assert "ELI TESTE FOGACA" in ativo[0]["nome"].upper()
        assert ativo[0]["documento"] == "222.333.444-55"


# ─── 4. Timeline e integra (causa raiz do bug original) ─────────────


class TestTimelineEIntegra:
    def test_timeline_segmenta_por_evento_n(self):
        """No TJSP o separador é 'Evento N' (não 'Documento N')."""
        cnj = "4006094-86.2026.8.26.0032"
        pages = [
            _capa_carimbo(cnj),
            _capa_formal_marcia(cnj),
            _separador_evento(
                1, "DISTRIBUIDO POR SORTEIO", "30/04/2026",
                "SP100100 - JAYME SILVA - ADVOGADO", cnj,
            ),
            _doc_evento_1_inic(cnj),
            _separador_evento(
                2, "JUNTADA DE PETICAO", "01/05/2026",
                "SP100100 - JAYME SILVA - ADVOGADO", cnj,
            ),
            "Conteúdo do evento 2.\n",
        ]
        res = TjspEprocExtractor().extract(pages)
        timeline = res.integra_json.get("timeline") or []
        assert len(timeline) == 2
        assert timeline[0]["document_id"] == 1
        assert "DISTRIBUIDO" in timeline[0]["label"].upper()
        assert timeline[0]["protocol_date"] == "2026-04-30"
        assert timeline[1]["document_id"] == 2

    def test_integra_sempre_tem_texto_cru(self):
        """
        Bug original: timeline=[] e integra ficava `{"timeline": []}` —
        sem texto da petição inicial. Regressão crítica pro AJUS.
        Garantia: texto_cru SEMPRE presente, mesmo sem eventos.
        """
        cnj = "4006094-86.2026.8.26.0032"
        pages = [
            _capa_carimbo(cnj),
            _capa_formal_marcia(cnj),
            # Sem separadores de evento — só texto cru.
            "Texto bastante longo da petição inicial sem separador.\n",
        ]
        res = TjspEprocExtractor().extract(pages)
        integra = res.integra_json or {}
        # Sem eventos detectados.
        assert not integra.get("timeline")
        # Mas texto_cru SEMPRE preenchido com o conteúdo concatenado.
        assert integra.get("texto_cru")
        assert "petição inicial" in integra["texto_cru"]

    def test_integra_tem_texto_cru_mesmo_com_timeline(self):
        """texto_cru não some quando a timeline foi preenchida."""
        cnj = "4006094-86.2026.8.26.0032"
        pages = [
            _capa_carimbo(cnj),
            _capa_formal_marcia(cnj),
            _separador_evento(
                1, "DISTRIBUIDO POR SORTEIO", "30/04/2026",
                "SP100100 - TESTE", cnj,
            ),
            _doc_evento_1_inic(cnj),
        ]
        res = TjspEprocExtractor().extract(pages)
        integra = res.integra_json or {}
        assert integra.get("timeline")
        assert integra.get("texto_cru")
        assert "EXCELENTÍSSIMO" in integra["texto_cru"]


# ─── 5. Confidence ───────────────────────────────────────────────────


class TestConfidence:
    def test_capa_completa_com_timeline_eh_high(self):
        cnj = "4006094-86.2026.8.26.0032"
        pages = [
            _capa_carimbo(cnj),
            _capa_formal_marcia(cnj),
            _separador_evento(
                1, "DISTRIBUIDO POR SORTEIO", "30/04/2026",
                "SP100100 - TESTE", cnj,
            ),
            _doc_evento_1_inic(cnj),
        ]
        res = TjspEprocExtractor().extract(pages)
        assert res.confidence == "high"

    def test_capa_parcial_sem_timeline_eh_partial(self):
        cnj = "4006094-86.2026.8.26.0032"
        # Capa mínima — só CNJ + classe (sem timeline, sem partes).
        pages = [
            _capa_carimbo(cnj),
            f"Nº do processo {cnj}\nClasse da ação: Procedimento Comum Cível\n",
        ]
        res = TjspEprocExtractor().extract(pages)
        assert res.confidence in ("partial", "low")
