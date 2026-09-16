import copy

import pytest

from simlab.compiler import ModelError, compile_model
from simlab.extensions import VERSION
from simlab.project import export_package, import_package, load_project, save_project
from simlab.sample import demo_project
from simlab.schema import MODELING_GROUPS, TABLES, table_label


def m3_supply_tables():
    tables = copy.deepcopy(demo_project()["tables"])
    tables["SimLabExecution"] = [{"MODE": "M3"}]
    tables["Station"].append({"STID": "REGIONAL", "DESCR": "区域中心", "TYPE": "DEPOT"})
    tables["StationStructure"][0].update(TFRMS="0", TTOMS="0")
    tables["StationStructure"].append(
        {"STID": "DEPOT", "MSTID": "REGIONAL", "TFRMS": "0", "TTOMS": "0"}
    )
    tables["SimLabSupplyRoute"] = []
    tables["SimLabSupplyPolicy"] = []
    tables["SimLabRepairLocation"] = []
    tables["SimLabServiceRoute"] = []
    for iid in ("POWER", "CONTROL", "PUMP"):
        tables["SimLabSupplyRoute"].extend(
            [
                {"ROUTEID": f"{iid}-R-D", "IID": iid, "FROM_STID": "REGIONAL", "TO_STID": "DEPOT", "TRANSIT_H": "4"},
                {"ROUTEID": f"{iid}-D-B", "IID": iid, "FROM_STID": "DEPOT", "TO_STID": "BASE", "TRANSIT_H": "2"},
            ]
        )
        tables["SimLabSupplyPolicy"].append(
            {"POINT": "BASELINE", "STID": "BASE", "IID": iid, "TRIGGER": "THRESHOLD", "TARGET_QTY": "4", "REORDER_QTY": "1"}
        )
        tables["SimLabRepairLocation"].append(
            {"IID": iid, "FROM_STID": "BASE", "REPAIR_STID": "DEPOT"}
        )
        tables["SimLabServiceRoute"].append(
            {"ROUTEID": f"{iid}-B-D", "IID": iid, "FROM_STID": "BASE", "TO_STID": "DEPOT", "TRANSIT_H": "3"}
        )
    return tables


def one_leaf_new_service_tables():
    tables = m3_supply_tables()
    tables["Item"] = [r for r in tables["Item"] if r["IID"] == "POWER"]
    tables["MaterielStructure"] = [r for r in tables["MaterielStructure"] if r["MID"] == "POWER"]
    tables["StockAllocation"] = [r for r in tables["StockAllocation"] if r["IID"] == "POWER"]
    for name in ("SimLabSupplyRoute", "SimLabSupplyPolicy", "SimLabRepairLocation", "SimLabServiceRoute"):
        tables[name] = [r for r in tables[name] if r["IID"] == "POWER"]
    tables["SimLabRepairLocation"].append(
        {"IID": "POWER", "FROM_STID": "DEPOT", "REPAIR_STID": "DEPOT"}
    )
    tables["ItemRepair"] = []
    tables["ItemReplacement"] = []
    tables["Tasks"].extend(
        [{"TID": "DIAGNOSE"}, {"TID": "SERVICE"}, {"TID": "TEST"}]
    )
    tables["TaskResource"].extend(
        [
            {"TID": "DIAGNOSE", "RID": "TECH", "QTY": "1"},
            {"TID": "SERVICE", "RID": "TECH", "QTY": "1"},
            {"TID": "TEST", "RID": "TECH", "QTY": "1"},
        ]
    )
    tables["SimLabMaintenanceRule"] = [
        {"RULEID": "POWER-CM", "MID": "VEHICLE", "IID": "POWER", "STID": "BASE", "KIND": "CORRECTIVE", "METHOD": "REPLACE"},
        {"RULEID": "POWER-PM", "MID": "VEHICLE", "IID": "POWER", "STID": "BASE", "KIND": "PREVENTIVE", "METHOD": "IN_PLACE"},
    ]
    tables["SimLabMaintenanceStep"] = [
        {"RULEID": "POWER-CM", "STEP": "REMOVE", "DURATION_H": "1", "TASK": "REPLACE"},
        {"RULEID": "POWER-CM", "STEP": "INSTALL", "DURATION_H": "1", "TASK": "REPLACE"},
        {"RULEID": "POWER-CM", "STEP": "TEST", "DURATION_H": "1", "TASK": "TEST"},
        {"RULEID": "POWER-PM", "STEP": "DIAGNOSE", "DURATION_H": "0", "TASK": "DIAGNOSE"},
        {"RULEID": "POWER-PM", "STEP": "IN_PLACE", "DURATION_H": "2", "TASK": "SERVICE"},
        {"RULEID": "POWER-PM", "STEP": "TEST", "DURATION_H": "1", "TASK": "TEST"},
    ]
    tables["SimLabOffItemService"] = [
        {"IID": "POWER", "STID": "DEPOT", "KIND": kind, "STEP": step, "DURATION_H": "1", "TASK": task}
        for kind in ("CORRECTIVE", "PREVENTIVE")
        for step, task in (("DIAGNOSE", "DIAGNOSE"), ("SERVICE", "SERVICE"), ("TEST", "TEST"))
    ]
    tables["SimLabItemPreventive"] = [
        {"PMID": "POWER-PM-CLOCK", "IID": "POWER", "CLOCK": "CALENDAR", "INTERVAL_H": "100"}
    ]
    return tables


