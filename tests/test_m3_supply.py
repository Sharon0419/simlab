"""Analytic supply acceptance: real identities, no stochastic substitutes."""
import importlib
import json

import pytest
import simpy

from simlab.components import Components


def route(source, dest, hours, name=None):
    return {'ROUTEID': name or source + dest, 'IID': 'X', 'FROM_STID': source,
            'TO_STID': dest, 'TRANSIT_H': hours}


def policy(station, target=0, reorder=0, first=None, interval=6):
    return {'POINT': 'P', 'STID': station, 'IID': 'X', 'TARGET_QTY': target,
            'TRIGGER': 'THRESHOLD' if first is None else 'PERIODIC',
            'REORDER_QTY': reorder, 'FIRST_H': first or 0, 'INTERVAL_H': interval}


def network(routes, policies=(), stock=None, horizon=30, definitions=None):
    # Missing implementation is an explicit feature assertion, not collection error.
    spec = importlib.util.find_spec('simlab.supply')
    assert spec is not None, 'M3 SupplyNetwork has not been implemented'
    cls = importlib.import_module('simlab.supply').SupplyNetwork
    env = simpy.Environment()
    parts = Components(definitions or {})
    config = {'horizon': horizon, 'stock': {(s, 'X'): q for s, q in (stock or {}).items()},
              'm3': {'tables': {'SimLabSupplyRoute': routes, 'SimLabSupplyPolicy': list(policies)}}}
    supply = cls(env, parts, config)
    return env, parts, supply


def demand(env, supply, station, count=1):
    receipts = []
    def take():
        part = yield supply.request_part(station, 'X')
        receipts.append((env.now, part))
    for _ in range(count):
        env.process(take())
    return receipts


def return_at(env, parts, supply, station, time, part=None):
    part = part or parts.create('X', 'repair', station)
    def finish():
        yield env.timeout(time)
        supply.return_part(station, part)
    env.process(finish())
    return part


def test_s1_multilevel_stock_moves_through_intermediate_site():
    env, parts, s = network([route('a', 'b', 3), route('b', 'c', 2)],
                            [policy('b', 1), policy('c', 1)], {'a': 1})
    got = demand(env, s, 'c')
    s.start(); env.run(until=6)
    assert [t for t, _ in got] == [5]
    assert [(r['source'], r['destination']) for r in s.snapshot()['shipments']] == [('a', 'b'), ('b', 'c')]
    assert parts.locations[got[0][1]] == 'held'
    s.validate()


def test_s2_direct_available_candidate_bypasses_empty_shorter_source():
    env, _, s = network([route('a', 'b', 3), route('b', 'c', 2), route('a', 'c', 4)],
                         [policy('c', 1)], {'a': 1})
    got = demand(env, s, 'c'); s.start(); env.run(until=5)
    assert [t for t, _ in got] == [4]
    assert [(r['source'], r['destination']) for r in s.snapshot()['shipments']] == [('a', 'c')]
    s.validate()


def test_s3_splits_six_without_duplicate_requests():
    env, _, s = network([route('b', 'c', 2), route('a', 'c', 5)],
                         [policy('c', 6)], {'b': 2, 'a': 10})
    s.start(); env.run(until=6)
    rows = s.snapshot()['shipments']
    assert [(r['arrival'], r['quantity']) for r in rows] == [(2, 2), (5, 4)]
    assert s.snapshot()['totals']['requested'] == 6
    assert len(s.available('c', 'X')) == 6
    s.validate()


def test_s4_return_to_alternate_supplier_wakes_existing_order():
    env, parts, s = network([route('b', 'c', 2), route('a', 'c', 5)], [policy('c', 1)])
    token = return_at(env, parts, s, 'a', 3)
    s.start(); env.run(until=1)
    assert next(r for r in s.snapshot()['stocks'] if r['station'] == 'b')['unmet'] == 1
    env.run(until=9)
    assert s.available('c', 'X') == [token]
    assert s.snapshot()['shipments'][0]['arrival'] == 8
    assert next(r for r in s.snapshot()['stocks'] if r['station'] == 'b')['unmet'] == 0
    s.validate()


def test_s5_inventory_position_counts_unreceived_once():
    env, _, s = network([route('a', 'c', 10)], [policy('c', 8, 4)], {'c': 2})
    # Three already committed units plus one unfulfilled local requirement.
    s.order('c', 'X', 3)
    s.request_part('c', 'X')
    s.start(); env.run(until=.1)
    rows = s.snapshot()['orders']
    assert [r['quantity'] for r in rows] == [3, 4]
    stock = next(r for r in s.snapshot()['stocks'] if r['station'] == 'c')
    assert (stock['available'], stock['unreceived'], stock['inventory_position']) == (1, 7, 8)
    s.validate()


