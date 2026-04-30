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
import re
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


class AjusProcessNotFoundError(AjusRunnerError):
    """
    AJUS retornou explicitamente que nao encontrou o processo na busca
    rapida (texto "Desculpe, mas nenhuma acao foi encontrada"). Nao eh
    erro tecnico — eh um caso legitimo de "processo nao cadastrado no
    AJUS dessa conta".
    """


# ─── Helpers de texto ────────────────────────────────────────────────


_CNJ_DIGITS_RE = re.compile(r"\D")


def _cnj_digits(cnj: Optional[str]) -> str:
    """Strip non-digits do CNJ. Aceita raw ou mascarado."""
    if not cnj:
        return ""
    return _CNJ_DIGITS_RE.sub("", str(cnj))


def _format_cnj_mask(cnj: Optional[str]) -> str:
    """
    Formata CNJ no padrao oficial NNNNNNN-DD.AAAA.J.TT.OOOO. Aceita
    input cru (20 digitos) ou ja mascarado. Se nao tem 20 digitos
    apos strip, devolve a string original sem mexer (fallback seguro).

    Mirror digitava o CNJ MASCARADO no input do AJUS — o ExtJS de la
    espera essa forma e renderiza o card de resultado com a mesma
    string formatada (verificado no DOM via DevTools). Nosso intake
    salva cnj_number cru (20 digits), entao precisamos formatar antes
    de passar pra busca/selectors.
    """
    digits = _cnj_digits(cnj)
    if len(digits) != 20:
        return cnj or ""
    return f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:20]}"


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

    def _is_workspace_blocked(self) -> bool:
        """
        Tela de loading ('aguarde, estamos preparando') OU bloqueio
        do login. Quando visivel, workspace NAO esta pronto.
        """
        return (
            self._is_visible(portal.WORKSPACE_LOADING_TEXT_SELECTOR)
            or self._is_visible(portal.WORKSPACE_BLOCKED_SELECTOR)
        )

    def _is_workspace_ready(self) -> bool:
        """
        Workspace pronto pra interagir? Porte direto do Mirror:
          1. NAO eh login form, IP-auth ou tela de loading.
          2. ENTAO accepta qualquer marker positivo:
             a. Input de busca rapida visivel.
             b. Trigger de busca (a.search) clicavel.
             c. Menu de processos clicavel (fallback).
             d. Algum input generico de busca (fallback).
        """
        if self._is_login_form_visible() or self._is_ip_auth_flow_visible():
            return False
        if self._is_workspace_blocked():
            return False

        # Marker primario — input de busca rapida
        if self._is_visible(portal.PROCESS_SEARCH_INPUT_SELECTOR):
            return True

        # Marker secundario — trigger da busca (icone de lupa)
        if self._can_click(portal.PROCESS_SEARCH_TRIGGER_SELECTOR):
            return True

        # Fallback — menu de processos clicavel
        if self._can_click(portal.MENU_PROCESSES_SELECTOR):
            return True

        # Fallback — qualquer input generico
        for sel in portal.PROCESS_QUICK_SEARCH_FALLBACK_SELECTORS:
            if self._is_visible(sel):
                return True

        return False

    def _wait_for_workspace_ready(self, *, timeout_ms: int = 45_000) -> None:
        """
        Bloqueia ate workspace_ready ou estoura. Usado APOS login
        (depois do _wait_for_login_outcome) e ANTES de buscar processo.
        """
        deadline = time.monotonic() + max(timeout_ms / 1000, 1)
        while time.monotonic() < deadline:
            if self._is_workspace_ready():
                return
            self._page.wait_for_timeout(500)
        debug = self._dump_login_state("workspace-not-ready")
        raise AjusRunnerError(
            f"AJUS nao liberou workspace dentro do timeout. {debug}",
        )

    def _is_minimal_shell(self) -> bool:
        """
        Detecta pagina shell-only do AJUS (apenas 'menu' / 'menu search'
        no body). Significa que sessao salva carregou mas nao liberou
        o workspace.
        """
        try:
            body = self._page.locator("body").inner_text(timeout=2000)
        except Exception:
            return False
        normalized = " ".join(body.split()).strip().lower()
        return normalized in {"menu search", "menu"} or normalized.startswith("menu search ")

    # ── Helpers de Locator (porte do Mirror) ───────────────────────

    def _is_hit_target(self, locator) -> bool:
        """
        Confirma que o locator eh o elemento real no ponto central
        (nao tem outro elemento sobreposto). Util pra evitar clicks
        em elementos visualmente cobertos por overlays/modals.
        """
        try:
            return bool(
                locator.evaluate(
                    """element => {
                        if (!element) return false;
                        const rect = element.getBoundingClientRect();
                        if (!element.offsetParent || rect.width <= 0 || rect.height <= 0) return false;
                        const cx = rect.left + rect.width / 2;
                        const cy = rect.top + rect.height / 2;
                        const top = document.elementFromPoint(cx, cy);
                        return !!top && (top === element || element.contains(top) || top.contains(element));
                    }"""
                )
            )
        except Exception:
            return False

    def _locator(self, selector: str):
        """
        Retorna o melhor locator pra um selector que pode matchear
        varios elementos. Prefere visivel + hit-target; senao primeiro
        visivel; senao primeiro do match.
        """
        loc = self._page.locator(selector)
        try:
            count = loc.count()
        except Exception:
            count = 0
        fallback = loc.first
        visible_fallback = loc.first
        for index in range(count):
            candidate = loc.nth(index)
            fallback = candidate
            try:
                if candidate.is_visible():
                    visible_fallback = candidate
                    if self._is_hit_target(candidate):
                        return candidate
            except Exception:
                continue
        return visible_fallback if count else fallback

    def _visible_locator(self, selector: str, *, timeout_s: int = 15):
        """
        Como `_locator`, mas com retry com timeout. Espera ate algum
        elemento ficar visivel (e idealmente hit-target).
        """
        loc = self._page.locator(selector)
        deadline = time.monotonic() + max(timeout_s, 1)
        visible_fallback = loc.first
        while time.monotonic() < deadline:
            try:
                count = loc.count()
            except Exception:
                count = 0
            for index in range(count):
                candidate = loc.nth(index)
                try:
                    if candidate.is_visible():
                        visible_fallback = candidate
                        if self._is_hit_target(candidate):
                            return candidate
                except Exception:
                    continue
            self._page.wait_for_timeout(250)
        return visible_fallback

    def _can_click(self, selector: Optional[str]) -> bool:
        """Testa se o selector tem um elemento clicavel agora."""
        if not selector:
            return False
        try:
            loc = self._visible_locator(selector, timeout_s=2)
        except Exception:
            return False
        try:
            loc.click(trial=True, timeout=1500)
            return True
        except Exception:
            return False

    def _click(self, selector: str, *, double: bool = False):
        """
        Click robusto: scroll into view + click normal -> click force ->
        evaluate JS click. Suporta dblclick.
        """
        loc = self._visible_locator(selector)
        try:
            loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            if double:
                loc.dblclick()
            else:
                loc.click()
            return loc
        except Exception:
            pass
        try:
            if double:
                loc.dblclick(force=True)
            else:
                loc.click(force=True)
            return loc
        except Exception:
            pass
        if double:
            loc.evaluate(
                "element => element.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }))"
            )
        else:
            loc.evaluate("element => element.click()")
        return loc

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

    def _reset_workspace(self) -> None:
        """
        Reseta o workspace pra um estado limpo entre itens. Mirror
        nao precisa disso porque abre browser novo por item, mas como
        nossa arquitetura compartilha browser por batch, o tab da
        Acao Judicial aberta no item anterior fica residual e quebra
        a busca rapida do proximo item.

        Estrategia:
          1. Aceita qualquer dialog "alteracoes nao salvas" automaticamente.
          2. Navega pra base URL (descarta tabs abertas).
          3. Aguarda workspace ready (45s) — pode precisar relogar
             se a sessao caiu, mas storage_state cobre isso.
        """
        # 1. Auto-accept dialog se aparecer (page.goto pode disparar)
        def _accept_dialog(dialog):
            try:
                dialog.accept()
            except Exception:
                pass
        try:
            self._page.on("dialog", _accept_dialog)
        except Exception:
            pass

        # 2. Navega pra base URL (workspace fresco)
        try:
            self._page.goto(
                portal.PORTAL_BASE_URL.rstrip("/") + "/#",
                wait_until="commit",
                timeout=30_000,
            )
        except Exception as exc:
            logger.warning(
                "AJUS runner: falha resetando workspace via goto: %s — "
                "tentando reload.", exc,
            )
            try:
                self._page.reload(wait_until="commit", timeout=30_000)
            except Exception as exc2:
                logger.warning(
                    "AJUS runner: reload tambem falhou: %s", exc2,
                )

        # 3. Settle + workspace ready
        self._settle(wait_ms=2000)
        try:
            self._wait_for_workspace_ready(timeout_ms=45_000)
        except Exception as exc:
            logger.warning(
                "AJUS runner: workspace nao ficou ready apos reset: %s. "
                "Proximo item pode falhar — release de account na sequencia.",
                exc,
            )

        # 4. Remove o handler de dialog pra nao acumular entre resets
        try:
            self._page.remove_listener("dialog", _accept_dialog)
        except Exception:
            pass

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
        except AjusProcessNotFoundError as exc:
            # Caso "AJUS nao tem esse processo" — distinto de erro tecnico.
            # Nao retentar automaticamente.
            self.classif_service.mark_not_found(
                item.id,
                details=str(exc)[:500],
            )
            logger.info(
                "AJUS runner: item %d (cnj=%s) NAO ENCONTRADO no AJUS: %s",
                item.id, item.cnj_number, exc,
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)[:4000]
            self.classif_service.mark_error(item.id, error_message=msg)
            logger.exception(
                "AJUS runner: falha classificando item %d (cnj=%s): %s",
                item.id, item.cnj_number, msg,
            )
        finally:
            # SEMPRE resetar workspace entre itens (sucesso ou erro).
            # Sem isso, o tab/foco do processo anterior fica residual
            # e o _find_process_search_input do proximo item recebe
            # o input errado / dropdown nao aparece. Mirror nao precisa
            # porque abre browser novo por item; nos compartilhamos
            # browser por batch entao precisamos do reset explicito.
            try:
                self._reset_workspace()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "AJUS runner: reset_workspace falhou apos item %d: %s. "
                    "Proximo item pode acumular state-bleed.",
                    item.id, exc,
                )

    def _find_process_search_input(self):
        """
        Acha o input de busca rapida do AJUS. Estrategia (Mirror):
          1. Tenta seletor configurado.
          2. Tenta seletores fallback genericos.
          3. Se nenhum visivel, clica no `a.search` pra expandir busca.
          4. Se ainda nao, clica no menu de processos (fallback).
          5. Loop com timeout de 15s.
        """
        candidates = [portal.PROCESS_SEARCH_INPUT_SELECTOR]
        candidates.extend(portal.PROCESS_QUICK_SEARCH_FALLBACK_SELECTORS)

        deadline = time.monotonic() + 15
        clicked_search_trigger = False
        clicked_menu_fallback = False

        while time.monotonic() < deadline:
            for sel in candidates:
                if self._is_visible(sel):
                    return self._visible_locator(sel)

            if not clicked_search_trigger and self._is_visible(portal.PROCESS_SEARCH_TRIGGER_SELECTOR):
                self._click(portal.PROCESS_SEARCH_TRIGGER_SELECTOR)
                self._settle(wait_ms=1500)
                clicked_search_trigger = True
                continue

            if not clicked_menu_fallback and self._is_visible(portal.MENU_PROCESSES_SELECTOR):
                self._click(portal.MENU_PROCESSES_SELECTOR)
                self._settle(wait_ms=1500)
                clicked_menu_fallback = True
                continue

            self._page.wait_for_timeout(500)

        debug = self._dump_login_state("search-input-not-found")
        raise AjusRunnerError(
            f"Nao foi possivel localizar a busca rapida do AJUS. {debug}",
        )

    def _type_process_search(self, search_input, cnj: str) -> None:
        """
        Limpa o campo e digita o CNJ MASCARADO (NNNNNNN-DD.AAAA.J.TT.OOOO).
        Apos digitar, FORCA o ExtJS combobox a disparar a query via
        Ext.getCmp(id).doQuery(value, true) — bypassa cache de lastQuery
        e garante que o XHR /ajax.handler.php?ajax=BuscaRapidaController.php
        sempre dispare. Sem isso, observamos casos onde o keyup nao chega
        ou o ExtJS dedupe a query (lastQuery=mesmo valor) e o XHR nao roda.
        Quando o XHR nao roda, o painel "sem resultados" tambem nao
        renderiza, entao a deteccao de nao_encontrado fica engasgada.
        """
        masked = _format_cnj_mask(cnj)
        try:
            search_input.press("Control+A")
            search_input.press("Delete")
        except Exception:
            pass
        try:
            search_input.fill("")
        except Exception:
            pass
        # Tipar normalmente — alguns flows do AJUS dependem do typing
        # pra mostrar autocomplete antes do submit.
        try:
            search_input.press_sequentially(masked, delay=35)
        except Exception:
            self._page.keyboard.type(masked, delay=35)

        # Forcar a query via JS — estrategia tripla:
        #   A) Ext.getCmp(input.id) — direto.
        #   B) Iteracao em ComponentMgr/ComponentManager procurando
        #      combobox cujo elemento contenha o input.
        #   C) Fallback bruto: dispatchEvent('keyup' + 'input' + 'change')
        #      — sempre executa, alguns flows do AJUS so reagem ao evento
        #      nativo. Garante que o XHR de busca sempre dispara.
        # Loga o status retornado pra termos visibilidade do que aconteceu.
        try:
            doquery_status = search_input.evaluate(
                """(el, value) => {
                    const result = { ext: false, found_cmp: null, doQuery: null, fallback: null, errors: [] };
                    if (!window.Ext) return result;
                    result.ext = true;
                    let cmp = null;
                    try {
                        if (el.id && Ext.getCmp) {
                            const c = Ext.getCmp(el.id);
                            if (c && typeof c.doQuery === 'function') {
                                cmp = c; result.found_cmp = 'getCmp:' + el.id;
                            }
                        }
                    } catch (e) { result.errors.push('getCmp:' + e.message); }
                    if (!cmp) {
                        try {
                            const all = (Ext.ComponentMgr && Ext.ComponentMgr.all)
                                ? (Ext.ComponentMgr.all.items || Object.values(Ext.ComponentMgr.all))
                                : ((Ext.ComponentManager && Ext.ComponentManager.all)
                                    ? (Ext.ComponentManager.all.items || Object.values(Ext.ComponentManager.all))
                                    : []);
                            result.errors.push('total:' + (all ? all.length : 0));
                            for (const c of (all || [])) {
                                if (!c || typeof c.doQuery !== 'function') continue;
                                try {
                                    const ie = c.getEl && c.getEl();
                                    const root = (ie && ie.dom) ? ie.dom : null;
                                    if (root && (root === el || root.contains(el))) {
                                        cmp = c; result.found_cmp = 'iter:' + (c.id || '?'); break;
                                    }
                                } catch (e2) {}
                            }
                        } catch (e3) { result.errors.push('iter:' + e3.message); }
                    }
                    if (cmp && typeof cmp.doQuery === 'function') {
                        try {
                            if (typeof cmp.setValue === 'function') { try { cmp.setValue(value); } catch(e){} }
                            cmp.doQuery(value, true);
                            result.doQuery = 'ok';
                        } catch (e5) { result.doQuery = 'error:' + e5.message; }
                    } else { result.doQuery = 'no_cmp'; }
                    try {
                        el.focus();
                        el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                        const lastChar = value && value.length ? value.charAt(value.length - 1) : '0';
                        el.dispatchEvent(new KeyboardEvent('keyup', {
                            key: lastChar, code: 'Digit' + lastChar,
                            bubbles: true, cancelable: true,
                        }));
                        el.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                        result.fallback = 'dispatched';
                    } catch (e6) { result.fallback = 'error:' + e6.message; }
                    return result;
                }""",
                masked,
            )
            logger.info(
                "AJUS runner: doQuery trigger pra %s -> %s",
                masked, doquery_status,
            )
        except Exception as exc:
            logger.warning(
                "AJUS runner: falha ao forcar doQuery via JS: %s — "
                "depende do keyup nativo.", exc,
            )

    def _is_search_empty_result_visible(self) -> bool:
        """
        Detecta o painel amarelo do AJUS quando a busca rapida retorna
        zero resultados. Markers (texto visivel no DOM):

          1. "Desculpe, mas nenhuma acao foi encontrada com os termos
             pesquisados!" (caixa amarela de aviso)
          2. "Nao ha registros para exibir" (rodape da paginacao)

        Os 2 aparecem juntos quando a busca resolve sem hits. Detectar
        QUALQUER um dos 2 eh suficiente — o outro eh redundante.

        Robusto a acentuacao: testa com e sem acento (alguns ambientes
        do AJUS retornam UTF-8 sem acento dependendo do encoding).
        """
        markers = [
            # Caixa amarela — eh a mais visivel e proxima ao input
            "text=Desculpe, mas nenhuma",
            "text=nenhuma ação foi encontrada",
            "text=nenhuma acao foi encontrada",
            # Paginacao vazia — fallback secundario
            "text=Não há registros para exibir",
            "text=Nao ha registros para exibir",
        ]
        for sel in markers:
            try:
                if self._is_visible(sel):
                    return True
            except Exception:
                continue
        return False

    def _find_process_result(self, cnj: str, search_input=None):
        """
        Acha o item do dropdown que matcheia o CNJ. Estrategia (Mirror):
          1. Selector template configurado.
          2. Fallback xpath generico.
          3. Fallback `text={cnj}` simples.

        Logging detalhado pra depurar quando o dropdown nao aparece:
          - Aos 30s (meio do timeout): screenshot intermediario + estado.
          - Aos 60s (timeout): screenshot final + estado completo
            (input value, store ExtJS, HTML do dropdown, contagens por
            selector candidato, ultima request XHR de busca).
        """
        # Gera candidatos pra ambos os formatos: mascarado (forma
        # canonica que o AJUS renderiza no DOM) e raw (defensive,
        # caso algum nodo tenha o numero sem mascara).
        masked = _format_cnj_mask(cnj)
        raw = _cnj_digits(cnj)
        forms = []
        if masked:
            forms.append(masked)
        if raw and raw != masked:
            forms.append(raw)

        candidates = []
        for form in forms:
            candidates.append(
                portal.PROCESS_RESULT_SELECTOR_TEMPLATE.format(process_number=form),
            )
            candidates.append(
                portal.PROCESS_RESULT_FALLBACK_SELECTOR_TEMPLATE.format(process_number=form),
            )
            candidates.append(f"text={form}")
        # Fallback adicional: card/grid (AJUS pode renderizar como
        # Ext.grid em vez de combo-list em alguns casos)
        for form in forms:
            candidates.append(
                f"xpath=(//div[contains(@class,'x-grid-row') or contains(@class,'x-grid-data-row')]"
                f"//*[contains(normalize-space(.), '{form}')])[1]",
            )

        # Hook em network.response pra capturar a resposta da busca.
        # AJUS bate em /ajax.handler.php?ajax=BuscaRapidaController.php
        # — separamos o capture em 2 niveis: o que CASA com BuscaRapida
        # (XHR oficial da busca) tem prioridade; outros XHRs do
        # ajax.handler ficam em fallback (workspace housekeeping).
        last_search_response: dict[str, str] = {}
        last_other_response: dict[str, str] = {}

        def _store(target: dict, response):
            try:
                target["url"] = response.url or ""
                target["status"] = str(response.status)
                try:
                    body = response.text()[:500]
                except Exception:
                    body = "(body indisponivel)"
                target["body"] = body
            except Exception:
                pass

        def _capture_response(response):
            try:
                url = (response.url or "").lower()
                if not url:
                    return
                # Prioridade 1: XHR EXATO da busca rapida.
                if "buscarapida" in url or "buscaracaojudicial" in url:
                    _store(last_search_response, response)
                    return
                # Prioridade 2: outros XHRs do ajax.handler — fallback.
                if any(
                    fragment in url
                    for fragment in (
                        "ajax.handler.php", "buscar", "search", "processo",
                    )
                ):
                    _store(last_other_response, response)
            except Exception:
                pass

        try:
            self._page.on("response", _capture_response)
        except Exception:
            pass

        try:
            # Da um primeiro grace de 3s pra busca resolver — antes
            # disso o painel "sem resultados" pode nao ter renderizado
            # ainda e a gente perde tempo.
            grace_deadline = time.monotonic() + 3
            while time.monotonic() < grace_deadline:
                for sel in candidates:
                    if self._is_visible(sel):
                        return self._visible_locator(sel, timeout_s=3)
                self._page.wait_for_timeout(300)

            deadline = time.monotonic() + 57  # total ~60s incluindo grace
            mid_dump_done = False
            mid_deadline = time.monotonic() + 27
            while time.monotonic() < deadline:
                for sel in candidates:
                    if self._is_visible(sel):
                        return self._visible_locator(sel, timeout_s=3)

                # Detecta painel "AJUS nao encontrou o processo" —
                # raise NotFound IMEDIATAMENTE (nao espera timeout final).
                # Marcadores observados: texto explicito + paginacao vazia.
                if self._is_search_empty_result_visible():
                    raise AjusProcessNotFoundError(
                        f"AJUS retornou 'sem resultados' pra CNJ {cnj}. "
                        f"Processo provavelmente nao esta cadastrado nesse "
                        f"sistema."
                    )

                # Dump intermediario aos 30s — captura estado quando o
                # AJUS ainda esta processando a busca, ajuda a entender
                # se o resultado *apareceu* e sumiu antes do timeout.
                if not mid_dump_done and time.monotonic() >= mid_deadline:
                    try:
                        self._dump_search_state(
                            "search-result-mid-timeout",
                            cnj=cnj,
                            candidates=candidates,
                            search_input=search_input,
                            last_search_response=last_search_response,
                            last_other_response=last_other_response,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "AJUS runner: falha no dump intermediario: %s", exc,
                        )
                    mid_dump_done = True

                self._page.wait_for_timeout(500)

            # Timeout final — dump completo
            debug = self._dump_search_state(
                "search-result-not-found",
                cnj=cnj,
                candidates=candidates,
                search_input=search_input,
                last_search_response=last_search_response,
                last_other_response=last_other_response,
            )
            raise AjusRunnerError(
                f"Resultado da busca pra CNJ {cnj} nao apareceu. {debug}",
            )
        finally:
            try:
                self._page.remove_listener("response", _capture_response)
            except Exception:
                pass

    def _dump_search_state(
        self,
        label: str,
        *,
        cnj: str,
        candidates: list[str],
        search_input=None,
        last_search_response: Optional[dict] = None,
        last_other_response: Optional[dict] = None,
    ) -> str:
        """
        Dump rico do estado da busca — screenshot + URL + titulo +
        valor do input + store ExtJS + HTML do dropdown + contagens
        por selector + ultima resposta XHR.

        Usado em 2 momentos:
          - Aos 30s: sinaliza que esta lento (mid-timeout).
          - Aos 60s: timeout final (search-result-not-found).
        """
        # Reusa o screenshot + URL + title do _dump_login_state
        base_debug = self._dump_login_state(label)

        # Coleta extras
        extras: list[str] = []

        # 1. Valor real do input de busca — comparar contra ambas as
        # formas (mascarada e crua) pra dar resultado correto sem
        # falso-positivo de "DIFERENTE" quando o input ta no formato certo.
        try:
            if search_input is not None:
                actual_value = search_input.input_value(timeout=2000)
                masked_form = _format_cnj_mask(cnj)
                raw_form = _cnj_digits(cnj)
                if actual_value == masked_form:
                    extras.append(f"input_value={actual_value!r} OK (mascarado)")
                elif actual_value == raw_form:
                    extras.append(f"input_value={actual_value!r} OK (cru)")
                elif _cnj_digits(actual_value) == raw_form:
                    extras.append(
                        f"input_value={actual_value!r} OK (mesmos digitos, "
                        f"formato diferente)"
                    )
                else:
                    extras.append(
                        f"input_value={actual_value!r} DIFERENTE — "
                        f"esperado mascarado={masked_form!r} ou raw={raw_form!r}. "
                        f"Possivel perda de caractere."
                    )
        except Exception as exc:  # noqa: BLE001
            extras.append(f"input_value=ERRO({exc})")

        # 2. Estado do store ExtJS — count, lastQuery, isLoading
        try:
            store_state = self._page.evaluate(
                """() => {
                    if (!window.Ext) return { error: 'Ext nao definido' };
                    // ExtJS antigo do AJUS nao tem ComponentQuery.query —
                    // fallback: ComponentMgr.all (Ext 3) ou ComponentManager (Ext 4+).
                    let combos = [];
                    try {
                        if (Ext.ComponentQuery && typeof Ext.ComponentQuery.query === 'function') {
                            combos = Ext.ComponentQuery.query('combobox');
                        } else if (Ext.ComponentMgr && Ext.ComponentMgr.all) {
                            const all = Ext.ComponentMgr.all.items || Object.values(Ext.ComponentMgr.all);
                            combos = (all || []).filter(c => c && c.store && typeof c.doQuery === 'function');
                        } else if (Ext.ComponentManager && Ext.ComponentManager.all) {
                            const all = Ext.ComponentManager.all.items || Object.values(Ext.ComponentManager.all);
                            combos = (all || []).filter(c => c && c.store && typeof c.doQuery === 'function');
                        }
                    } catch (e) { return { error: 'fallback-failed: ' + e.message }; }
                    const result = [];
                    for (const cb of combos) {
                        if (!cb || !cb.store) continue;
                        try {
                            result.push({
                                id: cb.id,
                                count: cb.store.getCount(),
                                lastQuery: (cb.store.lastOptions && cb.store.lastOptions.params && cb.store.lastOptions.params.query) || cb.lastQuery || null,
                                isLoading: typeof cb.store.isLoading === 'function' ? cb.store.isLoading() : false,
                            });
                        } catch (e) {}
                    }
                    return result.slice(0, 10);
                }"""
            )
            extras.append(f"ext_combos={store_state}")
        except Exception as exc:  # noqa: BLE001
            extras.append(f"ext_combos=ERRO({exc})")

        # 3. HTML do dropdown (.x-boundlist) — mostra "Nenhum resultado"
        try:
            dropdown_html = self._page.evaluate(
                """() => {
                    const lists = document.querySelectorAll('.x-boundlist');
                    const visible = [];
                    for (const el of lists) {
                        if (el.offsetParent !== null) {
                            visible.push({
                                items_count: el.querySelectorAll('.x-boundlist-item').length,
                                empty_text: el.querySelector('.x-boundlist-empty-area')?.textContent?.trim() || null,
                                inner_text: (el.innerText || '').slice(0, 200),
                            });
                        }
                    }
                    return visible;
                }"""
            )
            extras.append(f"boundlist={dropdown_html}")
        except Exception as exc:  # noqa: BLE001
            extras.append(f"boundlist=ERRO({exc})")

        # 4. Contagem por selector candidato (count > 0 mas nao visivel
        #    significa que o elemento existe mas esta hidden)
        try:
            counts = []
            for sel in candidates:
                try:
                    c = self._page.locator(sel).count()
                    counts.append(f"{sel!r}=count={c}")
                except Exception:
                    counts.append(f"{sel!r}=ERRO")
            extras.append(f"selector_counts=[{' | '.join(counts)}]")
        except Exception as exc:  # noqa: BLE001
            extras.append(f"selector_counts=ERRO({exc})")

        # 5. Ultima resposta de busca (HTTP) — prioriza BuscaRapida
        if last_search_response:
            extras.append(f"last_xhr_search={last_search_response}")
        elif last_other_response:
            extras.append(
                f"last_xhr_search=(nao capturada — XHR de busca NAO disparou). "
                f"Outro XHR recente: {last_other_response}"
            )
        else:
            extras.append("last_xhr=(nenhuma request capturada)")

        full = base_debug + " | " + " | ".join(extras)
        logger.error("AJUS runner DEBUG[%s] cnj=%s extras: %s", label, cnj, " | ".join(extras))
        return full

    def _open_process_by_cnj(self, cnj: str) -> None:
        """
        Abre a tela do processo no AJUS via busca rapida (porte fiel
        do `_open_process` do Mirror).

        Sequencia:
          1. Aguarda workspace ready (45s).
          2. Acha o input de busca rapida (com fallbacks).
          3. Clica e digita o CNJ caractere por caractere (delay=35ms).
          4. Espera 2s pelo AJUS resolver no store.
          5. Acha o resultado e da DOUBLE-CLICK (nao single).
          6. Settle 2s.
        """
        # Etapa 1: workspace ready
        self._wait_for_workspace_ready(timeout_ms=45_000)

        # Etapa 2 + 3: input + digita
        search_input = self._find_process_search_input()
        try:
            search_input.click()
        except Exception:
            try:
                search_input.click(force=True)
            except Exception:
                pass
        self._type_process_search(search_input, cnj)

        # Etapa 4: AJUS resolve a busca
        self._page.wait_for_timeout(2000)

        # Etapa 5: dblclick no resultado
        result = self._find_process_result(cnj, search_input=search_input)
        try:
            result.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            result.dblclick()
        except Exception:
            try:
                result.dblclick(force=True)
            except Exception:
                # Fallback: dispara dblclick via JS
                result.evaluate(
                    "element => element.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }))"
                )

        self._settle(wait_ms=2000)

    # ── Preenchimento de campos ExtJS (porte do Mirror) ───────────

    def _associated_visible_input_id(self, locator) -> Optional[str]:
        """
        Pra um input hidden ExtJS, retorna o id do input "companheiro"
        visivel (mesmo wrapper). ExtJS guarda valor real no hidden e
        display no visivel.
        """
        try:
            companion_id = locator.evaluate(
                """element => {
                    const wrapper =
                        element.closest('.x-form-field-wrap, .x-form-element, .x-trigger-wrap-focus') ||
                        element.parentElement;
                    if (!wrapper) return '';
                    const visible = Array.from(wrapper.querySelectorAll('input, textarea')).find(
                        candidate =>
                            candidate !== element &&
                            candidate.type !== 'hidden' &&
                            candidate.offsetParent !== null
                    );
                    return visible?.id || '';
                }"""
            )
            return companion_id or None
        except Exception:
            return None

    def _is_ext_combo(self, locator) -> bool:
        """Detecta se o elemento eh um combobox ExtJS (tem store + doQuery)."""
        try:
            return bool(
                locator.evaluate(
                    """element => {
                        const cmp = element?.id && window.Ext ? Ext.getCmp(element.id) : null;
                        return !!cmp && !!cmp.store && typeof cmp.doQuery === 'function' && !!cmp.displayField;
                    }"""
                )
            )
        except Exception:
            return False

    def _set_ext_component_value(self, locator, value: str) -> bool:
        """
        Set value via Ext.getCmp(id).setValue(). Disparas eventos
        input/change/blur. Trata caso especial de date. Retorna True
        se conseguiu setar e o valor foi confirmado.
        """
        try:
            return bool(
                locator.evaluate(
                    """(element, desiredValue) => {
                        if (!element || !window.Ext) return false;
                        const wrapper =
                            element.closest('.x-form-field-wrap, .x-form-element, .x-trigger-wrap-focus') ||
                            element.parentElement;
                        const candidates = [];
                        const push = c => { if (c && !candidates.includes(c)) candidates.push(c); };
                        push(element);
                        push(element.previousElementSibling);
                        push(element.nextElementSibling);
                        if (wrapper) {
                            Array.from(wrapper.querySelectorAll('input, textarea')).forEach(push);
                        }
                        let cmp = null;
                        let cmpInput = null;
                        for (const c of candidates) {
                            const id = c?.id || '';
                            if (!id) continue;
                            const current = Ext.getCmp(id);
                            if (current && typeof current.setValue === 'function') {
                                cmp = current; cmpInput = c; break;
                            }
                        }
                        if (!cmp) return false;
                        const visibleTargets = [];
                        const hiddenTargets = [];
                        const remember = (b, c) => { if (c && !b.includes(c)) b.push(c); };
                        const rawValue = String(desiredValue ?? '');
                        if (wrapper) {
                            for (const c of wrapper.querySelectorAll('input, textarea')) {
                                if (c instanceof HTMLInputElement && c.type === 'hidden') remember(hiddenTargets, c);
                                else remember(visibleTargets, c);
                            }
                        }
                        remember(visibleTargets, cmpInput);
                        const dispatch = n => {
                            n?.dispatchEvent?.(new Event('input', { bubbles: true }));
                            n?.dispatchEvent?.(new Event('change', { bubbles: true }));
                            n?.dispatchEvent?.(new Event('blur', { bubbles: true }));
                        };
                        const setNV = (n, v) => { if (n) { n.value = v; dispatch(n); } };
                        try {
                            cmp.clearInvalid?.(); cmp.clearValue?.(); cmp.setRawValue?.('');
                            cmp.lastQuery = null;
                        } catch (e) {}
                        visibleTargets.forEach(n => setNV(n, ''));
                        hiddenTargets.forEach(n => setNV(n, ''));
                        const xtype = String(cmp.xtype || cmp.constructor?.xtype || '').toLowerCase();
                        const looksLikeDate = xtype.includes('date') ||
                            hiddenTargets.some(n => /data(evento|agendamento|fatal)/i.test(n.name || '')) ||
                            visibleTargets.some(n => String(n.className || '').includes('x-form-date'));
                        try {
                            cmp.setValue?.(rawValue);
                            cmp.setRawValue?.(rawValue);
                            cmp.validate?.(); cmp.triggerBlur?.();
                            cmp.fireEvent?.('change', cmp, cmp.getValue?.(), null);
                            cmp.fireEvent?.('blur', cmp);
                        } catch (e) { return false; }
                        if (!looksLikeDate) {
                            hiddenTargets.forEach(n => setNV(n, rawValue));
                            if (cmp.hiddenField) setNV(cmp.hiddenField, rawValue);
                        }
                        for (const n of visibleTargets) {
                            if (String(n.value || '').trim() !== rawValue) setNV(n, rawValue);
                        }
                        const cv = cmp.getValue?.();
                        const dateOk = !looksLikeDate || (cv instanceof Date && !Number.isNaN(cv.getTime()));
                        const cd = String(cmp.getRawValue ? cmp.getRawValue() : '').trim() ||
                            String(visibleTargets.find(n => String(n.value || '').trim())?.value || '').trim();
                        return dateOk && cd === rawValue;
                    }""",
                    value,
                )
            )
        except Exception:
            return False

    def _select_ext_combo_value(self, locator, value: str) -> bool:
        """
        Seleciona valor num combobox ExtJS via JS evaluate. Faz query
        no store, encontra record matching pelo displayField, chama
        cmp.onSelect/cmp.select. Fallback pra picker visivel se falhar.
        """
        try:
            selected = bool(
                locator.evaluate(
                    """(element, desiredValue) => {
                        const normalize = s => (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().trim();
                        const id = element?.id || "";
                        const cmp = id && window.Ext ? Ext.getCmp(id) : null;
                        if (!cmp || !cmp.store || typeof cmp.doQuery !== "function" || !cmp.displayField) return false;
                        const target = normalize(desiredValue);
                        const store = cmp.store;
                        const wrapper = element.closest('.x-form-field-wrap, .x-form-element, .x-trigger-wrap-focus') || element.parentElement;
                        const visibleInput = wrapper ? Array.from(wrapper.querySelectorAll('input, textarea')).find(c => c.type !== 'hidden' && c.offsetParent !== null) : null;
                        const hiddenInputs = wrapper ? Array.from(wrapper.querySelectorAll('input[type="hidden"]')) : [];
                        const dispatch = n => {
                            n?.dispatchEvent?.(new Event('input', { bubbles: true }));
                            n?.dispatchEvent?.(new Event('change', { bubbles: true }));
                            n?.dispatchEvent?.(new Event('blur', { bubbles: true }));
                        };
                        const setNV = (n, v) => { if (n) { n.value = v; dispatch(n); } };
                        const clearState = () => {
                            try {
                                cmp.clearInvalid?.(); cmp.clearValue?.(); cmp.setRawValue?.('');
                                cmp.lastSelectionText = ''; cmp.lastQuery = null;
                            } catch (e) {}
                            setNV(visibleInput, '');
                            hiddenInputs.forEach(n => setNV(n, ''));
                            if (cmp.hiddenField) setNV(cmp.hiddenField, '');
                        };
                        const findRecord = allowContains => {
                            const count = store.getCount ? store.getCount() : 0;
                            let containsMatch = null;
                            for (let i = 0; i < count; i += 1) {
                                const r = store.getAt(i); if (!r) continue;
                                const display = normalize(r.get?.(cmp.displayField) ?? r.data?.[cmp.displayField]);
                                if (!display) continue;
                                if (display === target) return { record: r, index: i, exact: true };
                                if (allowContains && !containsMatch && (display.includes(target) || target.includes(display))) {
                                    containsMatch = { record: r, index: i, exact: false };
                                }
                            }
                            return containsMatch;
                        };
                        const applyRecord = m => {
                            if (!m || !m.record) return false;
                            try {
                                const { record, index } = m;
                                const rawValue = String(record.get?.(cmp.displayField) ?? record.data?.[cmp.displayField] ?? desiredValue).trim();
                                const storedValue = record.get?.(cmp.valueField) ?? record.data?.[cmp.valueField] ?? rawValue;
                                cmp.expand?.();
                                if (typeof cmp.onSelect === "function") cmp.onSelect(record, index ?? 0);
                                else if (typeof cmp.select === "function") cmp.select(record, true);
                                else { cmp.setValue?.(storedValue); cmp.setRawValue?.(rawValue); }
                                cmp.lastSelectionText = rawValue;
                                setNV(visibleInput, rawValue);
                                hiddenInputs.forEach(n => setNV(n, String(storedValue ?? '')));
                                if (cmp.hiddenField) setNV(cmp.hiddenField, String(storedValue ?? ''));
                                cmp.assertValue?.();
                                cmp.fireEvent?.("select", cmp, record, index ?? 0);
                                cmp.fireEvent?.("change", cmp, storedValue, null);
                                cmp.collapse?.(); cmp.triggerBlur?.();
                                const cd = normalize(cmp.getRawValue ? cmp.getRawValue() : "") || normalize(visibleInput?.value || "");
                                return cd === target;
                            } catch (e) { return false; }
                        };
                        return new Promise(resolve => {
                            let finished = false;
                            const finish = r => {
                                if (finished) return;
                                finished = true;
                                try { store.un?.("load", onLoad); } catch (e) {}
                                clearTimeout(timeoutId);
                                resolve(r);
                            };
                            const trySelect = ac => {
                                const m = findRecord(ac);
                                if (applyRecord(m)) finish(true);
                            };
                            const onLoad = () => setTimeout(() => trySelect(false), 120);
                            const timeoutId = setTimeout(() => finish(false), 5000);
                            try {
                                store.on?.("load", onLoad);
                                clearState(); cmp.expand?.(); cmp.onTriggerClick?.();
                                cmp.setRawValue?.(desiredValue);
                                cmp.lastQuery = null;
                                cmp.doQuery?.(desiredValue, false);
                                setTimeout(() => {
                                    if (finished) return;
                                    trySelect(false);
                                    if (finished) return;
                                    cmp.lastQuery = null;
                                    cmp.doQuery?.(desiredValue, true);
                                    setTimeout(() => {
                                        if (!finished) {
                                            trySelect(true);
                                            if (!finished) finish(false);
                                        }
                                    }, 250);
                                }, 250);
                            } catch (e) { finish(false); }
                        });
                    }""",
                    value,
                )
            )
            if selected:
                return True
        except Exception:
            pass
        # Fallback: tenta clicar no item visivel da picker (boundlist)
        return self._select_ext_combo_value_from_visible_picker(locator, value)

    def _select_ext_combo_value_from_visible_picker(self, locator, value: str) -> bool:
        """
        Fallback pro combobox: abre o dropdown e clica no item pelo
        texto visivel. Usado quando o JS evaluate falha.
        """
        target = _normalize_text(value)
        try:
            locator.click()
        except Exception:
            try: locator.click(force=True)
            except Exception: return False
        self._page.wait_for_timeout(400)
        # Procura items na boundlist visivel
        items = self._page.locator(
            "xpath=//div[contains(@class,'x-boundlist') "
            "and not(contains(@style,'display:none')) "
            "and not(contains(@style,'visibility: hidden'))]"
            "//*[contains(@class,'x-boundlist-item') or contains(@class,'x-combo-list-item')]"
        )
        try:
            count = items.count()
        except Exception:
            count = 0
        for i in range(count):
            item = items.nth(i)
            try:
                if not item.is_visible():
                    continue
                if _normalize_text(item.inner_text()) != target:
                    continue
                try: item.scroll_into_view_if_needed(timeout=2000)
                except Exception: pass
                try: item.click()
                except Exception: item.click(force=True)
                self._page.wait_for_timeout(500)
                return True
            except Exception:
                continue
        return False

    def _fill_field(self, label: str, selector: str, value: str) -> None:
        """
        Preenche UM campo da capa (porte do Mirror `_fill_field`).
        Decide o caminho:
          - <select> nativo: select_option.
          - Combobox ExtJS: _select_ext_combo_value (com fallback picker).
          - Input texto: scroll + click + remove readonly + Control+A +
            Delete + press_sequentially(delay=35) + Enter + Tab.
        """
        locator = self._visible_locator(selector)
        try:
            tag_name = locator.evaluate("element => element.tagName.toLowerCase()")
        except Exception:
            tag_name = ""

        if tag_name == "select":
            try: locator.select_option(label=value)
            except Exception: locator.select_option(value=value)
            return

        if self._is_ext_combo(locator):
            if self._select_ext_combo_value(locator, value):
                self._page.wait_for_timeout(400)
                return
            raise AjusRunnerError(
                f"Nao consegui selecionar '{value}' no campo {label} (combobox ExtJS).",
            )

        # Input de texto comum
        try: locator.scroll_into_view_if_needed(timeout=3000)
        except Exception: pass
        locator.click()
        try:
            locator.evaluate(
                """element => {
                    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
                        element.readOnly = false;
                    }
                }"""
            )
        except Exception:
            pass
        try:
            self._page.keyboard.press("Control+A")
            self._page.keyboard.press("Delete")
        except Exception:
            pass
        try: locator.fill("")
        except Exception: pass
        try: locator.press_sequentially(value, delay=35)
        except Exception: self._page.keyboard.type(value, delay=35)
        self._page.wait_for_timeout(700)
        try: self._page.keyboard.press("Enter")
        except Exception: pass
        self._page.wait_for_timeout(400)
        self._page.keyboard.press("Tab")

    def _wait_for_process_cover_dependency(self, label: str, selector: str) -> None:
        """
        Aguarda um campo dependente ficar visivel (ex.: Comarca depende
        de UF estar setada — o AJUS so habilita Comarca depois).
        """
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            loc = self._page.locator(selector)
            try:
                if loc.count() and loc.first.is_visible():
                    self._page.wait_for_timeout(250)
                    return
            except Exception:
                pass
            self._page.wait_for_timeout(250)
        raise AjusRunnerError(
            f"Campo dependente '{label}' nao ficou visivel no AJUS apos o anterior.",
        )

    def _read_locator_display_value(self, locator) -> str:
        """
        Le o display value de um campo. Pra inputs/textarea/select usa
        input_value(); pra outros elementos usa inner_text(). NAO usa
        Ext.getCmp.getRawValue() porque o display visual ja eh o que
        precisamos comparar.
        """
        try:
            tag_name = locator.evaluate("element => element.tagName.toLowerCase()")
        except Exception:
            tag_name = ""
        if tag_name in {"input", "textarea", "select"}:
            try:
                return (locator.input_value() or "").strip()
            except Exception:
                pass
        try:
            return (locator.inner_text() or "").strip()
        except Exception:
            return ""

    def _read_field_display_value(self, selector: str) -> str:
        loc = self._locator(selector)
        return self._read_locator_display_value(loc)

    # ── Atualizacao da capa do processo ────────────────────────────

    def _update_process_cover(self, item: AjusClassificacaoQueue) -> None:
        """
        Preenche os 5 campos da capa via _fill_field (porte fiel do
        Mirror `_update_process_fields`).

        Ordem importa: UF antes de Comarca (Comarca depende de UF).
        """
        for required, value in [
            ("UF", item.uf),
            ("Comarca", item.comarca),
            ("Materia", item.matter),
            ("Justica/Honorario", item.justice_fee),
            ("Risco/Prob. Perda", item.risk_loss_probability),
        ]:
            if not value or not value.strip():
                raise AjusRunnerError(
                    f"Item {item.id} sem `{required}` preenchido — "
                    f"operador precisa editar antes do dispatch.",
                )

        self._fill_field("UF", portal.PROCESS_UF_SELECTOR, item.uf)
        # Comarca depende de UF estar setada — espera ela ficar habilitada
        self._wait_for_process_cover_dependency("Comarca", portal.PROCESS_COMARCA_SELECTOR)
        self._fill_field("Comarca", portal.PROCESS_COMARCA_SELECTOR, item.comarca)
        self._fill_field("Materia", portal.PROCESS_MATTER_SELECTOR, item.matter)
        self._fill_field("Justica/Honorario", portal.PROCESS_JUSTICE_FEE_SELECTOR, item.justice_fee)
        self._fill_field("Risco/Prob. Perda", portal.PROCESS_RISK_SELECTOR, item.risk_loss_probability)

        # Salvar
        self._click(portal.PROCESS_SAVE_SELECTOR)
        self._settle(wait_ms=1500)

    def _validate_process_cover(self, item: AjusClassificacaoQueue) -> None:
        """
        Re-le os 5 campos da capa apos save e compara com expected.
        Usa _read_field_display_value (display visual normalizado).
        """
        actual = {
            "UF": self._read_field_display_value(portal.PROCESS_UF_SELECTOR),
            "Comarca": self._read_field_display_value(portal.PROCESS_COMARCA_SELECTOR),
            "Materia": self._read_field_display_value(portal.PROCESS_MATTER_SELECTOR),
            "Justica/Honorario": self._read_field_display_value(portal.PROCESS_JUSTICE_FEE_SELECTOR),
            "Risco/Prob. Perda": self._read_field_display_value(portal.PROCESS_RISK_SELECTOR),
        }
        expected = {
            "UF": item.uf or "",
            "Comarca": item.comarca or "",
            "Materia": item.matter or "",
            "Justica/Honorario": item.justice_fee or "",
            "Risco/Prob. Perda": item.risk_loss_probability or "",
        }
        mismatches = []
        for label, exp in expected.items():
            got = actual.get(label, "")
            if _normalize_text(got) != _normalize_text(exp):
                mismatches.append(f"{label}: esperado '{exp}', encontrado '{got}'")
        if mismatches:
            raise AjusRunnerError(
                "Capa nao ficou com os valores esperados apos o save: "
                + " | ".join(mismatches),
            )
