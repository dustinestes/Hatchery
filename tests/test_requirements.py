from unittest.mock import patch

from lib.requirements import Requirement, apt_install_command, check_all, missing


class TestCheckAll:
    def test_returns_six_requirements(self):
        with (
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            results = check_all()
        assert len(results) == 6

    def test_all_present_when_tools_found(self):
        with (
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            results = check_all()
        assert all(r.present for r in results)

    def test_all_absent_when_tools_missing(self):
        with (
            patch("shutil.which", return_value=None),
            patch("importlib.util.find_spec", return_value=None),
        ):
            results = check_all()
        assert all(not r.present for r in results)

    def test_cli_tools_use_shutil_which(self):
        with (
            patch("shutil.which", return_value="/usr/bin/tool") as mock_which,
            patch("importlib.util.find_spec", return_value=None),
        ):
            check_all()
        assert mock_which.call_count == 5

    def test_python3_gi_absent_when_find_spec_returns_none(self):
        with (
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("importlib.util.find_spec", return_value=None),
        ):
            results = check_all()
        gi = next(r for r in results if r.name == "python3-gi")
        assert not gi.present

    def test_python3_gi_present_when_find_spec_succeeds(self):
        with (
            patch("shutil.which", return_value="/usr/bin/tool"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            results = check_all()
        gi = next(r for r in results if r.name == "python3-gi")
        assert gi.present

    def test_mixed_present_and_absent(self):
        def which_side(name):
            return "/usr/bin/" + name if name == "virsh" else None

        with (
            patch("shutil.which", side_effect=which_side),
            patch("importlib.util.find_spec", return_value=None),
        ):
            results = check_all()
        virsh = next(r for r in results if r.name == "virsh")
        virt_install = next(r for r in results if r.name == "virt-install")
        assert virsh.present
        assert not virt_install.present

    def test_requirement_fields_populated(self):
        with (
            patch("shutil.which", return_value=None),
            patch("importlib.util.find_spec", return_value=None),
        ):
            results = check_all()
        for r in results:
            assert r.name
            assert r.package
            assert r.required_for

    def test_contains_expected_tools(self):
        with (
            patch("shutil.which", return_value=None),
            patch("importlib.util.find_spec", return_value=None),
        ):
            results = check_all()
        names = {r.name for r in results}
        assert names >= {"virsh", "virt-install", "qemu-img", "virt-make-fs", "swtpm", "python3-gi"}


class TestMissing:
    def test_returns_only_absent_requirements(self):
        checks = [
            Requirement("t1", "p1", "u1", True),
            Requirement("t2", "p2", "u2", False),
            Requirement("t3", "p3", "u3", True),
            Requirement("t4", "p4", "u4", False),
        ]
        result = missing(checks)
        assert len(result) == 2
        assert all(not r.present for r in result)

    def test_empty_when_all_present(self):
        checks = [Requirement("t", "p", "u", True)]
        assert missing(checks) == []

    def test_all_returned_when_all_absent(self):
        checks = [
            Requirement("t1", "p1", "u1", False),
            Requirement("t2", "p2", "u2", False),
        ]
        assert len(missing(checks)) == 2

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

    def test_uses_package_field_not_name(self):
        reqs = [Requirement("python3-gi", "python3-gi", "runtime dep", False)]
        assert "python3-gi" in apt_install_command(reqs)
        assert apt_install_command(reqs).startswith("sudo apt install")
