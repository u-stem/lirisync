from collections.abc import Iterable
from email.message import Message
from importlib.metadata import Distribution
from os import PathLike
from pathlib import Path

import pytest

from check_licenses import (
    active_requirement_names,
    bundled_licenses,
    is_allowed_expression,
    license_of,
    license_texts,
    split_bundled,
)

ALLOWED = frozenset({"MIT", "Apache-2.0", "PSF-2.0"})


def _metadata(**fields: str | list[str]) -> Message:
    message = Message()
    for key, value in fields.items():
        header = key.replace("_", "-")
        for item in value if isinstance(value, list) else [value]:
            message[header] = item
    return message


def test_single_allowed_id_is_allowed() -> None:
    # Arrange
    expression = "MIT"
    # Act
    result = is_allowed_expression(expression, ALLOWED)
    # Assert
    assert result is True


def test_disallowed_id_is_rejected() -> None:
    assert is_allowed_expression("GPL-3.0-only", ALLOWED) is False


def test_or_with_one_allowed_side_is_allowed() -> None:
    assert is_allowed_expression("Apache-2.0 OR BSD-2-Clause", ALLOWED) is True


def test_and_with_disallowed_side_is_rejected() -> None:
    assert is_allowed_expression("MIT AND MPL-2.0", ALLOWED) is False


def test_parentheses_are_respected() -> None:
    assert is_allowed_expression("MPL-2.0 AND (MIT OR Apache-2.0)", ALLOWED) is False


def test_with_exception_is_rejected() -> None:
    assert is_allowed_expression("Apache-2.0 WITH LLVM-exception", ALLOWED) is False


def test_unbalanced_expression_is_rejected() -> None:
    assert is_allowed_expression("(MIT", ALLOWED) is False


def test_license_expression_field_wins() -> None:
    metadata = _metadata(License_Expression="MIT", License="BSD")
    assert license_of(metadata) == "MIT"


def test_plain_license_field_is_used_when_it_is_an_spdx_id() -> None:
    metadata = _metadata(License="MIT")
    assert license_of(metadata) == "MIT"


def test_free_text_license_field_falls_back_to_classifiers() -> None:
    metadata = _metadata(
        License="Permission is hereby granted...",
        Classifier=["License :: OSI Approved :: Apache Software License"],
    )
    assert license_of(metadata) == "Apache-2.0"


def test_ambiguous_bsd_classifier_is_unknown() -> None:
    metadata = _metadata(Classifier=["License :: OSI Approved :: BSD License"])
    assert license_of(metadata) is None


def test_missing_license_is_unknown() -> None:
    assert license_of(_metadata()) is None


def test_plain_requirement_is_kept() -> None:
    assert active_requirement_names(["annotated-types>=0.6.0"]) == ["annotated-types"]


def test_requirement_with_true_marker_is_kept() -> None:
    assert active_requirement_names(["typing-extensions; python_version >= '3'"]) == [
        "typing-extensions"
    ]


def test_requirement_with_false_marker_is_skipped() -> None:
    assert active_requirement_names(["colorama; sys_platform == 'no-such-platform'"]) == []


def test_extra_gated_requirement_is_skipped() -> None:
    assert active_requirement_names(["email-validator>=2; extra == 'email'"]) == []


def test_extra_gated_requirement_is_skipped_even_with_other_true_marker() -> None:
    assert active_requirement_names(["tzdata; python_version >= '3' and extra == 'tz'"]) == []


def test_requirement_name_is_returned_without_specifier_or_extras() -> None:
    assert active_requirement_names(["pydantic[email]>=2,<3"]) == ["pydantic"]


GCC_RUNTIME = "GPL-3.0-or-later WITH GCC-exception-3.1"
ONLY_GCC = frozenset({GCC_RUNTIME})


def test_listed_with_exception_is_allowed() -> None:
    assert is_allowed_expression(GCC_RUNTIME, ALLOWED, ONLY_GCC) is True


def test_unlisted_with_exception_is_rejected() -> None:
    expression = "GPL-2.0-only WITH Classpath-exception-2.0"
    assert is_allowed_expression(expression, ALLOWED, ONLY_GCC) is False


