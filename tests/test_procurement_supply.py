import pytest
import simpy
from simlab.aging_components import AgingComponents
from simlab.supply import SupplyNetwork


def policy(station='c', target=5, lead=4, first=None):
    row=dict(POINT='P', STID=station, IID='X', TRIGGER='THRESHOLD', TARGET_QTY=str(target), REORDER_QTY='0', LEAD_H=str(lead))
    if first is not None:
        row.update(TRIGGER='PERIODIC', FIRST_H=str(first), INTERVAL_H='3', REORDER_QTY='')
    return row


def setup(purchase, routes=(), transfers=(), stock=None, definitions=None):
    env=simpy.Environment()
    parts=AgingComponents(definitions or {}, {}, env)
    cfg=dict(horizon=30, stock=stock or {}, m3={'tables':dict(SimLabPurchasePolicy=purchase, SimLabSupplyRoute=list(routes), SimLabSupplyPolicy=list(transfers))})
    return env, parts, SupplyNetwork(env,parts,cfg)


def route(hours):
    return dict(ROUTEID='a-c', IID='X', FROM_STID='a', TO_STID='c', TRANSIT_H=str(hours))


def test_purchase_only_counts_outstanding_once_and_arrives_whole():
    env,parts,s=setup([policy()])
    s.start(); env.run(until=3)
    assert len(s.snapshot().get('purchases',[]))==1
    assert len(parts.records)==0
    assert s.snapshot()['stocks'][0]['unreceived']==5
    env.run(until=5)
    assert len(s.available('c','X'))==5
    assert len(s.snapshot()['purchases'])==1
    s.validate()


@pytest.mark.parametrize('transit,expected_transfer,expected_purchase',[(1,2,3),(6,0,5),(4,2,3)])
def test_fastest_candidate_and_partial_split(transit,expected_transfer,expected_purchase):
    env,parts,s=setup([policy()], [route(transit)], [policy()], {('a','X'):2})
    s.start(); env.run(until=.1)
    assert sum(r['quantity'] for r in s.snapshot()['shipments'])==expected_transfer
    assert sum(r['quantity'] for r in s.snapshot().get('purchases',[]))==expected_purchase
    env.run(until=8)
    assert len(s.available('c','X'))==5
    s.validate()


def test_periodic_purchase_does_not_fire_before_own_tick_or_duplicate_pending():
    env,parts,s=setup([policy(first=2,lead=10)])
    s.start(); env.run(until=1)
    assert not s.orders
    env.run(until=11)
    assert len(s.snapshot().get('purchases',[]))==1
    env.run(until=13)
    assert len(s.available('c','X'))==5
    s.validate()


def test_ineligible_periodic_transfer_is_not_used_by_purchase():
    env,parts,s=setup([policy()], [route(1)], [policy(first=10)], {('a','X'):5})
    s.start(); env.run(until=5)
    assert not s.shipments
    assert len(s.available('c','X'))==5
    assert len(s.available('a','X'))==5
    s.validate()


def test_zero_lead_purchase_creates_fresh_parent_and_children():
    defs={'X':[dict(iid='Y',quantity=2)]}
    env,parts,s=setup([policy(target=1,lead=0)], definitions=defs)
    s.start(); env.run(until=.1)
    assert len(parts.records)==3
    assert all(r['age']==r['lifetime_hours']==0 for r in parts.records.values())
    assert len(s.snapshot()['purchases'][0]['parts'])==1
    s.validate()


def test_purchase_fills_local_demand_and_keeps_target_buffer():
    env,parts,s=setup([policy(target=1)])
    take=s.request_part('c','X'); s.start(); env.run(until=5)
    assert take.triggered
    assert len(s.available('c','X'))==1
    assert sum(r['quantity'] for r in s.snapshot()['purchases'])==2
    s.validate()


def test_later_purchase_tick_can_fulfil_unallocated_transfer_without_duplicate_order():
    env,parts,s=setup([policy(first=5,lead=2)], [route(1)], [policy()])
    s.start(); env.run(until=1)
    assert len(s.orders)==1 and s.orders[0].unallocated==5
    env.run(until=8)
    assert len(s.available('c','X'))==5
    assert len(s.orders)==1
    assert s.snapshot()['purchases'][0]['created']==5
    s.validate()


def test_upstream_procurement_supplies_existing_downstream_request():
    env,parts,s=setup([policy(station='a',target=1,lead=2)], [route(1)], [policy(target=2)])
    s.start(); env.run(until=4)
    assert len(s.available('c','X'))==2
    assert len(s.available('a','X'))==1
    assert sum(r['quantity'] for r in s.snapshot()['purchases'])==3
    s.validate()


def test_differing_targets_do_not_order_high_target_through_ineligible_mode():
    env,parts,s=setup([policy(target=2)], [route(1)], [policy(target=5)], {('a','X'):1})
    s.start(); env.run(until=5)
    assert len(s.available('c','X'))==2
    assert s.orders[0].unallocated==3
    assert sum(r['quantity'] for r in s.snapshot()['purchases'])==1
    s.validate()


def test_purchase_scale_guard_stops_before_allocating_large_tree():
    env,parts,s=setup([policy(target=3,lead=0)], definitions={'X':[dict(iid='Y',quantity=2)]})
    s.max_physical=8
    s.start()
    with pytest.raises(RuntimeError, match='规模'):
        env.run(until=1)
    assert not parts.records


def test_purchase_threshold_uses_shared_ip_including_unallocated_transfer():
    p=policy(target=1)
    transfer=policy(target=5); transfer['REORDER_QTY']='1'
    env,parts,s=setup([p], [route(1)], [transfer], {('c','X'):1})
    s.start(); env.run(until=1)
    s.request_part('c','X'); env.run(until=2)
    assert s.orders[0].unallocated==4
    assert not s.purchases  # Shared IP is 4, above purchase threshold 0.


def test_later_periodic_tick_can_convert_remainder_of_mixed_order():
    env,parts,s=setup([policy(target=1,first=0,lead=0)], [route(1)], [policy(target=5)])
    s.start(); env.run(until=1)
    s.request_part('c','X'); env.run(until=4)
    assert len(s.available('c','X'))==1
    assert [p['created'] for p in s.purchases]==[0,3]
    assert len(s.orders)==1 and s.orders[0].unallocated==3
    s.validate()


def test_same_tick_zero_lead_mixed_purchase_rechecks_after_immediate_consumption():
    env,parts,s=setup([policy(target=1,first=0,lead=0)], [route(1)], [policy(target=5)])
    consumed=[]
    def on_stock(station,part):
        if not consumed:
            consumed.append(s.request_part(station,'X'))
    s.on_stock=on_stock
    s.start(); env.run(until=1)
    assert consumed[0].triggered and len(s.available('c','X'))==1
    assert [r['created'] for r in s.purchases]==[0,0]
    s.validate()
