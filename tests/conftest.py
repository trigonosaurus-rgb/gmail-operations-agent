from collections.abc import Iterator
from pathlib import Path

import pytest

from gmail_operations_agent.store import Store
from tests.fakes import FakeClock

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock: FakeClock) -> Iterator[Store]:
    db = Store(":memory:", clock=clock)
    yield db
    db.close()


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()