def test_listed_with_exception_combines_with_and() -> None:
    assert is_allowed_expression(f"MIT AND {GCC_RUNTIME}", ALLOWED, ONLY_GCC) is True


def test_with_without_an_exception_id_is_rejected() -> None:
    assert is_allowed_expression("MIT WITH", ALLOWED, frozenset({"MIT WITH"})) is False


@pytest.mark.parametrize(
    "expression", ["WITH MIT", "( WITH MIT", "MIT WITH AND", f"{GCC_RUNTIME} WITH MIT"]
)
def test_misplaced_with_is_rejected(expression: str) -> None:
    assert is_allowed_expression(expression, ALLOWED, ONLY_GCC) is False


BUNDLED_NOTICE = """\
Copyright (c) 2005-2025, NumPy Developers.

----

This binary distribution of NumPy also bundles the following software:


Name: OpenBLAS
Files: numpy.libs\\libscipy_openblas*.dll
Description: bundled as a dynamically linked library
Availability: https://github.com/OpenMathLib/OpenBLAS/
License: BSD-3-Clause
  Copyright (c) 2011-2014, The OpenBLAS Project
  License: this indented line belongs to the license text


Name: GCC runtime library
Files: numpy.libs\\libscipy_openblas*.dll
Description: dynamically linked to files compiled with gcc
License: GPL-3.0-or-later WITH GCC-exception-3.1
  Libgfortran is free software; you can redistribute it and/or modify
"""


def test_bundled_libraries_are_read_from_name_and_license_fields() -> None:
    assert bundled_licenses(BUNDLED_NOTICE) == [
        ("OpenBLAS", "BSD-3-Clause"),
        ("GCC runtime library", GCC_RUNTIME),
    ]


def test_license_line_outside_a_named_entry_is_ignored() -> None:
    assert bundled_licenses("Some text\nLicense: GPL-3.0-only\n") == []


def test_entry_ended_before_its_license_is_reported_unknown() -> None:
    assert bundled_licenses("Name: libfoo\nsee below\nLicense: GPL-3.0-only\n") == [("libfoo", "")]


def test_entry_at_the_end_of_the_file_without_a_license_is_reported_unknown() -> None:
    assert bundled_licenses("Name: libfoo\nFiles: libfoo.dll") == [("libfoo", "")]


def test_license_value_on_the_next_line_is_reported_unknown() -> None:
    assert bundled_licenses("Name: libfoo\nLicense:\n  GPL-3.0-only\n") == [("libfoo", "")]


def test_hyphenated_field_does_not_end_the_entry() -> None:
    assert bundled_licenses("Name: libfoo\nBundled-By: bar\nLicense: MIT\n") == [("libfoo", "MIT")]


def test_bundled_failures_fail_on_the_shipped_platform() -> None:
    assert split_bundled(["numpy bundles x"], "win32") == (["numpy bundles x"], [])


def test_bundled_failures_only_warn_elsewhere() -> None:
    assert split_bundled(["numpy bundles x"], "darwin") == ([], ["numpy bundles x"])


class _StubDistribution(Distribution):
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    def read_text(self, filename: str) -> str | None:
        return self._files.get(filename)

    def locate_file(self, path: str | PathLike[str]) -> Path:
        raise NotImplementedError


def _texts(files: dict[str, str]) -> Iterable[str]:
    return list(license_texts(_StubDistribution(files)))


def test_license_files_are_read_under_licenses_first() -> None:
    files = {
        "METADATA": "License-File: LICENSE.txt\n\n",
        "licenses/LICENSE.txt": "new layout",
        "LICENSE.txt": "old layout",
    }
    assert _texts(files) == ["new layout"]


def test_license_files_fall_back_to_the_dist_info_root() -> None:
    files = {"METADATA": "License-File: LICENSE.txt\n\n", "LICENSE.txt": "old layout"}
    assert _texts(files) == ["old layout"]


def test_url_line_ends_the_entry() -> None:
    text = "Name: libfoo\nhttps://example.org/libfoo\nLicense: GPL-3.0-only\n"
    assert bundled_licenses(text) == [("libfoo", "")]
