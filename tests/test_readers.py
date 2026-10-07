import pytest

from kiosk.readers import student_numbers


@pytest.mark.parametrize(
    ("scan", "expected"),
    [
        ("000123456\n", ["000123456"]),
        ("1234567890\n", []),
        ("1234567890\n000123456\n", ["000123456"]),
    ],
    ids=["leading-zeros", "overlong-scan", "valid-scan-after-rejection"],
)
def test_student_numbers_parses_complete_scans(scan: str, expected: list[str]) -> None:
    events = ((index * 0.01, character) for index, character in enumerate(scan))

    assert list(student_numbers(events)) == expected
