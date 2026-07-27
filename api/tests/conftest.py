"""Test fixtures.

Service-layer tests run against a real Postgres, not a mock and not SQLite: the plan
payload is JSONB and the production behaviour of that column is part of what's being
tested. The test database is created once per session and torn down with it.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from furnitureos.core.config import settings
from furnitureos.core.db import Base

# Imported for its side effect: models must be registered on Base.metadata before
# create_all, and relying on a test module to pull them in transitively makes table
# creation depend on collection order.
import furnitureos.registry  # noqa: E402, F401  isort:skip


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = make_url(settings.test_database_url)
    database_name = url.database
    assert database_name and database_name.endswith("_test"), (
        "refusing to run tests against a database not named *_test"
    )

    admin_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin_engine.dispose()

    test_engine = create_engine(url)
    Base.metadata.create_all(test_engine)

    yield test_engine

    test_engine.dispose()
    with create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    ).connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session rolled back after each test, so tests cannot leak into each other."""
    connection = engine.connect()
    transaction = connection.begin()
    test_session = sessionmaker(bind=connection, expire_on_commit=False)()

    yield test_session

    test_session.close()
    transaction.rollback()
    connection.close()
