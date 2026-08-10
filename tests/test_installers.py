from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Darwin-lfl/agent-usage-monitor"


def test_shell_installer_accepts_stamped_repository():
    installer = (ROOT / "scripts" / "install.sh").read_text()

    stamped = installer.replace("__REPOSITORY__", REPOSITORY)

    assert f'REPOSITORY="${{AGENT_MONITOR_REPOSITORY:-{REPOSITORY}}}"' in stamped
    assert f'if [ "$REPOSITORY" = "{REPOSITORY}" ]' not in stamped


def test_powershell_installer_accepts_stamped_repository():
    installer = (ROOT / "scripts" / "install.ps1").read_text()

    stamped = installer.replace("__REPOSITORY__", REPOSITORY)

    assert f'else {{ "{REPOSITORY}" }}' in stamped
    assert f'if ($Repository -eq "{REPOSITORY}")' not in stamped
