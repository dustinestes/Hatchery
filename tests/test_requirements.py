from unittest.mock import MagicMock, patch

from lib.requirements import (
    NestToolSpec,
    Requirement,
    _check_python3_gi,
    apt_install_command,
    check_all,
    check_controller,
    check_nest_tools_local,
    install_hint,
    missing,
    package_for_current_os,
)


class TestCheckPython3Gi:
    def test_present_when_dpkg_reports_installed(self):
        with (
            patch("shutil.which", return_value="/usr/bin/dpkg-query"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="install ok installed")
            assert _check_python3_gi() is True

    def test_absent_when_dpkg_reports_not_installed(self):
        with (
            patch("shutil.which", return_value="/usr/bin/dpkg-query"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="unknown ok not-installed")
            assert _check_python3_gi() is False

    def test_absent_when_dpkg_query_fails(self):
        with (
            patch("shutil.which", return_value="/usr/bin/dpkg-query"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert _check_python3_gi() is False

    def test_absent_when_dpkg_query_missing_and_import_fails(self):
        import builtins

        real_import = builtins.__import__

        def _import(name, *args, **kwargs):
            if name == "gi" or name.startswith("gi."):
                raise ImportError("no gi")
            return real_import(name, *args, **kwargs)

        with (
            patch("shutil.which", return_value=None),
            patch("builtins.__import__", side_effect=_import),
        ):
            assert _check_python3_gi() is False

    def test_absent_when_dpkg_query_raises_oserror(self):
        with (
            patch("shutil.which", return_value="/usr/bin/dpkg-query"),
            patch("subprocess.run", side_effect=FileNotFoundError("dpkg-query")),
        ):
            assert _check_python3_gi() is False

    def test_uses_dpkg_query(self):
        with (
            patch("shutil.which", return_value="/usr/bin/dpkg-query"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="install ok installed")
            _check_python3_gi()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "dpkg-query"
        assert "python3-gi" in cmd


class TestCheckController:
    def test_no_ssh_when_no_remote_nests(self):
        with patch("shutil.which", return_value=None):
            results = check_controller(nests=[{"id": "local", "location": "local"}])
        names = {r.name for r in results}
        assert "ssh" not in names
        assert "pwsh" in names

    def test_ssh_required_when_remote_nest_present(self):
        nests = [
            {"id": "local", "location": "local"},
            {"id": "r1", "location": "remote"},
        ]
        with patch("shutil.which", return_value=None):
            results = check_controller(nests=nests)
        ssh = next(r for r in results if r.name == "ssh")
        assert not ssh.present
        assert ssh.optional is False
        assert ssh.role == "controller"
        assert ssh.install_hint

    def test_ssh_present(self):
        nests = [{"id": "r1", "location": "remote"}]
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            results = check_controller(nests=nests)
        ssh = next(r for r in results if r.name == "ssh")
        assert ssh.present

    def test_check_all_is_controller_only(self):
        with (
            patch("shutil.which", return_value=None),
            patch("lib.requirements.has_remote_nests", return_value=False),
        ):
            results = check_all()
        names = {r.name for r in results}
        assert "virsh" not in names
        assert "pwsh" in names

    def test_pwsh_marked_optional(self):
        with patch("shutil.which", return_value=None):
            results = check_controller(nests=[])
        pwsh = next(r for r in results if r.name == "pwsh")
        assert pwsh.optional is True


class TestNestToolsLocal:
    def test_libvirt_specs_evaluate(self):
        from lib.providers.libvirt import LibvirtProvider

        specs = LibvirtProvider.nest_tool_specs()
        assert {s.name for s in specs} >= {"virsh", "virt-install", "python3-gi"}

        with (
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("lib.requirements._check_python3_gi", return_value=True),
        ):
            results = check_nest_tools_local(specs)
        assert all(r.present for r in results)
        assert all(r.role == "nest" for r in results)

    def test_missing_virsh(self):
        specs = [
            NestToolSpec(
                name="virsh",
                required_for="ops",
                packages={"linux": "libvirt-clients"},
            )
        ]
        with patch("shutil.which", return_value=None):
            results = check_nest_tools_local(specs)
        assert len(results) == 1
        assert not results[0].present
        assert "apt install" in results[0].install_hint or results[0].install_hint


class TestInstallHint:
    def test_linux_apt(self):
        with patch("lib.requirements._os_key", return_value="linux"):
            assert install_hint("openssh-client") == "sudo apt install openssh-client"

    def test_macos_brew(self):
        with patch("lib.requirements._os_key", return_value="macos"):
            assert install_hint("openssh") == "brew install openssh"

    def test_windows_winget(self):
        with patch("lib.requirements._os_key", return_value="windows"):
            assert install_hint("OpenSSH.Client") == "winget install OpenSSH.Client"

    def test_package_for_os(self):
        pkgs = {"linux": "a", "macos": "b", "windows": "c"}
        with patch("lib.requirements._os_key", return_value="macos"):
            assert package_for_current_os(pkgs) == "b"


class TestPwshAvailable:
    def test_returns_true_when_found(self):
        from lib.requirements import pwsh_available

        with patch("shutil.which", return_value="/usr/bin/pwsh"):
            assert pwsh_available() is True

    def test_returns_false_when_missing(self):
        from lib.requirements import pwsh_available

        with patch("shutil.which", return_value=None):
            assert pwsh_available() is False


class TestMissing:
    def test_returns_only_absent_required(self):
        checks = [
            Requirement("t1", "p1", "u1", True),
            Requirement("t2", "p2", "u2", False),
            Requirement("t3", "p3", "u3", False, optional=True),
        ]
        result = missing(checks)
        assert len(result) == 1
        assert result[0].name == "t2"

    def test_empty_when_all_present(self):
        checks = [Requirement("t", "p", "u", True)]
        assert missing(checks) == []

    def test_empty_input_returns_empty(self):
        assert missing([]) == []


class TestAptInstallCommand:
    def test_single_package(self):
        reqs = [Requirement("virsh", "libvirt-clients", "VM ops", False)]
        assert apt_install_command(reqs) == "sudo apt install libvirt-clients"

    def test_multiple_packages(self):
        reqs = [
            Requirement("virsh", "libvirt-clients", "VM ops", False),
            Requirement("virt-install", "virtinst", "VM creation", False),
        ]
        cmd = apt_install_command(reqs)
        assert cmd == "sudo apt install libvirt-clients virtinst"

    def test_empty_list_returns_empty_string(self):
        assert apt_install_command([]) == ""

    def test_skips_optional(self):
        reqs = [Requirement("pwsh", "powershell", "scripts", False, optional=True)]
        assert apt_install_command(reqs) == ""
