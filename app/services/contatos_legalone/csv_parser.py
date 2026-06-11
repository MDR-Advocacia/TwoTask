"""Parser do CSV Dossie (CPF/CNPJ + telefones/e-mail/endereco).

Le' o CSV cru e devolve linhas normalizadas prontas pro worker. Regras
empiricas do arquivo da casa (ver ESTUDO-API-CONTATOS-LEGALONE.md):

- Encoding: tenta utf-8-sig, cai pra latin-1 (CSVs BR costumam vir cp1252).
- Delimitador: detecta ';' (comum no BR) ou ','.
- Vazio: o literal "NULL" (e a string vazia) contam como ausente.
- Documento: 11 digitos -> CPF; 14 -> CNPJ; outro -> linha invalida.
- Telefone: concatena DDD + TELEFONE (idem 2/3). Formata com mascara
  "(92) 99202-2665" por padrao (settings.contatos_legalone_phone_keep_mask).
- Endereco: so' monta se houver LOGRADOURO + CIDADE + UF (minimo pra tentar
  resolver cityId no worker). CEP/numero/bairro/complemento entram se vierem.

Saida por linha valida (payload_json do item):
  { doc_number, doc_digits, doc_kind, nome_abreviado,
    phones: [str...], email: str|None, address: {..raw..}|None }
"""

from __future__ import annotations

import csv
import io
import unicodedata
from typing import Any, Optional

from app.core.config import settings


# ─── Normalizacao de cabecalho ───────────────────────────────────────────


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm_header(h: str) -> str:
    """Cabecalho -> chave canonica (upper, sem acento, espacos->underscore)."""
    base = _strip_accents(str(h or "")).strip().upper()
    base = base.replace("-", "_").replace(".", "_")
    base = "_".join(base.split())  # colapsa espacos -> underscore unico
    while "__" in base:
        base = base.replace("__", "_")
    return base


def _clean(value: Any) -> str:
    """Strip + trata o literal 'NULL' (e vazio) como ausente."""
    s = str(value if value is not None else "").strip()
    if not s or s.upper() == "NULL":
        return ""
    return s


def _digits(value: Any) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


# ─── Telefone ─────────────────────────────────────────────────────────────


def format_phone(ddd: str, telefone: str, keep_mask: bool) -> Optional[str]:
    """Concatena DDD+TELEFONE -> numero formatado (ou None se vazio).

    Se TELEFONE ja' vier com >=10 digitos e sem DDD separado, usa como esta'.
    """
    ddd_d = _digits(ddd)
    tel_d = _digits(telefone)
    if not tel_d:
        return None

    if len(tel_d) >= 10 and not ddd_d:
        full = tel_d
    else:
        full = ddd_d + tel_d

    if not full:
        return None
    if not keep_mask:
        return full

    # Mascara "(DD) NNNNN-NNNN" / "(DD) NNNN-NNNN".
    if len(full) >= 3:
        area = full[:2]
        rest = full[2:]
        if len(rest) == 9:
            return f"({area}) {rest[:5]}-{rest[5:]}"
        if len(rest) == 8:
            return f"({area}) {rest[:4]}-{rest[4:]}"
    return full


# ─── Documento ──────────────────────────────────────────────────────────


def classify_doc(raw: str) -> tuple[Optional[str], str, str]:
    """(doc_kind|None, doc_number_canonico, doc_digits). None = invalido.

    O L1 guarda identificationNumber COM mascara e a busca por digitos puros
    retorna 0 (confirmado pra CPF no MD e pra CNPJ ao vivo). Por isso
    normalizamos pra mascara canonica — CPF 'NNN.NNN.NNN-NN', CNPJ
    'NN.NNN.NNN/NNNN-NN' — independente de como o CSV mandou (o Dossie vem
    com CPF mascarado mas CNPJ sem mascara).
    """
    raw_clean = _clean(raw)
    d = _digits(raw_clean)
    if len(d) == 11:
        return "CPF", f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}", d
    if len(d) == 14:
        return "CNPJ", f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}", d
    return None, raw_clean, d


# ─── Parse principal ──────────────────────────────────────────────────────


