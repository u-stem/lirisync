"""Fail when a runtime dependency of the worker has a non-allowed license.

Walks the Requires-Dist closure of the installed ``lirisync-worker``
distribution (dev dependency groups are not part of it) and checks each
package against ``scripts/allowed-licenses.json`` at the repository root.
Requirements guarded by an ``extra`` marker are skipped; requirements whose
other markers are false are skipped because they are simply not installed.
"""

from __future__ import annotations

import json
import re
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Protocol

ROOT_DISTRIBUTION = "lirisync-worker"
POLICY_PATH = Path(__file__).resolve().parents[3] / "scripts" / "allowed-licenses.json"

_SPDX_ID = re.compile(r"^[A-Za-z0-9.+-]+$")
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXTRA_MARKER = re.compile(r"\bextra\s*==")

# Only unambiguous classifiers. "BSD License" does not say which BSD variant,
# so it is left unknown and must be resolved with an override.
_CLASSIFIERS = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}


class MetadataLike(Protocol):
    def get(self, name: str, failobj: None = None) -> str | None: ...
    def get_all(self, name: str, failobj: None = None) -> list[str] | None: ...


class _Parser:
    def __init__(self, tokens: list[str], allowed: frozenset[str]) -> None:
        self._tokens = tokens
        self._allowed = allowed
        self._position = 0

    def parse(self) -> bool | None:
        value = self._expr()
        if value is None or self._position != len(self._tokens):
            return None
        return value

    def _peek(self) -> str | None:
        return self._tokens[self._position] if self._position < len(self._tokens) else None

    def _expr(self) -> bool | None:
        value = self._term()
        while value is not None and self._peek() == "OR":
            self._position += 1
            right = self._term()
            value = None if right is None else (value or right)
        return value

    def _term(self) -> bool | None:
        value = self._factor()
        while value is not None and self._peek() == "AND":
            self._position += 1
            right = self._factor()
            value = None if right is None else (value and right)
        return value

    def _factor(self) -> bool | None:
        token = self._peek()
        if token is None:
            return None
        self._position += 1
        if token == "(":
            value = self._expr()
            if self._peek() != ")":
                return None
            self._position += 1
            return value
        if token in {")", "AND", "OR"}:
            return None
        return token in self._allowed


def is_allowed_expression(expression: str, allowed: frozenset[str]) -> bool:
    """True when the SPDX expression is valid and satisfiable with allowed ids only."""
    tokens = expression.replace("(", " ( ").replace(")", " ) ").split()
    if not tokens:
        return False
    for token in tokens:
        if token == "WITH" or (token not in {"(", ")"} and not _SPDX_ID.match(token)):
            return False
    return _Parser(tokens, allowed).parse() is True


def license_of(metadata: MetadataLike) -> str | None:
    """Best-effort SPDX expression for a distribution, or None when unknown."""
    expression = metadata.get("License-Expression")
    if expression:
        return expression.strip()
    plain = (metadata.get("License") or "").strip()
    if plain and _SPDX_ID.match(plain):
        return plain
    for classifier in metadata.get_all("Classifier") or []:
        mapped = _CLASSIFIERS.get(classifier.strip())
        if mapped is not None:
            return mapped
    return None


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _runtime_requirements(metadata: MetadataLike) -> list[str]:
    names: list[str] = []
    for requirement in metadata.get_all("Requires-Dist") or []:
        _, _, marker = requirement.partition(";")
        if _EXTRA_MARKER.search(marker):
            continue
        match = _REQUIREMENT_NAME.match(requirement)
        if match is not None:
            names.append(match.group(1))
    return names


def main() -> int:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    allowed = frozenset(policy["allowed"])
    overrides: dict[str, str] = policy["overrides"]

    queue = _runtime_requirements(distribution(ROOT_DISTRIBUTION).metadata)
    seen: set[str] = set()
    failures: list[str] = []
    while queue:
        name = _normalize(queue.pop(0))
        if name in seen:
            continue
        seen.add(name)
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue  # Environment marker was false for this platform.
        metadata = dist.metadata
        found = overrides.get(f"pypi:{name}") or license_of(metadata)
        if found is None or not is_allowed_expression(found, allowed):
            failures.append(f"{name}=={dist.version}: {found!r}")
        queue.extend(_runtime_requirements(metadata))

    for failure in failures:
        print(f"disallowed license: {failure}", file=sys.stderr)
    print(f"pypi licenses: {len(seen)} runtime packages checked, {len(failures)} failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
