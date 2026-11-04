"""Greeting helpers shared across apps."""


def greet(name: str) -> str:
    """Return a friendly greeting for ``name``."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("name must not be empty")
    return f"Hello, {cleaned}!"