def _decode(file_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return file_bytes.decode("latin-1", errors="replace")


def _sniff_reader(text: str) -> csv.DictReader:
    sample = text[:4096]
    delimiter = ";"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        # Heuristica: mais ';' que ',' na 1a linha -> ';'.
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    return csv.DictReader(io.StringIO(text), delimiter=delimiter)


def parse_csv(file_bytes: bytes) -> dict[str, Any]:
    """Parseia o CSV -> {rows, summary, headers, invalid}.

    `rows`: payloads validos (1 por linha com documento valido).
    `invalid`: [{row_number, reason, raw_doc}] das linhas descartadas.
    """
    text = _decode(file_bytes)
    reader = _sniff_reader(text)
    raw_headers = reader.fieldnames or []
    header_map = {_norm_header(h): h for h in raw_headers}

    def col(row: dict, *names: str) -> str:
        for n in names:
            orig = header_map.get(n)
            if orig is not None:
                return _clean(row.get(orig))
        return ""

    keep_mask = settings.contatos_legalone_phone_keep_mask

    rows: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen_digits: set[str] = set()
    duplicates = 0
    total = 0

    def add_issue(row_number: int, column: str, value: Any, error: str, severity: str):
        # severity: "error" bloqueia o upload | "warning" so' avisa (dado e'
        # ignorado/tratado no processamento, nao impede o envio).
        issues.append({
            "row_number": row_number,
            "column": column,
            "value": str(value if value is not None else "")[:80],
            "error": error,
            "severity": severity,
        })

    # Cabecalho: sem coluna de documento, o arquivo inteiro e' inutil.
    if not any(k in header_map for k in ("CPF_CNPJ", "CPF", "CNPJ")):
        add_issue(
            0, "CPF_CNPJ", ", ".join(raw_headers) or "(vazio)",
            "Coluna CPF_CNPJ nao encontrada no cabecalho do arquivo.", "error",
        )

    phone_cols = (("DDD", "TELEFONE"), ("DDD2", "TELEFONE2"), ("DDD3", "TELEFONE3"))

    for idx, raw in enumerate(reader, start=1):
        # Linha em branco -> ignora silenciosamente (nao conta, nao valida).
        if not any(str(v if v is not None else "").strip() for v in raw.values()):
            continue
        raw_doc = col(raw, "CPF_CNPJ", "CPF", "CNPJ")
        # Linha de exemplo/comentario: CPF_CNPJ comecando com '#' e' ignorada
        # (permite deixar 1 linha-modelo preenchida no template sem ser lida).
        if raw_doc.lstrip().startswith("#"):
            continue
        total += 1
        kind, doc_number, doc_digits = classify_doc(raw_doc)
        if kind is None:
            n = len(_digits(raw_doc))
            reason = (
                "CPF/CNPJ vazio."
                if not raw_doc
                else f"CPF/CNPJ com {n} digito(s) — esperado 11 (CPF) ou 14 (CNPJ)."
            )
            invalid.append({"row_number": idx, "reason": reason, "raw_doc": doc_number})
            add_issue(idx, "CPF_CNPJ", raw_doc, reason, "error")
            continue

        # Telefones (ate' 3) + validacao de formato (campo free-text -> so' avisa).
        phones: list[str] = []
        for ddd_col, tel_col in phone_cols:
            tel_raw = col(raw, tel_col)
            num = format_phone(col(raw, ddd_col), tel_raw, keep_mask)
            if num and num not in phones:
                phones.append(num)
            if tel_raw:
                if num is None:
                    add_issue(idx, tel_col, tel_raw,
                              "Telefone sem digitos validos — sera ignorado.", "warning")
                else:
                    cd = _digits(num)
                    if len(cd) < 10 or len(cd) > 11:
                        add_issue(idx, tel_col, tel_raw,
                                  f"Telefone com {len(cd)} digito(s) — esperado 10 ou 11 com DDD.",
                                  "warning")

        # E-mail.
        email_raw = col(raw, "EMAIL")
        email = email_raw or None
        if email_raw and ("@" not in email_raw or "." not in email_raw.rsplit("@", 1)[-1]):
            add_issue(idx, "EMAIL", email_raw,
                      "E-mail fora do padrao — sera ignorado.", "warning")
            email = None

        # Endereco.
        logradouro = col(raw, "LOGRADOURO", "ENDERECO")
        cidade = col(raw, "CIDADE", "MUNICIPIO")
        uf = col(raw, "UF", "ESTADO")
        cep_raw = col(raw, "CEP")
        if uf and len(uf.strip()) != 2:
            add_issue(idx, "UF", uf,
                      "UF deve ter 2 letras (ex.: SP) — endereco pode nao resolver.", "warning")
        if cep_raw and len(_digits(cep_raw)) != 8:
            add_issue(idx, "CEP", cep_raw,
                      f"CEP com {len(_digits(cep_raw))} digito(s) — esperado 8.", "warning")
        if logradouro and (not cidade or not uf):
            add_issue(idx, "LOGRADOURO", logradouro,
                      "Endereco sem CIDADE/UF — sera ignorado.", "warning")

        address = None
        if logradouro and cidade and uf:
            address = {
                "logradouro": logradouro,
                "numero": col(raw, "NUMERO") or None,
                "complemento": col(raw, "COMPLEMENTO") or None,
                "bairro": col(raw, "BAIRRO") or None,
                "cidade": cidade,
                "uf": uf,
                "cep": _digits(cep_raw) or None,
            }

        if doc_digits in seen_digits:
            duplicates += 1
        else:
            seen_digits.add(doc_digits)

        rows.append({
            "row_number": idx,
            "doc_number": doc_number,
            "doc_digits": doc_digits,
            "doc_kind": kind,
            "name": col(raw, "NOME", "NOME_COMPLETO", "RAZAO_SOCIAL") or None,
            "nome_abreviado": col(raw, "NOME_ABREVIADO") or None,
            "phones": phones,
            "email": email,
            "address": address,
        })

    erros = sum(1 for i in issues if i["severity"] == "error")
    alertas = sum(1 for i in issues if i["severity"] == "warning")
    summary = {
        "total_linhas": total,
        "validas": len(rows),
        "invalidas": len(invalid),
        "duplicadas_no_arquivo": duplicates,
        "cpf": sum(1 for r in rows if r["doc_kind"] == "CPF"),
        "cnpj": sum(1 for r in rows if r["doc_kind"] == "CNPJ"),
        "com_telefone": sum(1 for r in rows if r["phones"]),
        "com_email": sum(1 for r in rows if r["email"]),
        "com_endereco": sum(1 for r in rows if r["address"]),
        "com_nome": sum(1 for r in rows if r["name"]),
        "total_telefones": sum(len(r["phones"]) for r in rows),
        "erros": erros,
        "alertas": alertas,
    }
    return {
        "rows": rows,
        "summary": summary,
        "headers": list(raw_headers),
        "invalid": invalid,
        "issues": issues,
        "has_blocking": erros > 0,
    }