def test_s6_pending_periodic_order_fulfils_between_ticks():
    env, parts, s = network([route('a', 'c', 0)], [policy('c', 1, first=2)])
    return_at(env, parts, s, 'a', 3)
    s.start(); env.run(until=4)
    assert s.snapshot()['shipments'][0]['departure'] == 3
    assert s.snapshot()['orders'][0]['created'] == 2
    taken = s.request_part('c', 'X')
    env.run(until=9)
    assert taken.triggered
    assert [(r['created'], r['quantity']) for r in s.snapshot()['orders']] == [(2, 1), (8, 1)]
    s.validate()


def test_s7_same_time_receipt_precedes_periodic_target_check():
    env, parts, s = network([route('a', 'c', 2)], [policy('c', 1, first=2)])
    # Scheduled tick was created first; receipt still wins phase ordering.
    token = parts.create('X', 'repair', 'c')
    s.start()
    return_at(env, parts, s, 'c', 2, token)
    env.run(until=3)
    assert s.snapshot()['totals']['order_count'] == 0
    s.validate()


def test_s8_fifo_competition_is_replayable():
    def run():
        env, parts, s = network([route('a', 'c', 1), route('a', 'd', 1)],
                                [policy('c', 1), policy('d', 1)])
        return_at(env, parts, s, 'a', 1)
        s.start(); env.run(until=.1)
        env.run(until=3)
        assert len(s.available('c', 'X')) == 1
        assert len(s.available('d', 'X')) == 0
        s.validate()
        return s.snapshot()
    assert run() == run()


def test_s9_one_unlimited_shipment_for_six_parts():
    env, _, s = network([route('a', 'c', 2)], [policy('c', 6)], {'a': 6})
    s.start(); env.run(until=3)
    rows = s.snapshot()['shipments']
    assert len(rows) == 1 and rows[0]['quantity'] == 6
    assert len(set(rows[0]['parts'])) == 6
    assert rows[0]['arrival'] == 2
    s.validate()


def test_s10_sponsored_upstream_commitment_survives_candidate_switch():
    env, parts, s = network([route('a', 'b', 4), route('b', 'c', 1), route('a', 'c', 5)],
                            [policy('b', 1), policy('c', 1)])
    return_at(env, parts, s, 'a', 3)
    return_at(env, parts, s, 'a', 4)
    s.order('c', 'X', 1)
    s.start(); env.run(until=10)
    # c's earlier order takes the first return directly; b's promise remains.
    assert len(s.available('c', 'X')) == 1
    assert len(s.available('b', 'X')) >= 1
    corders = [r for r in s.snapshot()['orders'] if r['station'] == 'c']
    assert len(corders) == 1 and corders[0]['received'] == 1
    assert [(r['source'], r['departure']) for r in s.snapshot()['shipments'] if r['destination'] == 'c'] == [('a', 3)]
    assert all(r['quantity'] == r['unallocated'] + r['in_transit'] + r['received'] for r in s.snapshot()['orders'])
    s.validate()


def test_zero_time_chain_has_traceable_shipments_and_converges():
    env, _, s = network([route('a', 'b', 0), route('b', 'c', 0)],
                         [policy('b', 1), policy('c', 1)], {'a': 1})
    s.start(); env.run(until=.1)
    assert len(s.available('c', 'X')) == 1
    assert all(r['departure'] == r['arrival'] == 0 and r['received'] for r in s.snapshot()['shipments'])
    s.validate()


def test_horizon_retains_unfinished_transport_and_excludes_final_tick():
    env, _, s = network([route('a', 'c', 5)], [policy('c', 1, first=0, interval=2)], {'a': 1}, horizon=2)
    s.start(); env.run(until=3)
    assert len(s.snapshot()['orders']) == 1
    assert s.snapshot()['orders'][0]['in_transit'] == 1
    assert not s.snapshot()['shipments'][0]['received']
    json.dumps(s.snapshot())
    s.validate()


def test_supplied_stores_are_not_reseeded_and_assembly_remains_attached():
    env, parts, original = network([], stock={'a': 1}, definitions={'X': [{'iid': 'Y', 'quantity': 2}]})
    cls = type(original)
    s = cls(env, parts, original.config, stores=original.stores)
    assert len(parts.records) == 3
    event = s.request_part('a', 'X'); s.start(); env.run(until=.1)
    assert event.triggered
    assert len(parts.records[event.value]['children']) == 2
    s.validate()


def test_receipt_hook_can_quarantine_before_local_demand_gets_part():
    env, parts, s = network([route('a', 'c', 1)], [policy('c', 1)], {'a': 1})
    def quarantine(station, part):
        if station == 'c':
            s.withdraw(part)
            parts.move(part, 'repair', station)
    s.on_stock = quarantine
    event = s.request_part('c', 'X'); s.start(); env.run(until=2)
    assert not event.triggered
    assert s.snapshot()['orders'][0]['received'] == 1
    assert s.available('c', 'X') == []
    s.validate()