def nested_pending_pm_tables():
    tables = one_leaf_new_service_tables()
    tables["Item"][0].update(FRT="0", AFFRT="1")
    tables["Item"].append({"IID": "BOARD", "TYPE": "SRU", "FRT": "0"})
    tables["MaterielStructure"].append({"MID": "BOARD", "MMID": "POWER", "QTYPM": "1"})
    tables["SimLabItemAging"] = [{
        "IID": "BOARD", "SHAPE": "1", "SCALE_H": "1000", "INITIAL_H": "0", "REPAIR": "MINIMAL",
    }]
    tables["SimLabMaintenanceRule"] = []
    tables["SimLabMaintenanceStep"] = []

    def add_rule(ruleid, mid, iid, station, kind, method, probability=""):
        tables["SimLabMaintenanceRule"].append({
            "RULEID": ruleid, "MID": mid, "IID": iid, "STID": station,
            "KIND": kind, "METHOD": method, "REPLACE_P": probability,
        })
        steps = [("TEST", "1")]
        if method in ("IN_PLACE", "MIXED"):
            steps.append(("IN_PLACE", "1"))
        if method in ("REPLACE", "MIXED"):
            steps.extend([("REMOVE", "1"), ("INSTALL", "1")])
        tables["SimLabMaintenanceStep"].extend({
            "RULEID": ruleid, "STEP": step, "DURATION_H": duration, "TASK": "SERVICE",
        } for step, duration in steps)

    add_rule("PARENT-CM", "VEHICLE", "POWER", "BASE", "CORRECTIVE", "REPLACE")
    add_rule("CHILD-CM-D", "POWER", "BOARD", "DEPOT", "CORRECTIVE", "IN_PLACE")
    add_rule("CHILD-PM-S", "POWER", "BOARD", "BASE", "PREVENTIVE", "REPLACE")
    add_rule("CHILD-PM-D", "POWER", "BOARD", "DEPOT", "PREVENTIVE", "IN_PLACE")
    tables["SimLabRepairLocation"] = [
        {"IID": "POWER", "FROM_STID": "BASE", "REPAIR_STID": "DEPOT"},
        {"IID": "BOARD", "FROM_STID": "BASE", "REPAIR_STID": "DEPOT"},
        {"IID": "BOARD", "FROM_STID": "DEPOT", "REPAIR_STID": "DEPOT"},
    ]
    tables["SimLabServiceRoute"] = [
        {"ROUTEID": f"{iid}-B-D", "IID": iid, "FROM_STID": "BASE", "TO_STID": "DEPOT", "TRANSIT_H": "1"}
        for iid in ("POWER", "BOARD")
    ]
    tables["SimLabOffItemService"] = [
        {"IID": "POWER", "STID": "DEPOT", "KIND": "CORRECTIVE", "STEP": step, "DURATION_H": "1", "TASK": "SERVICE"}
        for step in ("DIAGNOSE", "TEST")
    ] + [
        {"IID": "BOARD", "STID": "DEPOT", "KIND": "PREVENTIVE", "STEP": step, "DURATION_H": "1", "TASK": "SERVICE"}
        for step in ("DIAGNOSE", "SERVICE", "TEST")
    ]
    tables["SimLabItemPreventive"] = [{
        "PMID": "BOARD-PM", "IID": "BOARD", "CLOCK": "OPERATING", "INTERVAL_H": "10",
    }]
    return tables


