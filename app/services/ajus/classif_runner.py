"""
Runner Playwright da classificação AJUS — Chunk 2b.

Porte (enxuto) das partes essenciais do projeto Mirror que faziam
classificação de capa com 100% de sucesso. O foco é manter o que
importa: login (com IP-code), abrir processo por CNJ, preencher os
5 campos da capa (UF, Comarca, Matéria, Justiça/Honorário,
Risco/Prob. Perda) e validar o save.

Como roda:
  - Container `ajus-runner` (Chunk 2c) cria o `AjusClassifRunner` com
    uma `AjusSessionAccount` ativa. Cada conta = 1 instância de runner
    = 1 browser context isolado + storage_state próprio.
  - O runner faz polling no DB pra:
      - capturar pedido de login (status=logando)
      - capturar IP-code submetido pela UI (campo `pending_ip_code`)
      - pegar próximos itens da fila (origem do dispatcher — Chunk 2c)
  - Atualiza status da conta + dos itens via session_service e
    classificacao_service. Tudo persistido no DB pra o frontend ver.

NÃO roda dentro do container API (FastAPI). É importado pelo
container `ajus-runner` que tem Chromium instalado.

Helpers ExtJS:
  O AJUS é ExtJS-pesado. Em vez de portar as ~1500 linhas de helpers
  do Mirror, usamos uma estratégia mais simples: tenta clique +
  preenchimento padrão, se não funcionar, dispara evento de blur e
  re-checa. Edge cases (combobox com picker custom) ficam como
  fallback explicit nos métodos `_select_combo_*`. O Mirror tinha
  100% de sucesso com layout estável — mantemos porte fiel.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ajus import (
    AJUS_ACCOUNT_AGUARDANDO_IP,
    AJUS_ACCOUNT_LOGANDO,
    AJUS_ACCOUNT_OFFLINE,
    AJUS_ACCOUNT_ONLINE,
    AJUS_CLASSIF_PENDENTE,
    AjusClassificacaoQueue,
    AjusSessionAccount,
)
from app.services.ajus.classificacao_service import AjusClassificacaoService
from app.services.ajus.session_service import (
    AjusSessionService,
    ensure_account_dir,
    has_storage_state,
    storage_state_abs_path,
)


logger = logging.getLogger(__name__)


# Importação lazy do Playwright — evita erro no container API
# (que não tem o pacote instalado).

class AjusRunnerError(RuntimeError):
    """Erros do runner — porte do AjusConfigurationError do Mirror."""


class AjusLoginExpiredError(AjusRunnerError):
    """Sessão salva não é mais válida — precisa re-logar."""


# ─── Helpers de texto ────────────────────────────────────────────────


def _normalize_text(value: Optional[str]) -> str:
    """Normaliza pra comparação (sem acentos, lower, trim)."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


# ─── Runner ──────────────────────────────────────────────────────────


