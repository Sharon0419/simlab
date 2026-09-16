import copy

import pytest

from simlab.compiler import ModelError, SUPPORTED, compile_model
from simlab.extensions import VERSION
from simlab.schema import MODELING_GROUPS, TABLES, table_label
from tests.test_m3_config import m3_supply_tables, one_leaf_new_service_tables


def purchase(tables, **changes):
    row = {
        "POINT": "BASELINE", "STID": "BASE", "IID": "POWER",
        "TRIGGER": "THRESHOLD", "TARGET_QTY": "4", "REORDER_QTY": "1",
        "FIRST_H": "0", "INTERVAL_H": "", "LEAD_H": "3",
    }
    row.update(changes)
    tables["SimLabPurchasePolicy"] = [row]
    return row


def test_procurement_and_retirement_metadata_and_canonical_roundtrip():
    tables = one_leaf_new_service_tables()
    purchase(tables)
    tables["SimLabItemRetirement"] = [{"IID": "POWER", "LIMIT_H": "100", "LIMIT_REPAIRS": "2"}]
    config = compile_model(tables)

    assert VERSION >= 11
    assert set(SUPPORTED["SimLabPurchasePolicy"]) == {
        "POINT", "STID", "IID", "TRIGGER", "TARGET_QTY", "REORDER_QTY",
        "FIRST_H", "INTERVAL_H", "LEAD_H",
    }
    assert set(SUPPORTED["SimLabItemRetirement"]) == {"IID", "LIMIT_H", "LIMIT_REPAIRS"}
    assert all(name in TABLES for name in ("SimLabPurchasePolicy", "SimLabItemRetirement"))
    assert all(table_label(name) != name for name in ("SimLabPurchasePolicy", "SimLabItemRetirement"))
    assert {"SimLabPurchasePolicy", "SimLabItemRetirement"} <= {
        name for group in MODELING_GROUPS.values() for name in group
    }
    assert config["m3"]["tables"]["SimLabPurchasePolicy"][0]["LEAD_H"] == "3"
    assert config["m3"]["tables"]["SimLabItemRetirement"][0] == {
        "IID": "POWER", "LIMIT_H": "100", "LIMIT_REPAIRS": "2",
    }


@pytest.mark.parametrize("changes,message", [
    ({"LEAD_H": "-1"}, "LEAD_H"),
    ({"TRIGGER": "THRESHOLD", "INTERVAL_H": "1"}, "INTERVAL_H"),
    ({"TRIGGER": "THRESHOLD", "FIRST_H": "1"}, "FIRST_H"),
    ({"TRIGGER": "PERIODIC", "REORDER_QTY": "1", "INTERVAL_H": "2"}, "REORDER_QTY"),
    ({"TRIGGER": "PERIODIC", "REORDER_QTY": "", "INTERVAL_H": "0"}, "INTERVAL_H"),
    ({"TARGET_QTY": "1", "REORDER_QTY": "1"}, "TARGET_QTY"),
])
def test_purchase_policy_validation(changes, message):
    tables = m3_supply_tables()
    purchase(tables, **changes)
    with pytest.raises(ModelError, match=message):
        compile_model(tables)


def test_purchase_needs_no_inbound_route_and_periodic_workload_is_bounded():
    tables = m3_supply_tables()
    tables["SimLabSupplyRoute"] = []
    tables["SimLabSupplyPolicy"] = []
    purchase(tables, TRIGGER="PERIODIC", REORDER_QTY="", FIRST_H="0", INTERVAL_H="1")
    compile_model(tables)

    tables["Control"][0]["SIMPE"] = "300000"
    with pytest.raises(ModelError, match="200000.*采购订单"):
        compile_model(tables)


