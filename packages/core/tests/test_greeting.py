import pytest

from core import greet


def test_greet_returns_greeting() -> None:
    assert greet("World") == "Hello, World!"


def test_greet_strips_whitespace() -> None:
    assert greet("  Ada ") == "Hello, Ada!"


def test_greet_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="empty"):
        greet("   ")
