import pytest

from cli.main import main


def test_main_greets_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out == "Hello, World!\n"


def test_main_greets_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["Ada"]) == 0
    assert capsys.readouterr().out == "Hello, Ada!\n"
