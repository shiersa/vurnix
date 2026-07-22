import pytest


def test_alpha():
    assert 1 + 1 == 2
    assert "b" in "abc"


def test_beta():
    assert True


@pytest.mark.skip(reason="pre-existing skip: already present in the before snapshot")
def test_gamma():
    assert len("abc") == 3
