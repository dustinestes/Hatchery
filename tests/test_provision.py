from unittest.mock import MagicMock, patch

import pytest

import lib.provision as provision_lib
from lib.guest_transport import GuestEndpoint, WinrmGuestTransport

_CLIXML_NS = "http://schemas.microsoft.com/powershell/2004/04"
_CLIXML_PREFIX = "#< CLIXML\r\n"


def _clixml(content: str) -> str:
    """Wrap content in a real-world CLIXML envelope with the WinRM header."""
    return f'{_CLIXML_PREFIX}<Objs Version="1.1.0.1" xmlns="{_CLIXML_NS}">{content}</Objs>'


@pytest.fixture(autouse=True)
def _force_winrm_guest_transport(monkeypatch):
    """Provision unit tests exercise the WinRM guest path (no live TCP / SSH)."""

    def _gt(ip, user, password, **_kwargs):
        return WinrmGuestTransport(GuestEndpoint(host=ip, username=user, password=password))

    monkeypatch.setattr(provision_lib, "_guest_transport", _gt)


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
        # User body is present; helper function is not spliced into the script.
        assert "Get-Date" in sent
        assert "function Write-HatchEvent" not in sent
        assert "HATCHERY_SCRIPT_LOG" in sent
        assert "HATCHERY_MODULES" in sent

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


class TestHatcheryModuleSource:
    def test_psm1_exports_write_hatch_event(self):
        body = provision_lib.hatchery_module_psm1_source()
        assert "function Write-HatchEvent" in body
        assert "Export-ModuleMember" in body
        assert "$env:HATCHERY_SCRIPT_LOG" in body

    def test_psd1_points_at_psm1(self):
        manifest = provision_lib.hatchery_module_psd1_source()
        assert "Hatchery.psm1" in manifest
        assert "Write-HatchEvent" in manifest