def test_m3_metadata_is_chinese_and_tables_are_navigable():
    expected = {
        "SimLabExecution", "SimLabSupplyRoute", "SimLabSupplyPolicy",
        "SimLabRepairLocation", "SimLabServiceRoute", "SimLabMaintenanceRule",
        "SimLabMaintenanceStep", "SimLabOffItemService", "SimLabItemPreventive",
    }
    assert expected <= TABLES.keys()
    assert expected <= {table for group in MODELING_GROUPS.values() for table in group}
    assert all(table_label(name) != name for name in expected)
    assert VERSION == 10


def test_m3_allows_three_levels_and_returns_canonical_defaulted_tables():
    config = compile_model(m3_supply_tables())
    assert config["links"]["DEPOT"]["parent"] == "REGIONAL"
    assert config["m3"]["tables"]["SimLabSupplyPolicy"][0] == {
        "POINT": "BASELINE", "STID": "BASE", "IID": "POWER",
        "TRIGGER": "THRESHOLD", "TARGET_QTY": "4", "REORDER_QTY": "1",
        "FIRST_H": "0", "INTERVAL_H": "",
    }
    assert config["m3"]["tables"]["Control"][0]["APID"] == "BASELINE"
    assert config["stock"][("BASE", "POWER")] == 2


def test_m3_tables_require_explicit_execution_mode():
    tables = copy.deepcopy(demo_project()["tables"])
    tables["SimLabSupplyRoute"] = []
    tables["SimLabSupplyPolicy"] = [{
        "POINT": "BASELINE", "STID": "BASE", "IID": "POWER",
        "TRIGGER": "THRESHOLD", "TARGET_QTY": "2", "REORDER_QTY": "1",
    }]
    with pytest.raises(ModelError, match="MODE=M3"):
        compile_model(tables)


def test_legacy_mode_keeps_two_level_constraint_and_output_shape():
    legacy = copy.deepcopy(demo_project()["tables"])
    before = compile_model(legacy)
    legacy["Station"].append({"STID": "REGIONAL", "TYPE": "DEPOT"})
    legacy["StationStructure"].append({"STID": "DEPOT", "MSTID": "REGIONAL", "TFRMS": "0", "TTOMS": "0"})
    with pytest.raises(ModelError, match="两级"):
        compile_model(legacy)
    assert "m3" not in before
    assert before["fleets"][0]["root"] == "DEPOT"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda t: t["StationStructure"][0].update(TFRMS="1"), "TFRMS"),
        (lambda t: t["SimLabSupplyRoute"][0].update(FROM_STID="BASE", TO_STID="REGIONAL"), "补给路线"),
        (lambda t: t["SimLabServiceRoute"][0].update(FROM_STID="REGIONAL", TO_STID="BASE"), "送修路线"),
        (lambda t: t["StationStructure"].append({"STID": "REGIONAL", "MSTID": "BASE"}), "循环"),
    ],
)
def test_m3_rejects_illegal_hierarchy_or_route_direction(mutate, message):
    tables = m3_supply_tables()
    mutate(tables)
    with pytest.raises(ModelError, match=message):
        compile_model(tables)


def test_m3_rejects_duplicate_route_and_invalid_threshold_policy():
    tables = m3_supply_tables()
    duplicate = copy.deepcopy(tables["SimLabSupplyRoute"][0])
    duplicate["ROUTEID"] = "OTHER-ID"
    tables["SimLabSupplyRoute"].append(duplicate)
    tables["SimLabSupplyPolicy"][0].update(TARGET_QTY="1", REORDER_QTY="1")
    with pytest.raises(ModelError) as raised:
        compile_model(tables)
    text = "\n".join(raised.value.errors)
    assert "重复" in text and "TARGET_QTY" in text


def test_m3_rejects_four_level_tree_and_excessive_periodic_orders():
    tables = m3_supply_tables()
    tables["Station"].append({"STID": "NATIONAL", "TYPE": "DEPOT"})
    tables["StationStructure"].append({"STID": "REGIONAL", "MSTID": "NATIONAL"})
    tables["SimLabSupplyPolicy"][0].update(
        TRIGGER="PERIODIC", REORDER_QTY="", FIRST_H="0", INTERVAL_H="0.000001"
    )
    with pytest.raises(ModelError) as raised:
        compile_model(tables)
    text = "\n".join(raised.value.errors)
    assert "三级" in text and "200000" in text


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"TRIGGER": "PERIODIC", "FIRST_H": "0", "INTERVAL_H": "0"}, "INTERVAL_H"),
        ({"TRIGGER": "THRESHOLD", "FIRST_H": "1"}, "FIRST_H"),
        ({"TARGET_QTY": "nan"}, "有限"),
    ],
)
def test_m3_supply_policy_modes_are_strict(changes, message):
    tables = m3_supply_tables()
    tables["SimLabSupplyPolicy"][0].update(changes)
    with pytest.raises(ModelError, match=message):
        compile_model(tables)


