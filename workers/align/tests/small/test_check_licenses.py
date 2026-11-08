from email.message import Message

from check_licenses import active_requirement_names, is_allowed_expression, license_of

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
