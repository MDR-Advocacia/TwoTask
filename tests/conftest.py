# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
import os

# Adjust the path to import from the root directory
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.core.dependencies import get_db
from app.db.session import Base

TEST_DATABASE_URL = "sqlite:///./test_main.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def setup_test_database():
    """
    Create and drop the test database and tables once per test session.
    """
    if os.path.exists("test_main.db"):
        os.remove("test_main.db")
    Base.metadata.create_all(bind=engine)
    yield
    if os.path.exists("test_main.db"):
        os.remove("test_main.db")

@pytest.fixture(scope="function")
def db_session(setup_test_database) -> Generator[Session, None, None]:
    """
    Provides a clean, transactional database session for each test function.
    The session is rolled back after the test, ensuring test isolation.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    # Override the app's dependency to use this transactional session
    def override_get_db_for_test():
        yield session

    app.dependency_overrides[get_db] = override_get_db_for_test

    yield session

    # Teardown: rollback transaction and close connections
    session.close()
    transaction.rollback()
    connection.close()
    del app.dependency_overrides[get_db]

@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """
    Provides a TestClient that uses the transactional database session.
    The db_session fixture is included as a dependency to ensure the
    dependency override is active for all requests made by the client.
    """
    yield TestClient(app)