def test_m3_threshold_cannot_be_negative():
    tables = m3_supply_tables()
    tables["SimLabSupplyPolicy"][0]["REORDER_QTY"] = "-1"
    with pytest.raises(ModelError, match="REORDER_QTY"):
        compile_model(tables)


def test_supply_only_mode_accepts_legacy_repairs_with_explicit_location():
    config = compile_model(m3_supply_tables())
    assert config["repairs"][("DEPOT", "POWER")]["time"]["mean"] == 48
    assert config["replacements"][("VEHICLE", "POWER", "BASE")]["time"]["mean"] == 2


def test_supply_only_mode_rejects_missing_explicit_legacy_repair_location():
    tables = m3_supply_tables()
    tables["SimLabRepairLocation"] = [
        row for row in tables["SimLabRepairLocation"] if row["IID"] != "POWER"
    ]
    with pytest.raises(ModelError, match="POWER.*显式维修地点"):
        compile_model(tables)


def test_new_service_rules_do_not_require_legacy_repair_or_replacement_rows():
    config = compile_model(one_leaf_new_service_tables())
    assert config["repairs"] == {}
    assert config["replacements"] == {}
    assert config["m3"]["tables"]["SimLabMaintenanceRule"][0]["REPLACE_P"] == ""


def test_new_and_legacy_rules_cannot_overlap_same_context():
    tables = one_leaf_new_service_tables()
    tables["ItemRepair"] = [{"IID": "POWER", "STID": "DEPOT", "DIRPT": "2", "SURPT": "0"}]
    tables["ItemReplacement"] = [{"MID": "VEHICLE", "IID": "POWER", "STID": "BASE", "SURPT": "1"}]
    with pytest.raises(ModelError, match="新旧非等价"):
        compile_model(tables)


def test_new_off_item_service_conflicts_with_legacy_repair_same_context():
    tables = one_leaf_new_service_tables()
    tables["ItemRepair"] = [{"IID": "POWER", "STID": "DEPOT", "DIRPT": "2", "SURPT": "0"}]
    with pytest.raises(ModelError, match="ItemRepair.*新旧非等价"):
        compile_model(tables)


def test_new_preventive_can_coexist_with_explicit_legacy_corrective_rules():
    tables = one_leaf_new_service_tables()
    tables["SimLabMaintenanceRule"] = [tables["SimLabMaintenanceRule"][1]]
    tables["SimLabMaintenanceStep"] = [
        row for row in tables["SimLabMaintenanceStep"] if row["RULEID"] == "POWER-PM"
    ]
    tables["SimLabOffItemService"] = [
        row for row in tables["SimLabOffItemService"] if row["KIND"] == "PREVENTIVE"
    ]
    tables["ItemRepair"] = [{"IID": "POWER", "STID": "DEPOT", "DIRPT": "2", "SURPT": "0"}]
    tables["ItemReplacement"] = [{"MID": "VEHICLE", "IID": "POWER", "STID": "BASE", "SURPT": "1"}]
    config = compile_model(tables)
    assert config["repairs"][("DEPOT", "POWER")]["time"]["mean"] == 2


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda t: t["SimLabMaintenanceRule"][0].update(METHOD="MIXED", REPLACE_P="1.1"), "REPLACE_P"),
        (lambda t: t["SimLabMaintenanceRule"][0].update(METHOD="REPLACE", REPLACE_P="0.5"), "REPLACE_P"),
        (lambda t: t["SimLabMaintenanceStep"][0].update(STEP="IN_PLACE"), "工序"),
        (lambda t: t["SimLabMaintenanceStep"][0].update(TASK="ABSENT"), "不存在"),
        (lambda t: t["SimLabItemPreventive"][0].update(INTERVAL_H="0"), "INTERVAL_H"),
    ],
)
def test_m3_service_probabilities_steps_resources_and_clocks_are_strict(mutate, message):
    tables = one_leaf_new_service_tables()
    mutate(tables)
    with pytest.raises(ModelError, match=message):
        compile_model(tables)


