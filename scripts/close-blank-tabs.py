#!/usr/bin/env python3
"""Close only about:blank page targets in this project's Patchright container."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUEST_TIMEOUT_SECONDS = 5


def configured_cdp_url() -> str:
    """Use the project's loopback CDP endpoint without loading unrelated env values."""
    explicit_url = os.environ.get("BH_CDP_URL")
    if explicit_url:
        parsed = urlsplit(explicit_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("BH_CDP_URL must be an http loopback URL")
        return explicit_url.rstrip("/")

    port = os.environ.get("BH_HOST_PORT")
    if not port:
        env_file = PROJECT_ROOT / ".browser-harness.env"
        if not env_file.is_file():
            raise FileNotFoundError(f"Missing project CDP configuration: {env_file}")
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "BH_HOST_PORT":
                port = value.strip().strip("\"'")
                break
    if not port or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Could not determine a valid BH_HOST_PORT")
    return f"http://127.0.0.1:{port}"


def close_blank_tabs(cdp_url: str, *, dry_run: bool = False) -> tuple[int, int]:
    """Close `about:blank` page targets; return (closed, failed)."""
    with urlopen(f"{cdp_url}/json/list", timeout=REQUEST_TIMEOUT_SECONDS) as response:
        targets = json.load(response)

    blank_targets = [
        target for target in targets
        if target.get("type") == "page" and target.get("url") == "about:blank"
    ]
    closed = 0
    failed = 0
    for target in blank_targets:
        target_id = target.get("id")
        if not target_id:
            failed += 1
            continue
        if dry_run:
            print(f"Would close blank tab {target_id}")
            continue
        try:
            close_url = f"{cdp_url}/json/close/{quote(target_id, safe='')}"
            with urlopen(close_url, timeout=REQUEST_TIMEOUT_SECONDS):
                pass
            closed += 1
        except URLError as error:
            failed += 1
            print(f"Could not close blank tab {target_id}: {error}", file=sys.stderr)

    return (len(blank_targets) if dry_run else closed), failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list blank tabs without closing them")
    args = parser.parse_args()

    try:
        cdp_url = configured_cdp_url()
        closed, failed = close_blank_tabs(cdp_url, dry_run=args.dry_run)
    except (OSError, ValueError, URLError) as error:
        print(f"Blank-tab cleanup could not reach the browser: {error}", file=sys.stderr)
        return 1

    action = "Would close" if args.dry_run else "Closed"
    print(f"{action} {closed} about:blank tabs; failures: {failed}.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
