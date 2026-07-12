from unittest.mock import MagicMock, patch

import pytest

import lib.provision as provision_lib


class TestRunScript:
    def _make_result(self, status_code=0, stdout=b"output", stderr=b""):
        r = MagicMock()
        r.status_code = status_code
        r.std_out = stdout
        r.std_err = stderr
        return r

    def test_returns_zero_exit_code_on_success(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("Write-Host hello")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0, b"hello")
            code, output = provision_lib.run_script("192.168.1.1", "admin", "pass", script)
        assert code == 0

    def test_returns_nonzero_exit_code_on_failure(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("exit 1")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(1, b"", b"error")
            code, output = provision_lib.run_script("192.168.1.1", "admin", "pass", script)
        assert code == 1

    def test_combines_stdout_and_stderr(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0, b"out", b"err")
            _, output = provision_lib.run_script("192.168.1.1", "admin", "pass", script)
        assert "out" in output
        assert "err" in output

    def test_output_includes_connection_header(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0, b"", b"")
            _, output = provision_lib.run_script("192.168.1.1", "admin", "pass", script)
        assert "192.168.1.1" in output
        assert "admin" in output
        assert script.name in output

    def test_reads_script_content_from_file(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("Get-Date")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script("192.168.1.1", "admin", "pass", script)
        mock_sess.return_value.run_ps.assert_called_once_with("Get-Date")

    def test_raises_on_connection_error(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.side_effect = ConnectionError("refused")
            with pytest.raises(ConnectionError):
                provision_lib.run_script("192.168.1.1", "admin", "pass", script)

    def test_uses_ntlm_transport(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script("192.168.1.1", "admin", "pass", script)
        _, kwargs = mock_sess.call_args
        assert kwargs.get("transport") == "ntlm"


class TestBuildPsInvocation:
    def test_no_params_returns_content_unchanged(self):
        content = "Write-Host hello"
        assert provision_lib._build_ps_invocation(content, {}) == content

    def test_wraps_in_scriptblock_with_args(self):
        result = provision_lib._build_ps_invocation("Write-Host $Env", {"Env": "dev"})
        assert result.startswith("& {")
        assert "-Env 'dev'" in result
        assert "Write-Host $Env" in result

    def test_single_quotes_string_values(self):
        result = provision_lib._build_ps_invocation("", {"Name": "My VM"})
        assert "-Name 'My VM'" in result

    def test_escapes_single_quotes_in_values(self):
        result = provision_lib._build_ps_invocation("", {"Name": "it's"})
        assert "-Name 'it''s'" in result

    def test_multiple_params(self):
        result = provision_lib._build_ps_invocation("", {"A": "1", "B": "2"})
        assert "-A '1'" in result
        assert "-B '2'" in result


class TestRunScriptWithParameters:
    def _make_result(self, status_code=0, stdout=b"", stderr=b""):
        from unittest.mock import MagicMock

        r = MagicMock()
        r.status_code = status_code
        r.std_out = stdout
        r.std_err = stderr
        return r

    def test_no_params_sends_content_directly(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("Write-Host hello")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script("1.2.3.4", "admin", "pass", script)
        sent = mock_sess.return_value.run_ps.call_args[0][0]
        assert sent == "Write-Host hello"

    def test_with_params_wraps_in_scriptblock(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("param($Env) Write-Host $Env")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script("1.2.3.4", "admin", "pass", script, parameters={"Env": "dev"})
        sent = mock_sess.return_value.run_ps.call_args[0][0]
        assert sent.startswith("& {")
        assert "-Env 'dev'" in sent

    def test_header_includes_params_line(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            _, output = provision_lib.run_script(
                "1.2.3.4", "admin", "pass", script, parameters={"Env": "dev"}
            )
        assert "Env=dev" in output

    def test_no_params_header_shows_none(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            _, output = provision_lib.run_script("1.2.3.4", "admin", "pass", script)
        assert "params   : none" in output


class TestShutdownGuest:
    def test_sends_stop_computer(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            provision_lib.shutdown_guest("192.168.1.1", "admin", "pass")
        mock_sess.return_value.run_ps.assert_called_once()
        cmd = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Stop-Computer" in cmd

    def test_does_not_raise_on_connection_drop(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.side_effect = ConnectionError("dropped")
            provision_lib.shutdown_guest("192.168.1.1", "admin", "pass")  # must not raise
