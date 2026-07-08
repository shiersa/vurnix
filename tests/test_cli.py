from vurnix import __version__
from vurnix.cli import main


def test_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == f"vurnix {__version__}"


def test_info_points_home(capsys):
    assert main(["info"]) == 0
    assert "github.com/shiersa/vurnix" in capsys.readouterr().out


def test_default_is_info(capsys):
    assert main([]) == 0
    assert "software factory" in capsys.readouterr().out


def test_doctor_passes_where_git_exists(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "git" in out and "python" in out