def test_order_and_shipment_caps_fail_instead_of_returning_partial_success():
    env, _, s = network([route('a', 'c', 1)], stock={'a': 2})
    s.max_orders = 1
    s.order('c', 'X', 1)
    with pytest.raises(RuntimeError, match='订单'):
        s.order('c', 'X', 1)
    s.max_shipments = 0
    s.start()
    with pytest.raises(RuntimeError, match='运输'):
        env.run(until=2)


def test_ineligible_stock_is_never_dispatched():
    env, parts, s = network([route('a', 'c', 1)], [policy('c', 1)], {'a': 1})
    token = s.available('a', 'X')[0]
    parts.records[token]['preventive_due'] = True
    s.start(); env.run(until=2)
    assert not s.snapshot()['shipments']
    assert s.available('a', 'X') == []


def test_same_length_routes_use_id_tie_break():
    env, _, s = network([route('b', 'c', 1, 'Z'), route('a', 'c', 1, 'A')],
                         [policy('c', 1)], {'a': 1, 'b': 1})
    s.start(); env.run(until=2)
    assert s.snapshot()['shipments'][0]['route'] == 'A'
    s.validate()


def test_existing_local_demand_order_wins_over_policy_table_order():
    env, _, s = network([route('a', 'c', 1), route('a', 'd', 1)],
                         [policy('c', 1), policy('d', 1)], {'a': 1})
    first = s.request_part('d', 'X')
    second = s.request_part('c', 'X')
    s.start(); env.run(until=2)
    assert first.triggered and not second.triggered
    s.validate()


def test_available_alternate_prevents_unneeded_sponsored_upstream_order():
    env, _, s = network([route('b', 'c', 1), route('a', 'c', 2), route('a', 'b', 3)],
                         [policy('c', 1), policy('b', 1)], {'a': 3})
    # a can satisfy c directly; b's target1 requires exactly one replenishment.
    s.start(); env.run(until=4)
    assert [r['quantity'] for r in s.snapshot()['orders'] if r['station'] == 'b'] == [1]
    s.validate()


def test_replaced_identity_with_unchanged_count_is_not_conservation():
    env, parts, s = network([], stock={'a': 1})
    s.start(); env.run(until=.1)
    token = s.available('a', 'X')[0]
    s.withdraw(token)
    del parts.records[token]
    del parts.locations[token]
    replacement = parts.create('X', 'held', 'a')
    # Components' count-based ID would recycle the deleted ID; use a distinct ID.
    parts.records['X#foreign'] = parts.records.pop(replacement)
    parts.records['X#foreign']['id'] = 'X#foreign'
    parts.locations['X#foreign'] = parts.locations.pop(replacement)
    with pytest.raises(AssertionError, match='实物'):
        s.validate()


def test_truncated_details_do_not_truncate_totals_or_validation():
    env, _, s = network([route('a', 'c', 1)], stock={'a': 3})
    s.detail_limit = 1
    for _ in range(3):
        s.order('c', 'X', 1)
    s.start(); env.run(until=2)
    result = s.snapshot()
    assert len(result['orders']) == len(result['shipments']) == 1
    assert result['totals']['received'] == 3
    assert result['detail_counts']['orders'] == {'total': 3, 'retained': 1, 'truncated': True}
    s.validate()


@pytest.mark.parametrize('stations', [('b', 'c'), ('c', 'b')])
@pytest.mark.parametrize('transit', [0, 1])
def test_same_tick_periodic_sponsorship_reaches_target_in_both_row_orders(stations, transit):
    env, _, s = network([route('a', 'b', transit), route('b', 'c', transit)],
                         [policy(st, 1, first=0, interval=10) for st in stations], {'a': 5})
    s.start(); env.run(until=3)
    result = s.snapshot()
    assert {r['station']: r['inventory_position'] for r in result['stocks']} == {'a': 3, 'b': 1, 'c': 1}
    b_orders = [r for r in result['orders'] if r['station'] == 'b']
    assert sum(r['quantity'] for r in b_orders) == 2
    # D9: an earlier commitment remains intact; stabilization may add an order.
    assert [r['quantity'] for r in b_orders] == ([1, 1] if stations[0] == 'b' else [2])
    assert sum(r['quantity'] for r in result['orders'] if r['station'] == 'c') == 1
    taken = s.request_part('b', 'X')
    env.run(until=4)
    assert taken.triggered
    assert len(s.available('b', 'X')) == 0
    assert s.snapshot()['totals']['order_count'] == result['totals']['order_count']
    s.validate()
