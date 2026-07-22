import pytest


def test_alpha():
    assert 1 + 1 == 2
    assert "b" in "abc"


def test_beta():
    assert sum([1, 2, 3]) == 6


def test_delta():
    assert max(4, 2) == 4


@pytest.mark.skip(reason="pre-existing skip: already present in the before snapshot")
def test_gamma():
    assert len("abc") == 3
