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
from app.services.ajus import portal_constants as portal
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

    def _dump_login_state(self, label: str) -> str:
        """
        Salva screenshot + URL + título no volume da conta pra debug
        do flow de login. Retorna mensagem com a URL/path do PNG —
        anexa em error_message pra mostrar na UI.
        """
        try:
            ensure_account_dir(self.account)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            png = (
                Path(settings.ajus_session_path)
                / str(self.account.id)
                / f"debug-{label}-{ts}.png"
            )
            self._page.screenshot(path=str(png), full_page=True)
            url = self._page.url
            title = self._page.title()
            logger.error(
                "AJUS runner DEBUG[%s] account=%d url=%r title=%r screenshot=%s",
                label, self.account.id, url, title, png,
            )
            return f"url={url} | title={title!r} | screenshot={png.name}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao dump_login_state: %s", exc)
            return "(falha ao capturar debug)"

    def ensure_logged_in(self) -> None:
        """
        Garante que a conta esta autenticada (porte do flow do Mirror).

        Ordem de checagem:
          1. Carrega URL de login (wait_until="commit" — leve, sem
             travar em sites ExtJS que nunca ficam network-idle).
          2. Tenta detectar IP-auth surface primeiro (timeout 5s).
             Se aparecer, processa validacao de IP.
          3. Tenta detectar login form depois (timeout 15s).
             Se aparecer, preenche e submete.
          4. Se nada disso aparecer, assume que a sessao foi
             reaproveitada (storage_state valido).
        """
        login_url = f"{portal.PORTAL_BASE_URL.rstrip('/')}{portal.LOGIN_PATH}"
        self._goto(login_url)

        # 1. IP-auth surface (sessao reaproveitada mas IP novo)
        if self._wait_for_ip_auth_surface(timeout_ms=5000) or self._is_ip_auth_flow_visible():
            self._handle_ip_validation()
            self._persist_storage_state()
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_ONLINE,
            )
            return

        # 2. Login form
        if self._wait_for_login_form(timeout_ms=15000) or self._is_login_form_visible():
            password = self.session_service.get_password(self.account)
            try:
                self._page.fill(portal.DOMAIN_SELECTOR, portal.LOGIN_DOMAIN)
                self._page.fill(portal.USER_SELECTOR, self.account.login)
                self._page.fill(portal.PASSWORD_SELECTOR, password)
                self._page.click(portal.LOGIN_BUTTON_SELECTOR)
            except Exception as exc:  # noqa: BLE001
                debug = self._dump_login_state("login-fill-failed")
                self.session_service.set_status(
                    self.account.id, AJUS_ACCOUNT_OFFLINE,
                    error_message=f"Falha preenchendo form de login: {exc} | {debug}",
                )
                raise AjusRunnerError(
                    f"Falha preenchendo form de login: {exc}",
                ) from exc

            self._settle(wait_ms=2000)

            outcome = self._wait_for_login_outcome(
                timeout_ms=settings.ajus_login_outcome_timeout_ms,
            )

            if outcome == "ip_auth":
                self._handle_ip_validation()
                outcome = self._wait_for_login_outcome(
                    timeout_ms=settings.ajus_login_outcome_timeout_ms,
                )

            if outcome != "workspace":
                debug = self._dump_login_state("login-failed")
                self.session_service.set_status(
                    self.account.id, AJUS_ACCOUNT_OFFLINE,
                    error_message=(
                        f"AJUS nao concluiu login apos enviar credenciais. "
                        f"outcome={outcome} | {debug}"
                    ),
                )
                raise AjusRunnerError(
                    f"AJUS nao chegou no workspace apos login (outcome={outcome}). "
                    f"Veja {debug}",
                )

            self._persist_storage_state()
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_ONLINE,
            )
            return

        # 3. Sessao reaproveitada — nem login form nem IP-auth aparecem.
        self._persist_storage_state()
        self.session_service.set_status(
            self.account.id, AJUS_ACCOUNT_ONLINE,
        )
        logger.info(
            "AJUS runner: account %d — sessao reaproveitada (sem login form)",
            self.account.id,
        )

    # ── Helpers do flow de login (porte do Mirror) ─────────────────

    def _goto(self, url: str) -> None:
        """
        Navegacao tolerante: wait_until="commit" retorna assim que os
        headers chegam. NAO espera DOM nem rede idle. Em portais ExtJS
        com long-polling, networkidle nunca estoura — wait_until="commit"
        evita o trava-trava.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        try:
            self._page.goto(url, wait_until="commit", timeout=30_000)
        except PlaywrightTimeoutError:
            pass
        self._settle(wait_ms=1500)

    def _settle(self, *, wait_ms: int = 1500) -> None:
        """Espera DOM carregar (best-effort) + pausa."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        self._page.wait_for_timeout(wait_ms)

    def _is_visible(self, selector: Optional[str]) -> bool:
        """Util — retorna True se algum elemento desse selector eh visivel."""
        if not selector:
            return False
        try:
            loc = self._page.locator(selector)
            count = loc.count()
            for i in range(count):
                try:
                    if loc.nth(i).is_visible():
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def _is_login_form_visible(self) -> bool:
        """
        Marker do form de login: domain selector + login button.
        (Mirror checa esses 2; #username sozinho nao basta.)
        """
        return self._is_visible(portal.DOMAIN_SELECTOR) and self._is_visible(
            portal.LOGIN_BUTTON_SELECTOR,
        )

    def _is_ip_auth_visible(self) -> bool:
        """Inputs do codigo de validacao de IP visiveis?"""
        return self._is_visible(portal.IP_AUTH_INPUT_SELECTOR)

    def _is_ip_auth_request_visible(self) -> bool:
        """Botao 'Receber codigo' visivel? (1a tela do flow de IP-auth)"""
        return self._is_visible(portal.IP_AUTH_REQUEST_SELECTOR)

    def _is_ip_auth_flow_visible(self) -> bool:
        """Qualquer tela de IP-auth (request ou inputs) visivel?"""
        return self._is_ip_auth_request_visible() or self._is_ip_auth_visible()

    def _is_workspace_marker_visible(self) -> bool:
        """
        Marker positivo do workspace. Multiplos seletores (porte do
        Mirror) — aceita qualquer um deles como evidencia de workspace
        pronto:
          1. Input de busca rapida (quando expandido).
          2. Icone de lupa `a.search` (sempre visivel quando logado,
             mesmo com a busca colapsada).
        """
        return (
            self._is_visible(portal.PROCESS_SEARCH_INPUT_SELECTOR)
            or self._is_visible(portal.PROCESS_SEARCH_TRIGGER_SELECTOR)
        )

    def _is_workspace_blocked(self) -> bool:
        """
        Tela de loading do AJUS apos login ('aguarde, estamos preparando
        o seu AJUS') OU bloqueio de tela de login. Quando visivel,
        workspace NAO esta pronto ainda.
        """
        return (
            self._is_visible(portal.WORKSPACE_LOADING_TEXT_SELECTOR)
            or self._is_visible(portal.WORKSPACE_BLOCKED_SELECTOR)
        )

    def _is_workspace_ready(self) -> bool:
        """
        Workspace esta pronto pra interagir? Exige:
          - NAO ter login form visivel
          - NAO ter IP-auth flow visivel
          - NAO ter tela de loading visivel
          - TER algum marker positivo (search input ou search trigger)
        """
        if self._is_login_form_visible() or self._is_ip_auth_flow_visible():
            return False
        if self._is_workspace_blocked():
            return False
        return self._is_workspace_marker_visible()

    def _wait_for_login_form(self, *, timeout_ms: int) -> bool:
        """Aguarda DOMAIN_SELECTOR ficar visivel (Playwright nativo)."""
        try:
            self._page.locator(portal.DOMAIN_SELECTOR).first.wait_for(
                state="visible", timeout=timeout_ms,
            )
            return True
        except Exception:
            return False

    def _wait_for_ip_auth_surface(self, *, timeout_ms: int) -> bool:
        """Polling pra detectar tela de IP-auth (request ou inputs)."""
        deadline = time.monotonic() + max(timeout_ms / 1000, 1)
        while time.monotonic() < deadline:
            if self._is_ip_auth_flow_visible():
                return True
            self._page.wait_for_timeout(500)
        return False

    def _wait_for_login_outcome(self, *, timeout_ms: int) -> str:
        """
        Apos o submit do login, aguarda ate timeout_ms. Retorna:
          'ip_auth'    — IP-auth flow apareceu
          'workspace'  — workspace esta pronto
          'login_form' — timeout, form ainda visivel (login falhou)
        """
        deadline = time.monotonic() + max(timeout_ms / 1000, 1)
        while time.monotonic() < deadline:
            if self._is_ip_auth_flow_visible():
                return "ip_auth"
            if self._is_workspace_ready():
                return "workspace"
            self._page.wait_for_timeout(500)
        return "login_form"

    def _handle_ip_validation(self) -> None:
        """
        Processa o flow de validacao de IP do AJUS:
          1. Se botao 'Receber codigo' esta visivel, clica nele.
          2. Espera operador submeter codigo via UI (polling DB).
          3. Distribui os 6 digitos nos 6 inputs separados.
          4. Clica 'Confirmar' (a[href='#finish']).
        """
        # Etapa 1: clica em "Receber codigo" se aparecer
        if self._is_ip_auth_request_visible():
            try:
                self._page.click(portal.IP_AUTH_REQUEST_SELECTOR)
                self._settle(wait_ms=2500)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "AJUS runner: nao consegui clicar 'Receber codigo': %s", exc,
                )

        # Apos o click, os 6 inputs devem aparecer
        if not self._is_ip_auth_visible():
            debug = self._dump_login_state("ip-auth-no-inputs")
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_OFFLINE,
                error_message=(
                    "AJUS pediu codigo de IP mas os campos nao apareceram "
                    f"apos clicar 'Receber'. {debug}"
                ),
            )
            raise AjusRunnerError(
                f"Inputs do codigo de IP nao apareceram. {debug}",
            )

        # Etapa 2: aguarda operador submeter via UI
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
                error_message="Operador nao submeteu IP-code dentro do prazo.",
            )
            raise AjusRunnerError("Timeout esperando IP-code do operador.")

        # Etapa 3: 6 digitos em 6 inputs separados
        digits = code.strip()
        if len(digits) != 6 or not digits.isdigit():
            self.session_service.clear_ip_code(self.account.id)
            raise AjusRunnerError(
                f"IP-code deve ter exatamente 6 digitos, recebido: {len(digits)}",
            )

        try:
            input_count = self._page.locator(portal.IP_AUTH_INPUT_SELECTOR).count()
            if input_count < 6:
                debug = self._dump_login_state("ip-auth-too-few-inputs")
                raise AjusRunnerError(
                    f"AJUS espera 6 inputs de IP-code mas vimos {input_count}. {debug}",
                )

            for index, digit in enumerate(digits):
                self._page.locator(portal.IP_AUTH_INPUT_SELECTOR).nth(index).fill(digit)

            # Etapa 4: confirmar
            self._page.click(portal.IP_AUTH_CONFIRM_SELECTOR)
            self._settle(wait_ms=1800)
        except Exception as exc:  # noqa: BLE001
            self.session_service.clear_ip_code(self.account.id)
            raise AjusRunnerError(f"Falha ao submeter IP-code: {exc}") from exc

        self.session_service.clear_ip_code(self.account.id)

        # Se ainda esta na tela de IP-auth, codigo foi rejeitado
        if self._is_ip_auth_visible():
            self.session_service.set_status(
                self.account.id, AJUS_ACCOUNT_OFFLINE,
                error_message="Codigo de validacao de IP nao foi aceito pelo AJUS.",
            )
            raise AjusRunnerError(
                "Codigo de IP rejeitado pelo AJUS. Solicite novo codigo.",
            )

        logger.info(
            "AJUS runner: account %d — IP-code validado com sucesso",
            self.account.id,
        )

    # ── Classificacao ───────────────────────────────────────────────

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
        Abre a tela do processo no AJUS via busca rápida (overlay
        esquerdo): clica no input, digita o CNJ, espera o dropdown
        ExtJS aparecer, clica no item correspondente.

        AJUS não aceita URL direta com CNJ — o portal é um workspace
        ExtJS single-page. Tem que passar pela busca.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        try:
            search = self._page.locator(
                portal.PROCESS_SEARCH_INPUT_SELECTOR,
            ).first
            search.click()
            search.fill(cnj)
            self._page.wait_for_timeout(800)  # autocomplete

            # Clica no item do dropdown que contém o CNJ. Sem isso o
            # ExtJS combobox não navega — só mostra resultados.
            result_selector = portal.PROCESS_RESULT_SELECTOR_TEMPLATE.format(
                process_number=cnj,
            )
            result = self._page.locator(result_selector).first
            result.wait_for(state="visible", timeout=5_000)
            result.click()
            self._page.wait_for_timeout(2000)
        except PlaywrightTimeoutError as exc:
            raise AjusRunnerError(
                f"Não consegui abrir o processo {cnj} via busca rápida: {exc}",
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

        self._fill_combo("UF", portal.PROCESS_UF_SELECTOR, item.uf)
        self._fill_combo("Comarca", portal.PROCESS_COMARCA_SELECTOR, item.comarca)
        self._fill_combo("Matéria", portal.PROCESS_MATTER_SELECTOR, item.matter)
        self._fill_combo(
            "Justiça/Honorário",
            portal.PROCESS_JUSTICE_FEE_SELECTOR,
            item.justice_fee,
        )
        self._fill_combo(
            "Risco/Prob. Perda",
            portal.PROCESS_RISK_SELECTOR,
            item.risk_loss_probability,
        )

        self._page.click(portal.PROCESS_SAVE_SELECTOR)
        self._page.wait_for_timeout(1500)

    def _fill_combo(
        self, label: str, selector: str, value: str,
    ) -> None:
        """
        Preenche um combobox ExtJS:
          1. Clica no campo
          2. Limpa
          3. Digita o valor
          4. Espera 800ms (autocomplete)
          5. Press ArrowDown + Enter pra selecionar primeiro match
        Se o portal mudar layout, o ajuste é em
        `app/services/ajus/portal_constants.py`.
        """
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
            "UF": self._read_field_value(portal.PROCESS_UF_SELECTOR),
            "Comarca": self._read_field_value(portal.PROCESS_COMARCA_SELECTOR),
            "Matéria": self._read_field_value(portal.PROCESS_MATTER_SELECTOR),
            "Justiça/Honorário": self._read_field_value(
                portal.PROCESS_JUSTICE_FEE_SELECTOR,
            ),
            "Risco/Prob. Perda": self._read_field_value(
                portal.PROCESS_RISK_SELECTOR,
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

    def _read_field_value(self, selector: str) -> str:
        try:
            loc = self._page.locator(selector).first
            return (loc.input_value() or "").strip()
        except Exception:
            try:
                loc = self._page.locator(selector).first
                return (loc.text_content() or "").strip()
            except Exception:
                return ""
