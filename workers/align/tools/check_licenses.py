"""Fail when a runtime dependency of the worker has a non-allowed license.

Walks the Requires-Dist closure of the installed ``lirisync-worker``
distribution (dev dependency groups are not part of it) and checks each
package against ``scripts/allowed-licenses.json`` at the repository root.
Each requirement's environment marker is evaluated for the current platform
(with ``extra`` empty, so extra-gated requirements are false). Requirements
whose marker is false are skipped; every other requirement must be installed
and have an allowed license, otherwise the check fails.

Binary wheels may also bundle native libraries under licenses of their own,
which the package's License-Expression does not cover (numpy lists OpenBLAS
and the GCC runtime in its license file). Those entries are read from the
license files and checked the same way. Only the installed wheel is seen, so
this part fails only on Windows, the platform the app ships for; elsewhere
(macOS and Linux wheels bundle libraries the Windows one does not) it warns.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from importlib.metadata import Distribution, PackageNotFoundError, distribution
from pathlib import Path
from typing import Protocol

from packaging.requirements import Requirement

ROOT_DISTRIBUTION = "lirisync-worker"
SHIPPED_PLATFORM = "win32"
POLICY_PATH = Path(__file__).resolve().parents[3] / "scripts" / "allowed-licenses.json"

_SPDX_ID = re.compile(r"^[A-Za-z0-9.+-]+$")

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


def _join_exceptions(tokens: list[str]) -> list[str] | None:
    """Merge each `id WITH exception` into one token, or None when malformed."""
    joined: list[str] = []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if token == "WITH":
            return None
        if position + 2 < len(tokens) and tokens[position + 1] == "WITH":
            exception = tokens[position + 2]
            if exception in {"(", ")", "AND", "OR", "WITH"} or token in {"(", ")", "AND", "OR"}:
                return None
            joined.append(f"{token} WITH {exception}")
            position += 3
            continue
        if position + 1 < len(tokens) and tokens[position + 1] == "WITH":
            return None
        joined.append(token)
        position += 1
    return joined


def is_allowed_expression(
    expression: str, allowed: frozenset[str], allowed_with: frozenset[str] = frozenset()
) -> bool:
    """True when the SPDX expression is valid and satisfiable with allowed ids only.

    A `WITH` exception is allowed only as a whole pair listed in `allowed_with`,
    so each one is reviewed by a person before it is accepted."""
    tokens = expression.replace("(", " ( ").replace(")", " ) ").split()
    for token in tokens:
        if token not in {"(", ")"} and not _SPDX_ID.match(token):
            return False
    joined = _join_exceptions(tokens)
    if not joined:
        return False
    return _Parser(joined, allowed | allowed_with).parse() is True


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


_FIELD = re.compile(r"^([A-Za-z]+): (.+)$")


def bundled_licenses(text: str) -> list[tuple[str, str]]:
    """(name, license) for each bundled-library entry in a license file.

    An entry is a block of unindented `Field: value` lines that starts with
    `Name:`; its `License:` field is taken. Any other line ends the entry, so a
    `License:` line in free text is not attributed to a library."""
    found: list[tuple[str, str]] = []
    name: str | None = None
    for line in text.splitlines():
        field = _FIELD.match(line)
        if field is None:
            name = None
        elif field[1] == "Name":
            name = field[2].strip()
        elif field[1] == "License" and name is not None:
            found.append((name, field[2].strip()))
            name = None
    return found


def _license_files(dist: Distribution) -> Iterable[str]:
    for path in dist.metadata.get_all("License-File") or []:
        # Core metadata 2.4 keeps license files under `licenses/`.
        text = dist.read_text(f"licenses/{path}") or dist.read_text(path)
        if text is not None:
            yield text


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def active_requirement_names(requirements: Iterable[str]) -> list[str]:
    """Names of the requirements whose marker holds here, ignoring extras."""
    names: list[str] = []
    for line in requirements:
        requirement = Requirement(line)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            names.append(requirement.name)
    return names


def main() -> int:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    allowed = frozenset(policy["allowed"])
    allowed_with = frozenset(policy["allowedWith"])
    overrides: dict[str, str] = policy["overrides"]

    root = distribution(ROOT_DISTRIBUTION)
    queue = active_requirement_names(root.metadata.get_all("Requires-Dist") or [])
    seen: set[str] = set()
    checked = 0
    failures: list[str] = []
    bundled_failures: list[str] = []
    while queue:
        name = _normalize(queue.pop(0))
        if name in seen:
            continue
        seen.add(name)
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            failures.append(f"{name}: not installed")
            continue
        checked += 1
        metadata = dist.metadata
        found = overrides.get(f"pypi:{name}") or license_of(metadata)
        if found is None or not is_allowed_expression(found, allowed, allowed_with):
            failures.append(f"{name}=={dist.version}: {found!r}")
        for text in _license_files(dist):
            for library, bundled in bundled_licenses(text):
                if not is_allowed_expression(bundled, allowed, allowed_with):
                    bundled_failures.append(
                        f"{name}=={dist.version} bundles {library}: {bundled!r}"
                    )
        queue.extend(active_requirement_names(metadata.get_all("Requires-Dist") or []))

    if sys.platform == SHIPPED_PLATFORM:
        failures.extend(bundled_failures)
    else:
        for warning in bundled_failures:
            print(f"license check warning (not {SHIPPED_PLATFORM}): {warning}", file=sys.stderr)
    for failure in failures:
        print(f"license check failed: {failure}", file=sys.stderr)
    print(f"pypi licenses: {checked} runtime packages checked, {len(failures)} failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
