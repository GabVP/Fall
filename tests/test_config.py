"""Os quatro perfis operacionais são selecionados sem valores secretos."""

import pytest

from fall.config import Environment, load_settings


@pytest.mark.parametrize(
    ("name", "docs_enabled"),
    [
        ("development", True),
        ("test", True),
        ("staging", False),
        ("production", False),
    ],
)
def test_loads_an_explicit_environment(name: str, docs_enabled: bool) -> None:
    settings = load_settings({"FALL_ENVIRONMENT": name})

    assert settings.environment is Environment(name)
    assert settings.api_docs_enabled is docs_enabled


def test_missing_environment_fails_without_implicit_development() -> None:
    with pytest.raises(ValueError, match="FALL_ENVIRONMENT"):
        load_settings({})


def test_invalid_environment_is_not_echoed_in_error() -> None:
    with pytest.raises(ValueError) as error:
        load_settings({"FALL_ENVIRONMENT": "secret-sentinel"})

    assert "secret-sentinel" not in str(error.value)
