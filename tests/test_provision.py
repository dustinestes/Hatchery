from unittest.mock import MagicMock, patch

import pytest

import lib.provision as provision_lib

_CLIXML_NS = "http://schemas.microsoft.com/powershell/2004/04"
_CLIXML_PREFIX = "#< CLIXML\r\n"


def _clixml(content: str) -> str:
    """Wrap content in a real-world CLIXML envelope with the WinRM header."""
    return f'{_CLIXML_PREFIX}<Objs Version="1.1.0.1" xmlns="{_CLIXML_NS}">{content}</Objs>'


class TestStripClixml:
    def test_plain_text_passes_through_unchanged(self):
        text = "Hello from PowerShell"
        assert provision_lib._strip_clixml(text) == text

    def test_empty_string_passes_through(self):
        assert provision_lib._strip_clixml("") == ""

    def test_extracts_string_from_clixml_with_prefix(self):
        assert provision_lib._strip_clixml(_clixml("<S>Test output Text</S>")) == "Test output Text"

    def test_extracts_string_from_clixml_without_prefix(self):
        # <Objs directly (no #< CLIXML header) should also be stripped
        clixml = f'<Objs Version="1.1.0.1" xmlns="{_CLIXML_NS}"><S>hello</S></Objs>'
        assert provision_lib._strip_clixml(clixml) == "hello"

    def test_discards_progress_objects(self):
        clixml = _clixml(
            '<Obj S="progress" RefId="0">'
            '<TN RefId="0"><T>System.Management.Automation.PSCustomObject</T></TN>'
            '<MS><PR N="Record"><AV>Preparing modules for first use.</AV></PR></MS>'
            "</Obj>"
        )
        assert provision_lib._strip_clixml(clixml) == ""

    def test_extracts_strings_and_discards_progress(self):
        clixml = _clixml(
            "<S>Useful output</S>"
            '<Obj S="progress" RefId="0"><MS><PR N="Record"><AV>noise</AV></PR></MS></Obj>'
            "<S>More output</S>"
        )
        result = provision_lib._strip_clixml(clixml)
        assert "Useful output" in result
        assert "More output" in result
        assert "noise" not in result

    def test_decodes_powershell_unicode_escapes(self):
        # _x000D_ is \r, _x000A_ is \n — PowerShell encodes these in CLIXML
        result = provision_lib._strip_clixml(_clixml("<S>line one_x000D__x000A_line two</S>"))
        assert "line one" in result
        assert "line two" in result

    def test_multiple_string_nodes_joined_by_newline(self):
        result = provision_lib._strip_clixml(_clixml("<S>first</S><S>second</S>"))
        assert result == "first\nsecond"

    def test_malformed_xml_returns_original(self):
        bad = f"{_CLIXML_PREFIX}<Objs>unclosed"
        assert provision_lib._strip_clixml(bad) == bad

    def test_run_script_strips_clixml_from_stdout(self, tmp_path):
        script = tmp_path / "test.ps1"
        script.write_text('Write-Output "hello"')
        clixml = _clixml("<S>hello</S>").encode()
        with patch("lib.provision.winrm.Session") as mock_sess:
            r = MagicMock()
            r.status_code = 0
            r.std_out = clixml
            r.std_err = b""
            mock_sess.return_value.run_ps.return_value = r
            _, output = provision_lib.run_script("1.2.3.4", "admin", "pass", script)
        assert "hello" in output
        assert "<Objs" not in output


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
        sent = mock_sess.return_value.run_ps.call_args[0][0]
        # Hatchery prepends Write-HatchEvent before the script content
        assert "Get-Date" in sent
        assert "Write-HatchEvent" in sent

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


class TestExtractParamBlock:
    def test_no_param_block_returns_empty_and_full_content(self):
        content = "Write-Host hello"
        block, rest = provision_lib._extract_param_block(content)
        assert block == ""
        assert rest == content

    def test_simple_param_block_extracted(self):
        content = "param($Name)\nWrite-Host $Name"
        block, rest = provision_lib._extract_param_block(content)
        assert block == "param($Name)"
        assert rest == "\nWrite-Host $Name"

    def test_multiline_param_block_extracted(self):
        content = "param(\n    [string]$Name,\n    [int]$Count\n)\nWrite-Host $Name"
        block, rest = provision_lib._extract_param_block(content)
        assert block.startswith("param(")
        assert block.endswith(")")
        assert "[string]$Name" in block
        assert rest.strip() == "Write-Host $Name"

    def test_nested_parens_in_default_value(self):
        content = "param([string]$Name = (Get-Date).ToString())\nWrite-Host $Name"
        block, rest = provision_lib._extract_param_block(content)
        assert block == "param([string]$Name = (Get-Date).ToString())"
        assert "Write-Host $Name" in rest

    def test_param_in_middle_of_script_not_matched(self):
        content = "Write-Host hello\nparam($Late)"
        block, rest = provision_lib._extract_param_block(content)
        assert block == "param($Late)"