@pytest.mark.parametrize("row,message", [
    ({"IID": "POWER", "LIMIT_H": "", "LIMIT_REPAIRS": ""}, "至少"),
    ({"IID": "POWER", "LIMIT_H": "0", "LIMIT_REPAIRS": ""}, "LIMIT_H"),
    ({"IID": "POWER", "LIMIT_H": "", "LIMIT_REPAIRS": "0"}, "LIMIT_REPAIRS"),
    ({"IID": "POWER", "LIMIT_H": "", "LIMIT_REPAIRS": "1.5"}, "有限的整数"),
    ({"IID": "ABSENT", "LIMIT_H": "1", "LIMIT_REPAIRS": ""}, "引用 ABSENT 不存在"),
])
def test_retirement_limits_are_optional_but_one_positive_limit_is_required(row, message):
    tables = one_leaf_new_service_tables()
    tables["SimLabItemRetirement"] = [row]
    with pytest.raises(ModelError, match=message):
        compile_model(tables)


def test_retirement_requires_replacement_steps_even_for_in_place_corrective_rule():
    tables = one_leaf_new_service_tables()
    tables["SimLabItemRetirement"] = [{"IID": "POWER", "LIMIT_H": "100"}]
    rule = next(r for r in tables["SimLabMaintenanceRule"] if r["KIND"] == "CORRECTIVE")
    rule["METHOD"] = "IN_PLACE"
    tables["SimLabMaintenanceStep"] = [
        r for r in tables["SimLabMaintenanceStep"] if r["RULEID"] != rule["RULEID"]
    ] + [
        {"RULEID": rule["RULEID"], "STEP": "IN_PLACE", "DURATION_H": "1", "TASK": "SERVICE"},
        {"RULEID": rule["RULEID"], "STEP": "TEST", "DURATION_H": "1", "TASK": "TEST"},
    ]
    with pytest.raises(ModelError, match="报废换件") as raised:
        compile_model(tables)
    assert "REMOVE" in str(raised.value) and "INSTALL" in str(raised.value)

    tables["SimLabMaintenanceStep"].extend([
        {"RULEID": rule["RULEID"], "STEP": "REMOVE", "DURATION_H": "1", "TASK": "SERVICE"},
        {"RULEID": rule["RULEID"], "STEP": "INSTALL", "DURATION_H": "1", "TASK": "SERVICE"},
    ])
    compile_model(tables)


def test_purchase_site_counts_as_reachable_calendar_stock_site():
    tables = one_leaf_new_service_tables()
    purchase(tables, STID="REGIONAL")
    with pytest.raises(ModelError, match="POWER@REGIONAL.*维修地点"):
        compile_model(tables)


def test_child_hour_retirement_requires_home_context_even_when_parent_is_replaced():
    from tests.test_m3_config import nested_pending_pm_tables
    t=nested_pending_pm_tables()
    t['SimLabItemPreventive']=[]
    t['SimLabMaintenanceRule']=[r for r in t['SimLabMaintenanceRule'] if r['KIND']=='CORRECTIVE']
    t['SimLabMaintenanceStep']=[r for r in t['SimLabMaintenanceStep'] if r['RULEID'] in {'PARENT-CM','CHILD-CM-D'}]
    t['SimLabItemRetirement']=[dict(IID='BOARD',LIMIT_H='5')]
    for step in ('REMOVE','INSTALL'):
        t['SimLabMaintenanceStep'].append(dict(RULEID='CHILD-CM-D',STEP=step,DURATION_H='1',TASK='SERVICE'))
    with pytest.raises(ModelError,match='POWER/BOARD@BASE'):
        compile_model(t)


def test_unreachable_corrective_context_does_not_require_retirement_steps():
    t=one_leaf_new_service_tables()
    t['SimLabItemRetirement']=[dict(IID='POWER',LIMIT_H='100')]
    t['ResourceAllocation'].append(dict(POINT='BASELINE',RID='TECH',STID='REGIONAL',RQTY='1'))
    t['SimLabMaintenanceRule'].append(dict(RULEID='UNUSED',MID='VEHICLE',IID='POWER',STID='REGIONAL',KIND='CORRECTIVE',METHOD='IN_PLACE'))
    for step in ('IN_PLACE','TEST'):
        t['SimLabMaintenanceStep'].append(dict(RULEID='UNUSED',STEP=step,DURATION_H='1',TASK='SERVICE'))
    compile_model(t)