def test_preventive_clock_rejects_parent_item():
    tables = one_leaf_new_service_tables()
    tables["Item"].append({"IID": "BOARD", "TYPE": "SRU", "FRT": "0"})
    tables["MaterielStructure"].append({"MID": "BOARD", "MMID": "POWER", "QTYPM": "1"})
    with pytest.raises(ModelError, match="叶子"):
        compile_model(tables)


def test_preventive_rule_requires_leaf_clock_and_every_clock_requires_context():
    tables = one_leaf_new_service_tables()
    tables["SimLabItemPreventive"] = []
    with pytest.raises(ModelError, match="预防时钟"):
        compile_model(tables)

    tables = one_leaf_new_service_tables()
    tables["SimLabMaintenanceRule"] = [
        row for row in tables["SimLabMaintenanceRule"] if row["KIND"] != "PREVENTIVE"
    ]
    tables["SimLabMaintenanceStep"] = [
        row for row in tables["SimLabMaintenanceStep"] if row["RULEID"] != "POWER-PM"
    ]
    with pytest.raises(ModelError, match="PREVENTIVE"):
        compile_model(tables)


def test_parent_off_item_allows_diagnose_and_test_but_forbids_service():
    tables = one_leaf_new_service_tables()
    tables["SimLabMaintenanceRule"] = [tables["SimLabMaintenanceRule"][0]]
    tables["SimLabMaintenanceStep"] = [
        row for row in tables["SimLabMaintenanceStep"] if row["RULEID"] == "POWER-CM"
    ]
    tables["SimLabItemPreventive"] = []
    power = tables["Item"][0]
    power.update(FRT="0", AFFRT="1")
    tables["Item"].append({"IID": "BOARD", "TYPE": "SRU", "FRT": "100"})
    tables["MaterielStructure"].append({"MID": "BOARD", "MMID": "POWER", "QTYPM": "1"})
    tables["SimLabMaintenanceRule"].append({
        "RULEID": "BOARD-CM", "MID": "POWER", "IID": "BOARD", "STID": "DEPOT",
        "KIND": "CORRECTIVE", "METHOD": "IN_PLACE",
    })
    tables["SimLabMaintenanceStep"].extend([
        {"RULEID": "BOARD-CM", "STEP": "IN_PLACE", "DURATION_H": "1", "TASK": "SERVICE"},
        {"RULEID": "BOARD-CM", "STEP": "TEST", "DURATION_H": "1", "TASK": "TEST"},
    ])
    tables["SimLabOffItemService"] = [
        row for row in tables["SimLabOffItemService"] if row["STEP"] != "SERVICE"
    ]
    compile_model(tables)

    tables["SimLabOffItemService"].append({
        "IID": "POWER", "STID": "DEPOT", "KIND": "CORRECTIVE",
        "STEP": "SERVICE", "DURATION_H": "1", "TASK": "SERVICE",
    })
    with pytest.raises(ModelError, match="父项.*SERVICE"):
        compile_model(tables)


def test_predictable_preventive_jobs_respect_per_replication_cap():
    tables = one_leaf_new_service_tables()
    tables["Control"][0].update(SIMPE="300000", RCINT="100")
    tables["SimLabItemPreventive"][0]["INTERVAL_H"] = "1"
    with pytest.raises(ModelError, match="200000.*服务工单"):
        compile_model(tables)


def test_large_preventive_initial_age_counts_as_one_initial_due_not_past_cycles():
    tables = one_leaf_new_service_tables()
    tables["Item"][0]["FRT"] = "0"
    tables["Control"][0].update(SIMPE="2", RCINT="1")
    tables["SimLabItemPreventive"][0].update(
        CLOCK="OPERATING", INTERVAL_H="100", INITIAL_H="10000000"
    )
    compile_model(tables)


def test_calendar_pm_stock_site_requires_mapping_and_preventive_offitem_steps():
    tables = one_leaf_new_service_tables()
    tables["SimLabRepairLocation"] = [
        row for row in tables["SimLabRepairLocation"] if row["FROM_STID"] != "DEPOT"
    ]
    with pytest.raises(ModelError, match="CALENDAR.*POWER@DEPOT.*维修地点"):
        compile_model(tables)

    tables = one_leaf_new_service_tables()
    tables["SimLabOffItemService"] = [
        row for row in tables["SimLabOffItemService"] if row["KIND"] != "PREVENTIVE"
    ]
    with pytest.raises(ModelError, match="POWER@DEPOT/PREVENTIVE.*SERVICE"):
        compile_model(tables)