class TestBuildInjection:
    def test_sets_log_file_variable(self):
        result = provision_lib._build_injection("my-script.ps1")
        assert "$script:HatchLogFile" in result

    def test_log_path_uses_script_name(self):
        result = provision_lib._build_injection("configure-vm.ps1")
        assert "configure-vm.ps1.log" in result

    def test_log_path_under_hatchery_dir(self):
        result = provision_lib._build_injection("my-script.ps1")
        assert provision_lib.HATCHERY_GUEST_DIR in result

    def test_different_script_names_produce_different_paths(self):
        r1 = provision_lib._build_injection("script-a.ps1")
        r2 = provision_lib._build_injection("script-b.ps1")
        assert "script-a.ps1.log" in r1
        assert "script-b.ps1.log" in r2
        assert "script-b.ps1.log" not in r1

    def test_creates_log_directory(self):
        result = provision_lib._build_injection("my-script.ps1")
        assert "New-Item" in result
        assert "Directory" in result

    def test_defines_write_hatch_event(self):
        result = provision_lib._build_injection("my-script.ps1")
        assert "function Write-HatchEvent" in result

    def test_write_hatch_event_logs_to_file(self):
        result = provision_lib._build_injection("my-script.ps1")
        assert "Add-Content" in result
        assert "$script:HatchLogFile" in result

    def test_write_hatch_event_also_writes_to_stdout(self):
        result = provision_lib._build_injection("my-script.ps1")
        assert "Write-Output" in result


class TestBuildPsInvocation:
    def test_no_params_prepends_inject(self):
        inject = "# preamble\n"
        result = provision_lib._build_ps_invocation("Write-Host hello", {}, inject)
        assert result.startswith("# preamble")
        assert "Write-Host hello" in result
        assert not result.startswith("& {")

    def test_no_inject_returns_content_unchanged(self):
        content = "Write-Host hello"
        assert provision_lib._build_ps_invocation(content, {}) == content

    def test_wraps_in_scriptblock_with_args(self):
        result = provision_lib._build_ps_invocation("Write-Host $Env", {"Env": "dev"})
        assert result.startswith("& {")
        assert "-Env 'dev'" in result
        assert "Write-Host $Env" in result

    def test_param_block_before_inject_when_wrapping(self):
        inject = provision_lib._build_injection("test.ps1")
        content = "param($Name)\nWrite-Host $Name"
        result = provision_lib._build_ps_invocation(content, {"Name": "test"}, inject)
        param_pos = result.index("param(")
        inject_pos = result.index("Write-HatchEvent")
        assert param_pos < inject_pos, "param() must appear before inject"

    def test_inject_present_when_wrapping(self):
        inject = provision_lib._build_injection("test.ps1")
        content = "param($Name)\nWrite-Host $Name"
        result = provision_lib._build_ps_invocation(content, {"Name": "test"}, inject)
        assert "Write-HatchEvent" in result

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
        # Hatchery prepends Write-HatchEvent but otherwise sends content un-wrapped
        script = tmp_path / "setup.ps1"
        script.write_text("Write-Host hello")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script("1.2.3.4", "admin", "pass", script)
        sent = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Write-Host hello" in sent
        assert not sent.startswith("& {")

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


class TestRestartGuest:
    def test_sends_restart_computer(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            provision_lib.restart_guest("192.168.1.1", "admin", "pass")
        mock_sess.return_value.run_ps.assert_called_once()
        cmd = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Restart-Computer" in cmd

    def test_does_not_raise_on_connection_drop(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.side_effect = ConnectionError("dropped")
            provision_lib.restart_guest("192.168.1.1", "admin", "pass")  # must not raise


class TestCheckSetupComplete:
    def _make_result(self, stdout: str):
        r = MagicMock()
        r.std_out = stdout.encode()
        return r

    def test_returns_true_when_flag_present(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result("True\r\n")
            result = provision_lib.check_setup_complete("1.2.3.4", "admin", "pass")
        assert result is True
        cmd = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Test-Path" in cmd
        assert provision_lib.SETUP_COMPLETE_FLAG in cmd

    def test_returns_false_when_flag_absent(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result("False\r\n")
            result = provision_lib.check_setup_complete("1.2.3.4", "admin", "pass")
        assert result is False

    def test_returns_false_on_winrm_error(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.side_effect = ConnectionError("refused")
            result = provision_lib.check_setup_complete("1.2.3.4", "admin", "pass")
        assert result is False


class TestDeleteSetupFlag:
    def test_sends_remove_item(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            provision_lib.delete_setup_flag("1.2.3.4", "admin", "pass")
        cmd = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Remove-Item" in cmd
        assert provision_lib.SETUP_COMPLETE_FLAG in cmd

    def test_does_not_raise_on_connection_drop(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.side_effect = ConnectionError("dropped")
            provision_lib.delete_setup_flag("1.2.3.4", "admin", "pass")  # must not raise
