import pytest


def test_alpha():
    assert 1 + 1 == 2


def test_beta():
    assert sum([1, 2, 3]) == 6


@pytest.mark.skip(reason="pre-existing skip: already present in the before snapshot")
def test_gamma():
    assert len("abc") == 3
