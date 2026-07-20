"""PowerShell syntax validation for .ps1.j2 templates and example scripts.

Uses pwsh's built-in AST parser (ParseFile) — no execution, just parse.
Tests are skipped automatically when pwsh is not available on the host.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from lib import answerfile

_PWSH = shutil.which("pwsh")
_EXAMPLES_DIR = Path(__file__).parent.parent / ".hatchery" / "examples" / "scripts"


def _ps1_syntax_errors(path: str) -> list[str]:
    """Return a list of syntax error messages from the PowerShell AST parser, or [] if valid."""
    cmd = (
        "$e=$null; $t=$null; "
        f"$null=[System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e); "
        "if($e){$e|ForEach-Object{Write-Output $_.Message}; exit 1}"
    )
    result = subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines() if result.returncode != 0 else []


@pytest.mark.skipif(_PWSH is None, reason="pwsh not available")
class TestPs1Syntax:
    def test_setup_script_is_valid_powershell(self, tmp_path):
        ps1 = tmp_path / "hatchery-setup.ps1"
        ps1.write_text(answerfile.render_setup_script(), encoding="utf-8")
        errors = _ps1_syntax_errors(str(ps1))
        assert errors == [], "PowerShell syntax errors in hatchery-setup.ps1:\n" + "\n".join(errors)

    def test_cleanup_script_is_valid_powershell(self):
        path = _EXAMPLES_DIR / "hatchery-cleanup.ps1"
        errors = _ps1_syntax_errors(str(path))
        assert errors == [], "PowerShell syntax errors in hatchery-cleanup.ps1:\n" + "\n".join(
            errors
        )

    def test_configure_vm_basics_is_valid_powershell(self):
        path = _EXAMPLES_DIR / "configure-vm-basics.ps1"
        errors = _ps1_syntax_errors(str(path))
        assert errors == [], "PowerShell syntax errors in configure-vm-basics.ps1:\n" + "\n".join(
            errors
        )

    def test_hatchery_script_template_is_valid_powershell(self):
        path = _EXAMPLES_DIR / "hatchery-script-template.ps1"
        errors = _ps1_syntax_errors(str(path))
        assert errors == [], (
            "PowerShell syntax errors in hatchery-script-template.ps1:\n" + "\n".join(errors)
        )

    def test_retry_script_is_valid_powershell(self):
        path = _EXAMPLES_DIR / "test-retry.ps1"
        errors = _ps1_syntax_errors(str(path))
        assert errors == [], "PowerShell syntax errors in test-retry.ps1:\n" + "\n".join(errors)

    def test_invalid_powershell_is_caught(self, tmp_path):
        ps1 = tmp_path / "bad.ps1"
        ps1.write_text("function Broken { if ($true) {", encoding="utf-8")
        errors = _ps1_syntax_errors(str(ps1))
        assert errors != []
