"""A configuração de cada perfil é independente e não revela credenciais."""

import pytest

from fall.config import Environment
from fall.persistence.database import create_database_engine, load_database_url


@pytest.mark.parametrize(
    ("environment", "variable", "database"),
    [
        (Environment.DEVELOPMENT, "FALL_DEVELOPMENT_DATABASE_URL", "fall_development"),
        (Environment.TEST, "FALL_TEST_DATABASE_URL", "fall_test"),
        (Environment.STAGING, "FALL_STAGING_DATABASE_URL", "fall_staging"),
        (Environment.PRODUCTION, "FALL_PRODUCTION_DATABASE_URL", "fall_production"),
    ],
)
def test_selects_only_the_current_profile(environment, variable, database) -> None:
    url = f"postgresql+psycopg://local:synthetic@localhost/{database}"
    parsed = load_database_url(environment, {variable: url})

    assert parsed.database == database
    engine = create_database_engine(parsed)
    try:
        assert engine.url.database == database
    finally:
        engine.dispose()


def test_missing_profile_url_fails_even_if_another_profile_is_set() -> None:
    with pytest.raises(ValueError, match="FALL_TEST_DATABASE_URL"):
        load_database_url(
            Environment.TEST,
            {"FALL_DEVELOPMENT_DATABASE_URL": "postgresql+psycopg://u:p@localhost/dev"},
        )


@pytest.mark.parametrize("invalid", ["secret-sentinel", "sqlite:///secret-sentinel", "postgresql+psycopg://u:secret-sentinel@localhost"])
def test_invalid_url_is_redacted(invalid: str) -> None:
    with pytest.raises(ValueError) as error:
        load_database_url(Environment.TEST, {"FALL_TEST_DATABASE_URL": invalid})

    assert "secret-sentinel" not in str(error.value)
