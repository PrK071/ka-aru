"""Inicia Chrome/Brave normal para o bridge local do Sakura Mangas.

Usa perfil dedicado e CDP somente em localhost. Nenhum CAPTCHA e contornado:
se o Cloudflare aparecer, conclua a verificacao manualmente e deixe a janela
aberta enquanto o backend estiver usando a fonte Sakura.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


DEFAULT_URL = "https://sakuramangas.org/"
DEFAULT_PORT = 9333


def browser_candidates() -> list[Path]:
    home = Path.home()
    return [
        Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
        home / "AppData/Local/BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        home / "AppData/Local/Google/Chrome/Application/chrome.exe",
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]


def cdp_version(port: int) -> dict | None:
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError):
        return None


def find_browser(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"Navegador nao encontrado: {path}")
    for path in browser_candidates():
        if path.is_file():
            return path
    raise FileNotFoundError("Brave, Chrome ou Edge nao encontrado.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Abre bridge local do Sakura Mangas.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile", default=".sakura-browser-profile")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--browser", default=None, metavar="EXE")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError("--port deve estar entre 1024 e 65535.")

    endpoint = f"http://127.0.0.1:{args.port}"
    if cdp_version(args.port):
        print(f"Bridge Sakura ja ativo: {endpoint}")
        print("Deixe a janela aberta e inicie backend/front normalmente.")
        return 0

    browser = find_browser(args.browser)
    profile = Path(args.profile).expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        str(browser),
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        args.url,
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(command, creationflags=creationflags)

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if cdp_version(args.port):
            print(f"Bridge Sakura ativo: {endpoint}")
            print("Conclua Cloudflare manualmente, mantenha janela aberta, depois use app web.")
            return 0
        time.sleep(0.25)

    print("Navegador abriu, mas endpoint CDP nao respondeu.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
