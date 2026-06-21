"""Resolvedor automatico de Cloudflare Turnstile via CapSolver ou 2captcha.

Dois backends, mesma interface:
  solver = build_solver("capsolver", api_key="...")
  token = solver.solve_turnstile(params)

`params` = dict colhido da pagina (sitekey/action/cData/chlPageData/pageurl)
via interceptacao de `turnstile.render` (ver TURNSTILE_INTERCEPT_JS).

Chaves tambem via env: CAPSOLVER_API_KEY / TWOCAPTCHA_API_KEY (ou
CAPTCHA_API_KEY como fallback comum).

Dependencias: `capsolver`, `2captcha-python` (pip install -r requirements.txt).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import ClassVar, Optional
from urllib.parse import urlparse


# JS injetado ANTES da navegacao. Faz hook em turnstile.render para capturar os
# parametros do widget (sitekey/action/cData/chlPageData) e guardar o callback,
# para injetar o token resolvido depois.
TURNSTILE_INTERCEPT_JS = r"""
(() => {
  if (window.__cfTurnstileHooked) return;
  window.__cfTurnstileHooked = true;
  window.__cfTurnstileParams = null;
  window.__cfTurnstileCallback = null;
  window.__cfTurnstileToken = null;

  const capture = (opts) => {
    try {
      window.__cfTurnstileParams = {
        sitekey: opts.sitekey || null,
        action: opts.action || null,
        cData: opts.cData || null,
        chlPageData: opts.chlPageData || opts.pagedata || null,
        pageurl: location.href,
      };
      if (typeof opts.callback === 'function') {
        window.__cfTurnstileCallback = opts.callback;
      }
    } catch (e) {}
  };

  const install = () => {
    if (!window.turnstile || window.turnstile.__patched) return false;
    const original = window.turnstile.render;
    window.turnstile.render = function (container, opts) {
      capture(opts || {});
      return original.apply(this, arguments);
    };
    window.turnstile.__patched = true;
    return true;
  };

  if (!install()) {
    const timer = setInterval(() => {
      if (install()) clearInterval(timer);
    }, 50);
    setTimeout(() => clearInterval(timer), 30000);
  }
})();
"""


# JS para injetar o token resolvido: preenche os inputs conhecidos e dispara o
# callback do widget (que e o que faz o Cloudflare validar e seguir).
TURNSTILE_INJECT_JS = r"""
(token) => {
  window.__cfTurnstileToken = token;
  const names = ['cf-turnstile-response', 'g-recaptcha-response'];
  for (const name of names) {
    document.querySelectorAll(`[name="${name}"]`).forEach((el) => {
      el.value = token;
    });
  }
  try {
    if (typeof window.__cfTurnstileCallback === 'function') {
      window.__cfTurnstileCallback(token);
    }
  } catch (e) {}
  return true;
}
"""


class CaptchaError(RuntimeError):
    """Falha ao resolver o captcha (config ausente, timeout, saldo, etc.)."""


@dataclass
class TurnstileParams:
    sitekey: str
    pageurl: str
    action: Optional[str] = None
    cdata: Optional[str] = None
    chl_page_data: Optional[str] = None
    user_agent: Optional[str] = None

    @classmethod
    def from_page(cls, raw: dict, user_agent: Optional[str] = None) -> "TurnstileParams":
        raw = raw or {}
        sitekey = (raw.get("sitekey") or "").strip()
        pageurl = (raw.get("pageurl") or "").strip()
        if not sitekey or not pageurl:
            raise CaptchaError(
                "Parametros do Turnstile incompletos (sitekey/pageurl ausentes). "
                "O widget pode nao ter sido interceptado."
            )
        return cls(
            sitekey=sitekey,
            pageurl=pageurl,
            action=raw.get("action") or None,
            cdata=raw.get("cData") or None,
            chl_page_data=raw.get("chlPageData") or None,
            user_agent=user_agent or None,
        )


@dataclass
class ProxyConfig:
    """Proxy unico reaproveitado por browser, solver e cloudscraper.

    O cf_clearance fica amarrado ao IP que resolveu o desafio, entao TODOS os
    canais (CapSolver, navegador, HTTP) precisam usar o MESMO proxy.
    """

    scheme: str
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    @classmethod
    def parse(cls, raw: str) -> "ProxyConfig":
        """Aceita 'http://user:pass@host:port', 'host:port' ou 'host:port:user:pass'."""
        raw = (raw or "").strip()
        if not raw:
            raise CaptchaError("Proxy vazio.")

        if "://" in raw:
            parsed = urlparse(raw)
            if not parsed.hostname or not parsed.port:
                raise CaptchaError(f"Proxy invalido: {raw!r} (faltou host/porta).")
            return cls(
                scheme=(parsed.scheme or "http").lower(),
                host=parsed.hostname,
                port=int(parsed.port),
                username=parsed.username or None,
                password=parsed.password or None,
            )

        parts = raw.split(":")
        if len(parts) == 2:
            host, port = parts
            return cls(scheme="http", host=host, port=int(port))
        if len(parts) == 4:
            host, port, username, password = parts
            return cls(scheme="http", host=host, port=int(port), username=username, password=password)
        raise CaptchaError(
            f"Formato de proxy nao reconhecido: {raw!r}. "
            "Use 'http://user:pass@host:port' ou 'host:port[:user:pass]'."
        )

    def playwright(self) -> dict:
        cfg: dict = {"server": f"{self.scheme}://{self.host}:{self.port}"}
        if self.username:
            cfg["username"] = self.username
        if self.password:
            cfg["password"] = self.password
        return cfg

    def requests_url(self) -> str:
        auth = ""
        if self.username:
            auth = self.username
            if self.password:
                auth += f":{self.password}"
            auth += "@"
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    def requests_proxies(self) -> dict:
        url = self.requests_url()
        return {"http": url, "https": url}

    def capsolver_fields(self) -> dict:
        proxy_type = "socks5" if self.scheme.startswith("socks") else "http"
        fields: dict = {
            "proxyType": proxy_type,
            "proxyAddress": self.host,
            "proxyPort": self.port,
        }
        if self.username:
            fields["proxyLogin"] = self.username
        if self.password:
            fields["proxyPassword"] = self.password
        return fields


@dataclass
class CloudflareSolution:
    """Resultado do AntiCloudflareTask: cookie cf_clearance + UA que o gerou."""

    cf_clearance: str
    user_agent: Optional[str] = None
    token: Optional[str] = None
    cookies: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class _Solver:
    api_key: str
    timeout: int = 180
    name: ClassVar[str] = "solver"
    supports_clearance: ClassVar[bool] = False

    def solve_turnstile(self, params: TurnstileParams) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def solve_cloudflare_clearance(  # pragma: no cover - interface
        self,
        url: str,
        proxy: ProxyConfig,
        user_agent: Optional[str] = None,
        html: Optional[str] = None,
    ) -> CloudflareSolution:
        raise CaptchaError(f"{self.name} nao suporta solve de cf_clearance (AntiCloudflareTask).")


class CapSolver(_Solver):
    name = "capsolver"
    supports_clearance = True

    def solve_turnstile(self, params: TurnstileParams) -> str:
        try:
            import capsolver
        except ImportError as exc:
            raise CaptchaError("Pacote 'capsolver' ausente. pip install capsolver") from exc

        capsolver.api_key = self.api_key

        metadata: dict[str, str] = {}
        if params.action:
            metadata["action"] = params.action
        if params.cdata:
            metadata["cdata"] = params.cdata

        task: dict = {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": params.pageurl,
            "websiteKey": params.sitekey,
        }
        if metadata:
            task["metadata"] = metadata

        try:
            solution = capsolver.solve(task)
        except Exception as exc:  # SDK levanta erros variados
            raise CaptchaError(f"CapSolver falhou: {exc}") from exc

        token = (solution or {}).get("token") or (solution or {}).get("gRecaptchaResponse")
        if not token:
            raise CaptchaError(f"CapSolver nao retornou token: {solution!r}")
        return token

    def solve_cloudflare_clearance(
        self,
        url: str,
        proxy: ProxyConfig,
        user_agent: Optional[str] = None,
        html: Optional[str] = None,
    ) -> CloudflareSolution:
        try:
            import capsolver
        except ImportError as exc:
            raise CaptchaError("Pacote 'capsolver' ausente. pip install capsolver") from exc

        if proxy is None:
            raise CaptchaError("AntiCloudflareTask exige proxy (--proxy). cf_clearance fica preso ao IP.")

        capsolver.api_key = self.api_key

        task: dict = {
            "type": "AntiCloudflareTask",
            "websiteURL": url,
        }
        task.update(proxy.capsolver_fields())
        if user_agent:
            task["userAgent"] = user_agent
        if html:
            task["html"] = html

        try:
            solution = capsolver.solve(task)
        except Exception as exc:
            raise CaptchaError(f"CapSolver AntiCloudflareTask falhou: {exc}") from exc

        solution = solution or {}
        cookies = solution.get("cookies") or {}
        # cookies pode vir como dict {nome: valor} ou lista de dicts.
        if isinstance(cookies, list):
            cookies = {
                c.get("name"): c.get("value")
                for c in cookies
                if isinstance(c, dict) and c.get("name")
            }
        cf_clearance = cookies.get("cf_clearance") or solution.get("cf_clearance")
        if not cf_clearance:
            raise CaptchaError(f"CapSolver nao retornou cf_clearance: {solution!r}")

        return CloudflareSolution(
            cf_clearance=cf_clearance,
            user_agent=solution.get("userAgent") or user_agent,
            token=solution.get("token"),
            cookies=cookies,
            raw=solution,
        )


class TwoCaptcha(_Solver):
    name = "2captcha"

    def solve_turnstile(self, params: TurnstileParams) -> str:
        try:
            from twocaptcha import TwoCaptcha as _TwoCaptchaClient
        except ImportError as exc:
            raise CaptchaError(
                "Pacote '2captcha-python' ausente. pip install 2captcha-python"
            ) from exc

        client = _TwoCaptchaClient(self.api_key, defaultTimeout=self.timeout)

        kwargs: dict = {"sitekey": params.sitekey, "url": params.pageurl}
        if params.action:
            kwargs["action"] = params.action
        if params.cdata:
            kwargs["data"] = params.cdata
        if params.chl_page_data:
            kwargs["pagedata"] = params.chl_page_data
        if params.user_agent:
            kwargs["useragent"] = params.user_agent

        try:
            result = client.turnstile(**kwargs)
        except Exception as exc:
            raise CaptchaError(f"2captcha falhou: {exc}") from exc

        token = (result or {}).get("code")
        if not token:
            raise CaptchaError(f"2captcha nao retornou token: {result!r}")
        return token


_PROVIDERS = {
    "capsolver": CapSolver,
    "2captcha": TwoCaptcha,
    "twocaptcha": TwoCaptcha,
}

_ENV_KEYS = {
    "capsolver": ("CAPSOLVER_API_KEY", "CAPTCHA_API_KEY"),
    "2captcha": ("TWOCAPTCHA_API_KEY", "TWO_CAPTCHA_API_KEY", "CAPTCHA_API_KEY"),
}


def resolve_api_key(provider: str, explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit.strip()
    for env_name in _ENV_KEYS.get(provider, ()):  # primeira env preenchida
        value = os.environ.get(env_name)
        if value:
            return value.strip()
    return None


def build_solver(
    provider: str,
    api_key: Optional[str] = None,
    timeout: int = 180,
) -> _Solver:
    provider = (provider or "").strip().casefold()
    factory = _PROVIDERS.get(provider)
    if factory is None:
        raise CaptchaError(
            f"Provider de captcha desconhecido: {provider!r}. "
            f"Use um de: {', '.join(sorted(set(_PROVIDERS)))}."
        )
    key = resolve_api_key(factory.name, api_key)
    if not key:
        envs = " / ".join(_ENV_KEYS.get(factory.name, ()))
        raise CaptchaError(
            f"API key ausente para {factory.name}. "
            f"Passe --captcha-key ou defina {envs}."
        )
    return factory(api_key=key, timeout=timeout)
