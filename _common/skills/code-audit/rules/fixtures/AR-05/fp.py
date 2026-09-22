import pytest


def test_it(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))
    assert run() == 0
