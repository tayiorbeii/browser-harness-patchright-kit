#!/usr/bin/env python3
"""Enforce the project kit's mirror and staged-index invariants."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

# Root files are the working implementation. Templates are distributable snapshots.
# The environment snapshot intentionally substitutes only these four identity values.
ENV_SUBSTITUTIONS = (
    (
        "BH_PROJECT_SLUG=browser_harness_patchright_project_kit",
        "BH_PROJECT_SLUG=my-app",
    ),
    (
        "BH_CONTAINER_NAME=bh-browser_harness_patchright_project_kit",
        "BH_CONTAINER_NAME=bh-my-app",
    ),
    (
        "BH_BU_NAME=browser_harness_patchright_project_kit",
        "BH_BU_NAME=my-app",
    ),
    (
        "BH_PROFILE_VOLUME=bh-browser_harness_patchright_project_kit-profile",
        "BH_PROFILE_VOLUME=bh-my-app-profile",
    ),
)

# (canonical working file, distributable template, allowed substitutions, Git mode)
MIRROR_RULES = (
    (
        ".browser-harness.env.example",
        "templates/.browser-harness.env.template",
        ENV_SUBSTITUTIONS,
        0o100644,
    ),
    (
        "docker-compose.browser-harness.yml",
        "templates/docker-compose.browser-harness.yml",
        (),
        0o100644,
    ),
    (
        "docker/browser-harness-patchright/Dockerfile",
        "templates/docker/browser-harness-patchright/Dockerfile",
        (),
        0o100644,
    ),
    (
        "docker/browser-harness-patchright/launch_patchright_cdp.py",
        "templates/docker/browser-harness-patchright/launch_patchright_cdp.py",
        (),
        0o100755,
    ),
    ("scripts/bh", "templates/scripts/bh", (), 0o100755),
    ("scripts/oracle", "templates/scripts/oracle", (), 0o100755),
    ("scripts/oracle-lane", "templates/scripts/oracle-lane", (), 0o100755),
    (".oracle/config.json", "templates/.oracle/config.json", (), 0o100644),
    (
        ".codex/skills/browser-harness/SKILL.md",
        "templates/skills/browser-harness/SKILL.md",
        (),
        0o100644,
    ),
)

# These files implement and prove the hook contract. The hook requires their
# staged bytes and regular-file modes to match the copies it is executing.
REQUIRED_INFRASTRUCTURE = {
    ".githooks/pre-commit": 0o100755,
    "scripts/check_repository_integrity.py": 0o100755,
    "scripts/test-repository-integrity": 0o100755,
}

FORBIDDEN_STATE_COMPONENTS = frozenset(
    {".pi", ".pi-subagents", ".browser-harness"}
)
FORBIDDEN_ARTIFACT_NAMES = frozenset({"commit.json", "report.md"})
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".ppk")
LOCAL_SECRET_SUFFIXES = (".local", ".secret", ".secrets")
PRIVATE_KEY_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
SANITIZED_ENV_SUFFIXES = (".example", ".template")


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _materialize_template(
    canonical_text: str,
    substitutions: Sequence[tuple[str, str]],
    canonical_path: str,
) -> tuple[str, list[str]]:
    lines = canonical_text.splitlines(keepends=True)
    errors: list[str] = []
    for canonical_value, template_value in substitutions:
        matches = [
            index
            for index, line in enumerate(lines)
            if line.rstrip("\r\n") == canonical_value
        ]
        if len(matches) != 1:
            errors.append(
                f"{canonical_path}: expected exactly one normalization line "
                f"{canonical_value!r}, found {len(matches)}"
            )
            continue
        index = matches[0]
        newline = lines[index][len(lines[index].rstrip("\r\n")) :]
        lines[index] = template_value + newline
    return "".join(lines), errors


def _read_repository_file(root: Path, name: str, cached: bool) -> tuple[bytes, int]:
    if not cached:
        path = root / name
        try:
            file_stat = path.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(name) from None
        mode = stat.S_IFMT(file_stat.st_mode) | stat.S_IMODE(file_stat.st_mode)
        content = path.read_bytes() if stat.S_ISREG(file_stat.st_mode) else b""
        return content, mode

    entry = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", name],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if not entry:
        raise FileNotFoundError(name)
    mode = int(entry.split(maxsplit=1)[0], 8)
    content = subprocess.run(
        ["git", "-C", str(root), "show", f":{name}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    return content, mode


def check_mirrors(root: Path, *, cached: bool = False) -> list[str]:
    errors: list[str] = []
    source = "staged index" if cached else "working tree"
    for canonical_name, template_name, substitutions, expected_mode in MIRROR_RULES:
        try:
            canonical_bytes, canonical_mode = _read_repository_file(
                root, canonical_name, cached
            )
            template_bytes, template_mode = _read_repository_file(
                root, template_name, cached
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            missing = exc.filename if isinstance(exc, FileNotFoundError) else "mirror entry"
            errors.append(f"missing {source} mirror file: {missing}")
            continue

        for name, actual_mode in (
            (canonical_name, canonical_mode),
            (template_name, template_mode),
        ):
            if actual_mode != expected_mode:
                errors.append(
                    f"mirror mode drift in {source}: {name} has {actual_mode:o}; "
                    f"expected regular-file mode {expected_mode:o}"
                )

        if substitutions:
            try:
                canonical_text = canonical_bytes.decode("utf-8")
                template_text = template_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                errors.append(f"mirror is not UTF-8 text in {source}: {exc}")
                continue
            expected, normalization_errors = _materialize_template(
                canonical_text, substitutions, canonical_name
            )
            errors.extend(normalization_errors)
            if not normalization_errors and template_text != expected:
                errors.append(
                    f"mirror drift in {source}: {template_name} must equal "
                    f"{canonical_name} after the declared environment substitutions"
                )
        elif canonical_bytes != template_bytes:
            errors.append(
                f"mirror drift in {source}: {template_name} must byte-match "
                f"{canonical_name}"
            )
    return errors


def _is_environment_name(name: str) -> bool:
    return (
        name == ".env"
        or name.startswith(".env.")
        or name.endswith(".env")
        or ".env." in name
    )


def forbidden_reason(path: str) -> str | None:
    posix_path = PurePosixPath(path)
    parts = tuple(part.casefold() for part in posix_path.parts)
    if not parts:
        return None

    for part in parts:
        collapsed = re.sub(r"[^a-z0-9]+", "", part)
        if "promptchain" in collapsed:
            return "prompt-chain artifact"

    state_component = next(
        (part for part in parts if part in FORBIDDEN_STATE_COMPONENTS), None
    )
    if state_component is not None:
        return f"local runtime/agent state ({state_component})"

    basename = parts[-1]
    if basename in FORBIDDEN_ARTIFACT_NAMES:
        return "agent run artifact"

    if _is_environment_name(basename) and not basename.endswith(
        SANITIZED_ENV_SUFFIXES
    ):
        return "unsanitized environment file"

    if "secrets" in parts:
        return "secrets directory content"
    if basename.endswith(SECRET_SUFFIXES):
        return "likely private key or certificate material"
    if basename.startswith(PRIVATE_KEY_PREFIXES) and not basename.endswith(".pub"):
        return "likely SSH private key material"
    if basename.endswith(LOCAL_SECRET_SUFFIXES):
        return "local or secret material"
    return None


def index_paths(root: Path) -> Iterable[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    for raw_path in result.stdout.split(b"\0"):
        if raw_path:
            yield os.fsdecode(raw_path)


def check_index(root: Path) -> list[str]:
    errors: list[str] = []
    for path in index_paths(root):
        reason = forbidden_reason(path)
        if reason is not None:
            errors.append(f"forbidden indexed path ({reason}): {path}")

    for name, expected_mode in REQUIRED_INFRASTRUCTURE.items():
        try:
            worktree_bytes, worktree_mode = _read_repository_file(root, name, False)
            index_bytes, index_mode = _read_repository_file(root, name, True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            errors.append(f"required integrity infrastructure is missing from the index: {name}")
            continue
        if worktree_mode != expected_mode or index_mode != expected_mode:
            errors.append(
                f"required integrity infrastructure mode drift: {name} must be "
                f"regular-file mode {expected_mode:o} in both worktree and index"
            )
        if worktree_bytes != index_bytes:
            errors.append(
                f"required integrity infrastructure differs between worktree and index: {name}"
            )
    return errors


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mirrors", action="store_true", help="check all live/template mirror rules"
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="check every path in Git's staged index (including force-added paths)",
    )
    parser.add_argument(
        "--cached-mirrors",
        action="store_true",
        help="read mirror contents and modes from the staged index, not the worktree",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    any_check = args.mirrors or args.index or args.cached_mirrors
    run_mirrors = args.mirrors or args.cached_mirrors or not any_check
    run_index = args.index or not any_check
    root = repository_root()

    errors: list[str] = []
    if run_mirrors:
        errors.extend(check_mirrors(root, cached=args.cached_mirrors))
    if run_index:
        try:
            errors.extend(check_index(root))
        except subprocess.CalledProcessError as exc:
            errors.append(f"could not inspect Git index (exit {exc.returncode})")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            "Repository integrity check failed. Restore mirrors or remove forbidden "
            "artifacts from Git's index.",
            file=sys.stderr,
        )
        return 1

    checks = "/".join(
        name for enabled, name in ((run_mirrors, "mirrors"), (run_index, "index")) if enabled
    )
    print(f"PASS: repository integrity ({checks})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