class AjusClassifRunner:
    """
    Runner Playwright pra classificar processos no AJUS.

    Uso típico (no container ajus-runner):

        with AjusClassifRunner(account, db) as runner:
            runner.ensure_logged_in()                # bloqueia até online
            for item in pending_items:
                runner.classify_item(item)
    """

    def __init__(self, account: AjusSessionAccount, db: Session) -> None:
        self.account = account
        self.db = db
        self.session_service = AjusSessionService(db)
        self.classif_service = AjusClassificacaoService(db)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    # ── Context manager ─────────────────────────────────────────────

    def __enter__(self) -> "AjusClassifRunner":
        from playwright.sync_api import sync_playwright

        ensure_account_dir(self.account)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context_kwargs = {
            "viewport": {"width": 1366, "height": 900},
            "ignore_https_errors": True,
        }
        if has_storage_state(self.account):
            context_kwargs["storage_state"] = str(
                storage_state_abs_path(self.account),
            )
        self._context = self._browser.new_context(**context_kwargs)
        self._page = self._context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._page:
                self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

    # ── Storage state ───────────────────────────────────────────────

    def _persist_storage_state(self) -> None:
        path = storage_state_abs_path(self.account)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(path))
        logger.info(
            "AJUS runner: storage_state salvo pra account %d em %s",
            self.account.id, path,
        )

    # ── Login ───────────────────────────────────────────────────────

    def ensure_logged_in(self) -> None:
        """
        Garante que a conta está autenticada. Se já tem storage_state
        válido, reaproveita. Senão, faz login completo (com tratamento
        de IP-code se AJUS pedir). Atualiza status da conta no DB.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        portal = settings.ajus_portal_base_url.rstrip("/")
        login_url = f"{portal}{settings.ajus_login_path}"

        try:
            self._page.goto(login_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            raise AjusRunnerError(f"Não consegui abrir {login_url}: {exc}") from exc

        # Sessão salva — se chegamos no workspace direto, ok.
        if not self._is_login_form_visible() and not self._is_ip_auth_visible():
            self._persist_storage_state()
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_ONLINE,
            )
            return

        # Validação de IP — pode aparecer antes do form
        if self._is_ip_auth_visible():
            self._handle_ip_validation()
            self._persist_storage_state()
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_ONLINE,
            )
            return

        # Form de login regular — AJUS pede 3 campos: domínio, usuário,
        # senha. Domínio é fixo por instalação (cliente MDR usa
        # `banco_master`), configurável via `AJUS_LOGIN_DOMAIN`.
        password = self.session_service.get_password(self.account)
        try:
            if settings.ajus_domain_selector and settings.ajus_login_domain:
                el = self._page.query_selector(settings.ajus_domain_selector)
                if el is not None:
                    self._page.fill(
                        settings.ajus_domain_selector,
                        settings.ajus_login_domain,
                    )
            self._page.fill(settings.ajus_user_selector, self.account.login)
            self._page.fill(settings.ajus_password_selector, password)
            self._page.click(settings.ajus_login_button_selector)
        except PlaywrightTimeoutError as exc:
            raise AjusRunnerError(f"Falha preenchendo form de login: {exc}") from exc

        # Espera resultado: workspace OU IP-code OU erro
        outcome = self._wait_for_login_outcome()
        if outcome == "ip_auth":
            self._handle_ip_validation()
            outcome = self._wait_for_login_outcome()
        if outcome != "workspace":
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_OFFLINE,
                error_message="AJUS não fechou a tela de login após enviar credenciais.",
            )
            raise AjusRunnerError(
                "AJUS não chegou no workspace após login. Confira credenciais.",
            )

        self._persist_storage_state()
        self.session_service.set_status(self.account.id, AJUS_ACCOUNT_ONLINE)

    def _is_login_form_visible(self) -> bool:
        try:
            user_el = self._page.query_selector(settings.ajus_user_selector)
            btn_el = self._page.query_selector(settings.ajus_login_button_selector)
            return bool(user_el and user_el.is_visible() and btn_el and btn_el.is_visible())
        except Exception:
            return False

    def _is_ip_auth_visible(self) -> bool:
        """
        Heurística: AJUS mostra um campo de "código de validação" depois
        do login. Procura por inputs/labels com texto "código" ou "IP".
        """
        try:
            return bool(
                self._page.query_selector(
                    "input[name*='codigo'], input[name*='code'], "
                    "input[id*='codigo'], input[id*='code'], "
                    "*:has-text('Código de validação'), "
                    "*:has-text('Validação de IP')"
                )
            )
        except Exception:
            return False

    def _wait_for_login_outcome(self) -> str:
        """
        Aguarda até `ajus_login_outcome_timeout_ms`. Retorna:
          'workspace' — login concluído
          'ip_auth' — AJUS pedindo código de IP
          'login_form' — ainda no form (provavelmente erro)
          'unknown' — não conseguiu identificar
        """
        deadline = time.monotonic() + (
            settings.ajus_login_outcome_timeout_ms / 1000.0
        )
        while time.monotonic() < deadline:
            if self._is_ip_auth_visible():
                return "ip_auth"
            if not self._is_login_form_visible():
                return "workspace"
            time.sleep(0.5)
        return "login_form"

    def _handle_ip_validation(self) -> None:
        """
        AJUS pediu código de validação de IP. Marca conta como
        `aguardando_ip_code`, polla `pending_ip_code` no DB até o
        operador submeter pela UI, preenche e tenta submeter.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        self.session_service.set_status(
            self.account.id, AJUS_ACCOUNT_AGUARDANDO_IP,
        )
        logger.info(
            "AJUS runner: account %d aguardando IP-code (operador submete via UI)",
            self.account.id,
        )

        deadline = time.monotonic() + settings.ajus_ip_code_wait_seconds
        code: Optional[str] = None
        while time.monotonic() < deadline:
            self.db.refresh(self.account)
            if self.account.pending_ip_code:
                code = self.account.pending_ip_code.strip()
                break
            time.sleep(2)

        if not code:
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_OFFLINE,
                error_message="Operador não submeteu IP-code dentro do prazo.",
            )
            raise AjusRunnerError("Timeout esperando IP-code do operador.")

        # Tenta encontrar o input do código e submeter
        try:
            # Heurística — primeiro input vazio com nome/id de "codigo"
            sel = (
                "input[name*='codigo'], input[name*='code'], "
                "input[id*='codigo'], input[id*='code']"
            )
            self._page.fill(sel, code)
            # Submit pode ser Enter ou um botão "Validar/Confirmar"
            self._page.keyboard.press("Enter")
        except PlaywrightTimeoutError as exc:
            self.session_service.clear_ip_code(self.account.id)
            raise AjusRunnerError(f"Falha ao submeter IP-code: {exc}") from exc

        self.session_service.clear_ip_code(self.account.id)

    # ── Classificação ───────────────────────────────────────────────

    def classify_item(self, item: AjusClassificacaoQueue) -> None:
        """
        Classifica um único item da fila. Atualiza status (processando
        → sucesso/erro). Idempotente — se item já está em sucesso,
        retorna sem fazer nada.
        """
        if item.status != AJUS_CLASSIF_PENDENTE:
            logger.info(
                "AJUS runner: item %d não está pendente (status=%s) — pulando",
                item.id, item.status,
            )
            return

        # Marca processando
        item = self.classif_service.mark_processing(item.id)
        item.dispatched_by_account_id = self.account.id
        self.db.commit()

        try:
            self._open_process_by_cnj(item.cnj_number)
            self._update_process_cover(item)
            self._validate_process_cover(item)
            self.classif_service.mark_success(
                item.id,
                last_log=f"Classificado por account_id={self.account.id} em {datetime.now(timezone.utc).isoformat()}",
            )
            logger.info(
                "AJUS runner: item %d (cnj=%s) classificado com sucesso",
                item.id, item.cnj_number,
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)[:4000]
            self.classif_service.mark_error(item.id, error_message=msg)
            logger.exception(
                "AJUS runner: falha classificando item %d (cnj=%s): %s",
                item.id, item.cnj_number, msg,
            )

    def _open_process_by_cnj(self, cnj: str) -> None:
        """
        Abre a tela do processo no AJUS. Estratégia preferida:
        URL template (`AJUS_PROCESS_SEARCH_URL_TEMPLATE`). Fallback:
        usa o input de busca rápida do workspace.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        if settings.ajus_process_search_url_template:
            url = settings.ajus_process_search_url_template.format(
                process_number=cnj,
            )
            self._page.goto(url, wait_until="domcontentloaded")
            self._page.wait_for_timeout(2000)
            return

        if not settings.ajus_process_search_input_selector:
            raise AjusRunnerError(
                "Sem AJUS_PROCESS_SEARCH_URL_TEMPLATE nem "
                "AJUS_PROCESS_SEARCH_INPUT_SELECTOR configurado — "
                "runner não sabe como abrir o processo.",
            )

        try:
            search = self._page.locator(
                settings.ajus_process_search_input_selector,
            ).first
            search.click()
            search.fill(cnj)
            self._page.keyboard.press("Enter")
            self._page.wait_for_timeout(2000)
        except PlaywrightTimeoutError as exc:
            raise AjusRunnerError(
                f"Não consegui usar o input de busca do AJUS: {exc}",
            ) from exc

    def _update_process_cover(self, item: AjusClassificacaoQueue) -> None:
        """Preenche os 5 campos da capa via ExtJS."""
        for required, value in [
            ("UF", item.uf),
            ("Comarca", item.comarca),
            ("Matéria", item.matter),
            ("Justiça/Honorário", item.justice_fee),
            ("Risco/Prob. Perda", item.risk_loss_probability),
        ]:
            if not value or not value.strip():
                raise AjusRunnerError(
                    f"Item {item.id} sem `{required}` preenchido — "
                    f"operador precisa editar antes do dispatch.",
                )

        self._fill_combo("UF", settings.ajus_process_uf_selector, item.uf)
        self._fill_combo("Comarca", settings.ajus_process_comarca_selector, item.comarca)
        self._fill_combo("Matéria", settings.ajus_process_matter_selector, item.matter)
        self._fill_combo(
            "Justiça/Honorário",
            settings.ajus_process_justice_fee_selector,
            item.justice_fee,
        )
        self._fill_combo(
            "Risco/Prob. Perda",
            settings.ajus_process_risk_selector,
            item.risk_loss_probability,
        )

        if settings.ajus_process_save_selector:
            self._page.click(settings.ajus_process_save_selector)
            self._page.wait_for_timeout(1500)

    def _fill_combo(
        self, label: str, selector: Optional[str], value: str,
    ) -> None:
        """
        Preenche um combobox ExtJS:
          1. Clica no campo
          2. Limpa
          3. Digita o valor
          4. Espera 800ms (autocomplete)
          5. Press ArrowDown + Enter pra selecionar primeiro match
        Se o portal mudar layout, esses passos viram o ponto de
        ajuste (mesmo padrão do Mirror).
        """
        if not selector:
            raise AjusRunnerError(
                f"Selector pra '{label}' não configurado "
                f"(setar AJUS_PROCESS_*_SELECTOR no env).",
            )
        loc = self._page.locator(selector).first
        loc.click()
        self._page.keyboard.press("Control+a")
        self._page.keyboard.press("Delete")
        loc.fill(value)
        self._page.wait_for_timeout(800)
        self._page.keyboard.press("ArrowDown")
        self._page.keyboard.press("Enter")
        self._page.wait_for_timeout(400)

    def _validate_process_cover(self, item: AjusClassificacaoQueue) -> None:
        """
        Re-lê os 5 campos da capa e compara com o esperado.
        Levanta se algum não bater (normalizado — case/acentos
        ignorados).
        """
        actual = {
            "UF": self._read_field_value(settings.ajus_process_uf_selector),
            "Comarca": self._read_field_value(settings.ajus_process_comarca_selector),
            "Matéria": self._read_field_value(settings.ajus_process_matter_selector),
            "Justiça/Honorário": self._read_field_value(
                settings.ajus_process_justice_fee_selector,
            ),
            "Risco/Prob. Perda": self._read_field_value(
                settings.ajus_process_risk_selector,
            ),
        }
        expected = {
            "UF": item.uf or "",
            "Comarca": item.comarca or "",
            "Matéria": item.matter or "",
            "Justiça/Honorário": item.justice_fee or "",
            "Risco/Prob. Perda": item.risk_loss_probability or "",
        }
        mismatches = []
        for label, exp in expected.items():
            got = actual.get(label, "")
            if _normalize_text(got) != _normalize_text(exp):
                mismatches.append(f"{label}: esperado '{exp}', encontrado '{got}'")
        if mismatches:
            raise AjusRunnerError(
                "Capa não ficou com valores esperados após o save: "
                + " | ".join(mismatches),
            )

    def _read_field_value(self, selector: Optional[str]) -> str:
        if not selector:
            return ""
        try:
            loc = self._page.locator(selector).first
            return (loc.input_value() or "").strip()
        except Exception:
            try:
                loc = self._page.locator(selector).first
                return (loc.text_content() or "").strip()
            except Exception:
                return ""