class TestBuildPsInvocation:
    def test_no_params_prepends_env_prefix(self):
        prefix = "$env:FOO = '1'\n"
        result = provision_lib._build_ps_invocation("Write-Host hello", {}, env_prefix=prefix)
        assert result.startswith("$env:FOO")
        assert "Write-Host hello" in result
        assert "function Write-HatchEvent" not in result

    def test_no_prefix_returns_content_unchanged(self):
        content = "Write-Host hello"
        assert provision_lib._build_ps_invocation(content, {}) == content

    def test_wraps_in_scriptblock_with_args(self):
        result = provision_lib._build_ps_invocation("Write-Host $Env", {"Env": "dev"})
        assert result.startswith("& {")
        assert "-Env 'dev'" in result
        assert "Write-Host $Env" in result

    def test_env_outside_user_scriptblock_when_wrapping(self):
        prefix = "$env:FOO = '1'\n"
        content = "param($Name)\nWrite-Host $Name"
        result = provision_lib._build_ps_invocation(content, {"Name": "test"}, env_prefix=prefix)
        assert result.startswith("$env:FOO")
        assert "function Write-HatchEvent" not in result
        # param() is first inside the user scriptblock, after outer env.
        user_start = result.index("& {")
        param_pos = result.index("param(", user_start)
        assert param_pos > user_start

    def test_param_defaults_wrapped_when_env_present(self):
        """VirtIO-style scripts: param() defaults, no clutch parameters (#554)."""
        prefix = "$env:HATCHERY_ROOT = 'C:\\Program Files\\Hatchery'\n"
        content = (
            'param(\n    [string]$DriveLetter = "",\n'
            '    [string]$IsoLabel = "virtio-win"\n)\n'
            "Write-Host $IsoLabel\n"
        )
        result = provision_lib._build_ps_invocation(content, {}, env_prefix=prefix)
        assert result.startswith("$env:HATCHERY_ROOT")
        assert "& {" in result
        user_start = result.index("& {")
        param_pos = result.index("param(", user_start)
        assert param_pos > user_start
        assert "function Write-HatchEvent" not in result
        assert '[string]$DriveLetter = ""' in result
        assert "Write-Host $IsoLabel" in result

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

    def test_no_params_sends_content_without_user_scriptblock(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("Write-Host hello")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script("1.2.3.4", "admin", "pass", script)
        sent = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Write-Host hello" in sent
        assert "& {" not in sent
        assert "function Write-HatchEvent" not in sent

    def test_with_params_wraps_in_scriptblock(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("param($Env) Write-Host $Env")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script("1.2.3.4", "admin", "pass", script, parameters={"Env": "dev"})
        sent = mock_sess.return_value.run_ps.call_args[0][0]
        assert "& {" in sent
        assert "-Env 'dev'" in sent
        assert "function Write-HatchEvent" not in sent

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

    def test_environment_injected_before_script(self, tmp_path):
        script = tmp_path / "setup.ps1"
        script.write_text("Write-Host $env:MY_FLAG")
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(0)
            provision_lib.run_script(
                "1.2.3.4",
                "admin",
                "pass",
                script,
                environment={
                    "HATCHERY_ROOT": r"C:\Program Files\Hatchery",
                    "MY_FLAG": "1",
                },
            )
        sent = mock_sess.return_value.run_ps.call_args[0][0]
        assert "$env:HATCHERY_ROOT = 'C:\\Program Files\\Hatchery'" in sent
        assert "$env:MY_FLAG = '1'" in sent
        assert sent.index("$env:HATCHERY_ROOT") < sent.index("Write-Host $env:MY_FLAG")


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


class TestLastBootUpTimeRebootWait:
    def _boot_result(self, filetime: str):
        r = MagicMock()
        r.status_code = 0
        r.std_out = f"{filetime}\r\n".encode()
        r.std_err = b""
        return r

    def test_get_last_boot_uptime_parses_filetime(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._boot_result("133012345678901234")
            assert provision_lib.get_last_boot_uptime("10.0.0.1", "a", "b") == "133012345678901234"
        cmd = mock_sess.return_value.run_ps.call_args[0][0]
        assert "LastBootUpTime" in cmd

    def test_wait_for_boot_uptime_change_ignores_same_boot_id(self, monkeypatch):
        boots = iter(["111", "111", "222"])
        monkeypatch.setattr(provision_lib, "guest_remoting_ready", lambda *a, **k: True)
        monkeypatch.setattr(provision_lib, "get_last_boot_uptime", lambda *a, **k: next(boots))
        monkeypatch.setattr(provision_lib.time, "sleep", lambda *_: None)
        assert (
            provision_lib.wait_for_boot_uptime_change(
                "10.0.0.1", "a", "b", "111", poll_interval_sec=0, timeout_sec=60
            )
            == "222"
        )

    def test_wait_for_boot_uptime_change_times_out(self, monkeypatch):
        monkeypatch.setattr(provision_lib, "guest_remoting_ready", lambda *a, **k: True)
        monkeypatch.setattr(provision_lib, "get_last_boot_uptime", lambda *a, **k: "111")
        monkeypatch.setattr(provision_lib.time, "sleep", lambda *_: None)
        # Force deadline immediately after first iteration.
        ticks = iter([0.0, 0.0, 1000.0])
        monkeypatch.setattr(provision_lib.time, "monotonic", lambda: next(ticks))
        try:
            provision_lib.wait_for_boot_uptime_change(
                "10.0.0.1", "a", "b", "111", poll_interval_sec=0, timeout_sec=1
            )
            raise AssertionError("expected timeout")
        except RuntimeError as exc:
            assert "did not report a new LastBootUpTime" in str(exc)

    def test_reboot_guest_and_wait_orders_capture_restart_wait(self, monkeypatch):
        calls: list[str] = []

        def fake_get(*a, **k):
            calls.append("get")
            return "before"

        def fake_restart(*a, **k):
            calls.append("restart")

        def fake_wait_boot(*a, **k):
            calls.append("wait")
            return "134350310025000000"

        monkeypatch.setattr(provision_lib, "get_last_boot_uptime", fake_get)
        monkeypatch.setattr(provision_lib, "restart_guest", fake_restart)
        monkeypatch.setattr(provision_lib, "wait_for_boot_uptime_change", fake_wait_boot)
        monkeypatch.setattr(provision_lib, "wait_for_guest_stable", lambda *a, **k: None)
        events: list[tuple[str, str]] = []
        assert (
            provision_lib.reboot_guest_and_wait(
                "10.0.0.1", "a", "b", on_event=lambda lvl, msg: events.append((lvl, msg))
            )
            == "134350310025000000"
        )
        assert calls == ["get", "restart", "wait"]
        assert events[0][0] == "INFO"
        assert "Guest reboot confirmed: 2026-09-28T01:03:22+00:00" in events[0][1]

    def test_wait_for_winrm_stable_emits_start_and_success(self, monkeypatch):
        events: list[tuple[str, str]] = []
        probes = {"n": 0}

        class _Transport:
            kind = "winrm"

            def run_ps(self, *_a, **_k):
                probes["n"] += 1
                return 0, "ready"

        monkeypatch.setattr(provision_lib, "_guest_transport", lambda *a, **k: _Transport())
        monkeypatch.setattr(provision_lib.time, "sleep", lambda *_: None)
        provision_lib.wait_for_winrm_stable(
            "10.0.0.1",
            "a",
            "b",
            consecutive=2,
            poll_interval_sec=0,
            on_event=lambda lvl, msg: events.append((lvl, msg)),
        )
        assert probes["n"] == 2
        assert events[0][1].startswith("Waiting for guest remoting to stabilize")
        assert events[-1][1].startswith("Guest remoting stable after reboot")

    def test_format_guest_reboot_confirmed_matches_event_timestamps(self):
        msg = provision_lib.format_guest_reboot_confirmed("134350310025000000")
        assert msg == (
            "Guest reboot confirmed: 2026-09-28T01:03:22+00:00 (LastBootUpTime=134350310025000000)"
        )

    def test_filetime_to_utc_round_trip_seconds(self):
        dt = provision_lib.filetime_to_utc("134350310025000000")
        assert dt.isoformat(timespec="seconds") == "2026-09-28T01:03:22+00:00"


class TestCheckSetupComplete:
    def _make_result(self, stdout: str):
        r = MagicMock()
        r.status_code = 0
        r.std_out = stdout.encode()
        r.std_err = b""
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


class TestReadSetupLog:
    def _make_result(self, stdout: str):
        r = MagicMock()
        r.status_code = 0
        r.std_out = stdout.encode()
        r.std_err = b""
        return r

    def test_returns_log_content(self):
        log = "[HATCH:INFO][step-1][2026-07-20T12:00:00+00:00] Step 1 started"
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(log)
            result = provision_lib.read_setup_log("1.2.3.4", "admin", "pass")
        assert result == log
        cmd = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Get-Content" in cmd
        assert provision_lib.SETUP_LOG_FILE in cmd

    def test_returns_empty_when_missing(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result("")
            result = provision_lib.read_setup_log("1.2.3.4", "admin", "pass")
        assert result == ""

    def test_returns_empty_on_winrm_error(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.side_effect = ConnectionError("refused")
            result = provision_lib.read_setup_log("1.2.3.4", "admin", "pass")
        assert result == ""

    def test_strips_clixml(self):
        clixml = (
            "#< CLIXML\r\n"
            '<Objs Version="1.1.1.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
            '<S N="Message">[HATCH:INFO][setup][2026-07-20T12:00:00+00:00] Setup started</S>'
            "</Objs>"
        )
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.return_value = self._make_result(clixml)
            result = provision_lib.read_setup_log("1.2.3.4", "admin", "pass")
        assert result == "[HATCH:INFO][setup][2026-07-20T12:00:00+00:00] Setup started"


class TestDeleteSetupLog:
    def test_sends_remove_item(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            provision_lib.delete_setup_log("1.2.3.4", "admin", "pass")
        cmd = mock_sess.return_value.run_ps.call_args[0][0]
        assert "Remove-Item" in cmd
        assert provision_lib.SETUP_LOG_FILE in cmd

    def test_does_not_raise_on_connection_drop(self):
        with patch("lib.provision.winrm.Session") as mock_sess:
            mock_sess.return_value.run_ps.side_effect = ConnectionError("dropped")
            provision_lib.delete_setup_log("1.2.3.4", "admin", "pass")  # must not raise
