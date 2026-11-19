import pytest


@pytest.fixture(autouse=True)
def indexed(monkeypatch):
    """The libraries the server would index in the background after a change
    (server._index_soon), recorded instead: a real index calls the model."""
    roots = []
    monkeypatch.setattr("noesis.server._index_soon", roots.append)
    return roots
