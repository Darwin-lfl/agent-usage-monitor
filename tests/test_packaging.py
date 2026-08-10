from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_collects_textual_lazy_imports():
    spec = (ROOT / "agent-monitor.spec").read_text()

    assert 'collect_submodules("textual")' in spec
