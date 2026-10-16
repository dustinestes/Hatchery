"""Tests for discovered script parameter metadata (#571)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from lib import script_params as sp


def test_detect_kind():
    assert sp.detect_kind("setup.ps1") == "powershell"
    assert sp.detect_kind("setup.sh") == "shell"
    assert sp.detect_kind("setup.bash") == "shell"
    assert sp.detect_kind("notes.txt") == "unknown"


def test_shell_and_unknown_introspect_return_empty(tmp_path):
    sh = tmp_path / "run.sh"
    sh.write_text("#!/bin/sh\necho hi\n")
    assert sp.introspect(sh) == []
    assert sp.introspect(tmp_path / "missing.ps1") == []


def test_validate_bool_rejects_string_true_literal_style():
    specs = [sp.ParamSpec(name="IncludeManagementTools", kind="bool", source_kind="powershell")]
    # Coercion accepts "True"/"true" — validate should pass after coerce path.
    assert sp.validate_values(specs, {"IncludeManagementTools": "True"}) == []
    assert sp.validate_values(specs, {"IncludeManagementTools": "nope"}) == [
        "IncludeManagementTools: expected boolean, got 'nope'"
    ]


def test_validate_mandatory_and_validate_set_and_length():
    specs = [
        sp.ParamSpec(name="Env", kind="string", mandatory=True, allowed_values=("dev", "prod")),
        sp.ParamSpec(name="ComputerName", kind="string", min_length=1, max_length=15),
    ]
    assert "Env: required" in sp.validate_values(specs, {})
    assert any("one of" in e for e in sp.validate_values(specs, {"Env": "qa"}))
    assert any(
        "at most 15" in e
        for e in sp.validate_values(specs, {"Env": "dev", "ComputerName": "x" * 16})
    )
    assert sp.validate_values(specs, {"Env": "dev", "ComputerName": "dc01"}) == []


def test_encode_powershell_bool_not_quoted_string():
    specs = [
        sp.ParamSpec(name="IncludeManagementTools", kind="bool", source_kind="powershell"),
        sp.ParamSpec(name="Force", kind="switch", source_kind="powershell"),
        sp.ParamSpec(name="Count", kind="int", source_kind="powershell"),
        sp.ParamSpec(name="Name", kind="string", source_kind="powershell"),
    ]
    args = sp.encode_powershell_args(
        specs,
        {
            "IncludeManagementTools": "True",
            "Force": True,
            "Count": "3",
            "Name": "lab's",
        },
    )
    assert "-IncludeManagementTools $true" in args
    assert "'True'" not in args
    assert "-Force" in args
    assert "-Force:$false" not in args
    assert "-Count 3" in args
    assert "-Name 'lab''s'" in args


def test_encode_switch_false():
    specs = [sp.ParamSpec(name="Force", kind="switch")]
    assert sp.encode_powershell_args(specs, {"Force": False}) == "-Force:$false"


def test_looks_like_param_binding_failure():
    assert sp.looks_like_param_binding_failure(
        "Cannot process argument transformation on parameter 'IncludeManagementTools'."
    )
    assert not sp.looks_like_param_binding_failure("Script complete")


def test_validate_clutch_vms_uses_introspect(monkeypatch, tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "enable.ps1"
    script.write_text("param([bool]$IncludeManagementTools)\n")

    def fake_introspect(path):
        assert Path(path).name == "enable.ps1"
        return [
            sp.ParamSpec(
                name="IncludeManagementTools",
                kind="bool",
                source_kind="powershell",
            )
        ]

    monkeypatch.setattr(sp, "introspect", fake_introspect)
    vm = SimpleNamespace(
        name="LAB",
        automations=[
            SimpleNamespace(
                type="script",
                name="enable.ps1",
                parameters={"IncludeManagementTools": "not-a-bool"},
            )
        ],
    )
    errors = sp.validate_clutch_vms([vm], scripts_dir=scripts)
    assert errors
    assert "LAB / enable.ps1" in errors[0]


def test_validate_clutch_vms_skips_when_no_metadata(monkeypatch, tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run.sh").write_text("#!/bin/sh\n")
    monkeypatch.setattr(sp, "introspect", lambda _p: [])
    vm = SimpleNamespace(
        name="LAB",
        automations=[
            SimpleNamespace(type="script", name="run.sh", parameters={"x": "1"}),
        ],
    )
    assert sp.validate_clutch_vms([vm], scripts_dir=scripts) == []


def test_param_spec_from_ps_row_switch_and_validateset():
    row = {
        "Name": "Mode",
        "Type": "String",
        "FullName": "System.String",
        "Mandatory": True,
        "HelpMessage": "pick one",
        "Default": None,
        "ValidateSet": ["A", "B"],
        "MinLength": 1,
        "MaxLength": 8,
    }
    spec = sp._param_spec_from_ps_row(row)
    assert spec.kind == "string"
    assert spec.allowed_values == ("A", "B")
    assert spec.min_length == 1
    assert spec.max_length == 8

    sw = sp._param_spec_from_ps_row(
        {
            "Name": "Force",
            "Type": "SwitchParameter",
            "FullName": "System.Management.Automation.SwitchParameter",
            "Mandatory": False,
            "ValidateSet": [],
            "MinLength": None,
            "MaxLength": None,
        }
    )
    assert sw.kind == "switch"


def test_specs_to_api_includes_kind():
    specs = [
        sp.ParamSpec(
            name="Env",
            kind="string",
            allowed_values=("dev",),
            min_length=1,
            max_length=10,
            source_kind="powershell",
            raw_type="String",
        )
    ]
    api = sp.specs_to_api(specs)[0]
    assert api["kind"] == "string"
    assert api["allowed_values"] == ["dev"]
    assert api["min_length"] == 1
    assert api["type"] == "String"


def test_introspect_powershell_parses_mocked_pwsh(monkeypatch, tmp_path):
    script = tmp_path / "enable.ps1"
    script.write_text("param([bool]$IncludeManagementTools = $true)\n")

    class Result:
        returncode = 0
        stdout = (
            '[{"Name":"IncludeManagementTools","Type":"Boolean",'
            '"FullName":"System.Boolean","Mandatory":false,'
            '"HelpMessage":null,"Default":"True","ValidateSet":[],'
            '"MinLength":null,"MaxLength":null}]'
        )
        stderr = ""

    monkeypatch.setattr(sp.shutil, "which", lambda _n: "/usr/bin/pwsh")
    monkeypatch.setattr(sp.subprocess, "run", lambda *a, **k: Result())
    specs = sp.introspect(script)
    assert len(specs) == 1
    assert specs[0].kind == "bool"
    assert specs[0].name == "IncludeManagementTools"


def test_coerce_parameters_bool():
    specs = [sp.ParamSpec(name="Flag", kind="bool")]
    assert sp.coerce_parameters(specs, {"Flag": "yes"}) == {"Flag": True}


def test_coerce_int_and_float_and_reject_bool():
    import pytest

    assert sp.coerce_value(sp.ParamSpec(name="N", kind="int"), "7") == 7
    assert sp.coerce_value(sp.ParamSpec(name="N", kind="float"), "1.5") == 1.5
    with pytest.raises(ValueError, match="integer"):
        sp.coerce_value(sp.ParamSpec(name="N", kind="int"), True)
    with pytest.raises(ValueError, match="number"):
        sp.coerce_value(sp.ParamSpec(name="N", kind="float"), "x")


def test_encode_unknown_key_quoted_and_skip_empty():
    specs = [sp.ParamSpec(name="Known", kind="string")]
    args = sp.encode_powershell_args(
        specs, {"Known": "a", "Extra": "b", "Empty": "", "NoneVal": None}
    )
    assert "-Known 'a'" in args
    assert "-Extra 'b'" in args
    assert "Empty" not in args
    assert "NoneVal" not in args


def test_param_spec_asdict_lists_allowed():
    spec = sp.ParamSpec(name="Env", kind="string", allowed_values=("a", "b"))
    data = sp.param_spec_asdict(spec)
    assert data["allowed_values"] == ["a", "b"]


def test_validate_min_length():
    specs = [sp.ParamSpec(name="Name", kind="string", min_length=3)]
    assert any("at least 3" in e for e in sp.validate_values(specs, {"Name": "ab"}))


def test_ps_numeric_bounds_unsigned_and_byte():
    assert sp._ps_numeric_bounds("UInt32", "System.UInt32", "int") == (0, None)
    assert sp._ps_numeric_bounds("Byte", "System.Byte", "int") == (0, 255)
    assert sp._ps_numeric_bounds("Int32", "System.Int32", "int") == (None, None)


def test_validate_rejects_negative_uint():
    specs = [
        sp.ParamSpec(name="RetryCount", kind="int", min_value=0, raw_type="UInt32"),
    ]
    assert any("at least 0" in e for e in sp.validate_values(specs, {"RetryCount": -1}))
    assert sp.validate_values(specs, {"RetryCount": 2}) == []


def test_param_spec_from_ps_row_uint_sets_min_value():
    spec = sp._param_spec_from_ps_row(
        {
            "Name": "RetryCount",
            "Type": "UInt32",
            "FullName": "System.UInt32",
            "Mandatory": False,
            "ValidateSet": [],
            "MinLength": None,
            "MaxLength": None,
        }
    )
    assert spec.kind == "int"
    assert spec.min_value == 0
    api = spec.to_api_dict()
    assert api["min_value"] == 0


def test_clutch_yaml_roundtrip_preserves_bool_native(tmp_path):
    """Typed natives survive Clutch export/load (#571)."""
    from lib import clutch as clutch_lib
    from lib.clutch import AutomationEntry, Clutch, VMConfig

    path = tmp_path / "lab.yaml"
    clutch = Clutch(
        name="Lab",
        vms=[
            VMConfig(
                name="dc01",
                os="windows",
                vcpus=2,
                ram_gb=4,
                disk_gb=40,
                os_media="win.iso",
                automations=[
                    AutomationEntry(
                        type="script",
                        name="enable.ps1",
                        parameters={"IncludeManagementTools": True, "Count": 3},
                    )
                ],
            )
        ],
    )
    clutch_lib.save(clutch, path)
    text = path.read_text()
    assert "IncludeManagementTools: true" in text or "IncludeManagementTools: True" in text
    assert "Count: 3" in text
    loaded = clutch_lib.load(path)
    params = loaded.vms[0].automations[0].parameters
    assert params["IncludeManagementTools"] is True
    assert params["Count"] == 3