def test_every_deployed_part_has_corrective_coverage():
    tables = one_leaf_new_service_tables()
    tables["SimLabMaintenanceRule"] = [
        row for row in tables["SimLabMaintenanceRule"] if row["KIND"] != "CORRECTIVE"
    ]
    tables["SimLabMaintenanceStep"] = [
        row for row in tables["SimLabMaintenanceStep"] if row["RULEID"] != "POWER-CM"
    ]
    with pytest.raises(ModelError, match="VEHICLE/POWER@BASE.*CORRECTIVE"):
        compile_model(tables)


def test_pending_minimal_leaf_pm_method_is_compatible_after_parent_relocation():
    tables = nested_pending_pm_tables()
    with pytest.raises(ModelError, match="CHILD-PM-S.*DEPOT.*REPLACE"):
        compile_model(tables)

    destination = next(
        row for row in tables["SimLabMaintenanceRule"] if row["RULEID"] == "CHILD-PM-D"
    )
    destination.update(METHOD="MIXED", REPLACE_P="0")
    tables["SimLabMaintenanceStep"].extend([
        {"RULEID": "CHILD-PM-D", "STEP": "REMOVE", "DURATION_H": "1", "TASK": "SERVICE"},
        {"RULEID": "CHILD-PM-D", "STEP": "INSTALL", "DURATION_H": "1", "TASK": "SERVICE"},
    ])
    compile_model(tables)


def test_pending_healthy_sibling_pm_is_checked_even_when_broken_leaf_repairs_perfectly():
    tables = nested_pending_pm_tables()
    tables["SimLabItemAging"][0]["REPAIR"] = "PERFECT"
    # With one leaf, that leaf caused the parent replacement and PERFECT
    # corrective work covers its queued PM before any destination rebind.
    compile_model(tables)

    next(row for row in tables["MaterielStructure"] if row["MID"] == "BOARD")["QTYPM"] = "2"
    # With a sibling, a healthy leaf may already hold the incompatible queued PM
    # while the other leaf triggers parent replacement.
    with pytest.raises(ModelError, match="CHILD-PM-S.*DEPOT.*REPLACE"):
        compile_model(tables)


def test_service_resource_bundle_must_have_capacity_and_common_shift():
    tables = one_leaf_new_service_tables()
    tables["TaskResource"].append({"TID": "SERVICE", "RID": "BAY", "QTY": "1"})
    for row in tables["ResourceAllocation"]:
        if row["STID"] == "DEPOT" and row["RID"] == "BAY":
            row["RQTY"] = "0"
    with pytest.raises(ModelError, match="资源 BAY 数量不足"):
        compile_model(tables)

    tables = one_leaf_new_service_tables()
    tables["TaskResource"].append({"TID": "SERVICE", "RID": "BAY", "QTY": "1"})
    tables["Shift"] = [{"SHID": "TECH_SHIFT"}, {"SHID": "BAY_SHIFT"}]
    tables["ShiftProfile"] = [
        {"SHPID": "TECH_ONLY", "SSHPID": "TECH_SHIFT", "STIM": "0", "ETIM": "10"},
        {"SHPID": "BAY_ONLY", "SSHPID": "BAY_SHIFT", "STIM": "20", "ETIM": "30"},
    ]
    tables["ResourceStationData"] = [
        {"RID": "TECH", "STID": "DEPOT", "SHPID": "TECH_ONLY"},
        {"RID": "BAY", "STID": "DEPOT", "SHPID": "BAY_ONLY"},
    ]
    with pytest.raises(ModelError, match="共同班次"):
        compile_model(tables)


def test_version_10_roundtrip_upgrades_old_project_and_preserves_runs(tmp_path):
    old = demo_project()
    old["extensions_version"] = 1
    old["runs"] = [{"id": "historic", "status": "completed", "result": {"value": 1}}]
    database = tmp_path / "old.sqlite"
    save_project(old, database)
    loaded = load_project(database)
    assert loaded["extensions_version"] == 10
    assert loaded["runs"] == old["runs"]
    package = tmp_path / "model.simproj"
    export_package(loaded, package)
    imported = import_package(package)
    assert imported["extensions_version"] == 10
    assert imported["runs"] == old["runs"]


def test_project_rejects_future_extension_version():
    project = demo_project()
    project["extensions_version"] = 11
    with pytest.raises(ValueError, match="扩展格式版本"):
        save_project(project, "future.sqlite")
