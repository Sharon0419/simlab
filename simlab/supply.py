"""Explicit M3 physical supply network, with one inventory writer.

Regular SimPy callbacks settle physical receipts and register requests. A later
priority phase services them in stable FIFO order and checks replenishment. Zero
hour shipments remain ordinary, separately recorded receipt events.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
import math

import simpy

from .supply_ledger import Demand, Order, Shipment


class SupplyNetwork:
    max_orders = 200000
    max_shipments = 1000000
    detail_limit = 10000

    def __init__(self, env, components, config, stores=None, log=None):
        self.env, self.components, self.config = env, components, config
        self.stores = {} if stores is None else stores
        self.log = log
        self.horizon = float(config.get('horizon', math.inf))
        self.orders, self.shipments, self.demands = [], [], []
        self._order_ids = {}
        self._pending_orders, self._pending_demands = [], []
        self._sequence = 0
        self._started = self._scheduled = self._running = False
        self._periodic_due_at = {}
        self._initial_counts = None
        self._initial_ids = None
        self.eligible = self._healthy
        self.on_stock = None
        self.routes = defaultdict(list)
        tables = config.get('m3', {}).get('tables', {})
        for raw in tables.get('SimLabSupplyRoute', []):
            row = dict(raw)
            row['TRANSIT_H'] = float(row['TRANSIT_H'])
            if not math.isfinite(row['TRANSIT_H']) or row['TRANSIT_H'] < 0:
                raise ValueError('供应运输时长必须为有限非负数')
            self.routes[(row['TO_STID'], row['IID'])].append(row)
            self._store(row['FROM_STID'], row['IID'])
            self._store(row['TO_STID'], row['IID'])
        for rows in self.routes.values():
            rows.sort(key=lambda r: (r['TRANSIT_H'], r['ROUTEID']))
        controls = tables.get('Control', [])
        point = controls[0].get('APID') if controls else None
        self.policies = {}
        for raw in tables.get('SimLabSupplyPolicy', []):
            if point is not None and raw.get('POINT') != point:
                continue
            key = raw['STID'], raw['IID']
            row = dict(raw)
            row['TARGET_QTY'] = int(float(row['TARGET_QTY']))
            row['REORDER_QTY'] = int(float(row.get('REORDER_QTY') or 0))
            if row['TRIGGER'] == 'PERIODIC':
                row['FIRST_H'] = float(row.get('FIRST_H') or 0)
                row['INTERVAL_H'] = float(row['INTERVAL_H'])
                if not math.isfinite(row['INTERVAL_H']) or row['INTERVAL_H'] <= 0:
                    raise ValueError('补货周期必须为有限正数')
            self.policies[key] = row
            self._store(*key)
        if stores is None:
            for (station, iid), quantity in config.get('stock', {}).items():
                stock = self._store(station, iid)
                for _ in range(quantity):
                    stock.items.append(components.create(iid, 'stock', station))

    def _store(self, station, iid):
        key = station, iid
        if key not in self.stores:
            self.stores[key] = simpy.Store(self.env)
        return self.stores[key]

    def _healthy(self, part):
        record = self.components.records[part]
        return (not record['broken'] and not record.get('preventive_due', False)
                and all(child is not None and self._healthy(child) for child in record['children']))

    def available(self, station, iid):
        return [p for p in self._store(station, iid).items if self.eligible(p)]

    def start(self):
        if self._started:
            return
        self._started = True
        self._initial_counts = Counter(r['iid'] for r in self.components.records.values())
        self._initial_ids = set(self.components.records)
        for key, policy in self.policies.items():
            if policy['TRIGGER'] == 'PERIODIC':
                self.env.process(self._periodic(key, policy))
        self.allocate()

    def _periodic(self, key, policy):
        when = policy['FIRST_H']
        while when < self.horizon:
            yield self.env.timeout(max(0, when - self.env.now))
            self.tick_policy(*key)
            when += policy['INTERVAL_H']

    def tick_policy(self, station=None, iid=None):
        if self.env.now >= self.horizon:
            return
        for key, row in self.policies.items():
            if (station is None or station == key[0]) and (iid is None or iid == key[1]):
                if row['TRIGGER'] == 'PERIODIC':
                    self._periodic_due_at[key] = self.env.now
        self.allocate()

    def _next_sequence(self):
        self._sequence += 1
        return self._sequence

    def request_part(self, station, iid, owner=''):
        event = self.env.event()
        row = Demand(f'D{len(self.demands)+1}', self._next_sequence(), station, iid,
                     self.env.now, str(owner), event)
        self.demands.append(row)
        self._pending_demands.append(row)
        self._store(station, iid)
        self.allocate()
        return event

    def order(self, station, iid, quantity, reason='manual'):
        """Commit an explicit replenishment once; policy calls use the same path."""
        if not math.isfinite(quantity) or int(quantity) != quantity or quantity < 0:
            raise ValueError('供应订单数量必须为有限非负整数')
        if not quantity:
            return None
        if len(self.orders) >= self.max_orders:
            raise RuntimeError('供应订单超过每轮规模上限，停止计算')
        routes = self.routes.get((station, iid), [])
        if not routes:
            raise ValueError(f'站点 {station} 部件 {iid} 没有入向供应路线')
        row = Order(f'O{len(self.orders)+1}', self._next_sequence(), station, iid,
                    self.env.now, int(quantity), routes[0]['FROM_STID'], reason)
        self.orders.append(row)
        self._order_ids[row.id] = row
        self._pending_orders.append(row)
        self.allocate()
        return row

    def return_part(self, station, part):
        record = self.components.records[part]
        assert record['parent'] is None, '附着部件不能独立返库'
        assert self.components.locations[part] != 'stock', '实物重复返库'
        assert not record['broken'], '故障件不能进入可用库存'
        self.components.move(part, 'stock', station)
        self._store(station, record['iid']).items.append(part)
        if self.on_stock:
            self.on_stock(station, part)
        self.allocate()

    def withdraw(self, part):
        record = self.components.records[part]
        if self.components.locations[part] != 'stock':
            return False
        self._store(record['site'], record['iid']).items.remove(part)
        self.components.move(part, 'held', record['site'])
        self.allocate()
        return True

    def _balances(self):
        unreceived, unmet = Counter(), Counter()
        for row in self._pending_orders:
            unreceived[(row.station, row.iid)] += row.unallocated + row.in_transit
            unmet[(row.sponsor, row.iid)] += row.unallocated
        for row in self._pending_demands:
            unmet[(row.station, row.iid)] += row.quantity - row.fulfilled
        return unreceived, unmet

    def allocate(self):
        if self._scheduled or self._running:
            return
        self._scheduled = True
        event = self.env.event()
        event._ok, event._value = True, None
        event.callbacks.append(self._settle)
        self.env.schedule(event, priority=2)

    def _settle(self, _event):
        self._scheduled = False
        self._running = True
        try:
            while True:
                self._fulfil()
                # Physical zero-time arrivals must settle before further target checks.
                unreceived, unmet = self._balances()
                created = False
                if self._started and self.env.now < self.horizon:
                    # A policy table's row order must not reverse existing demand FIFO.
                    first_demand = {}
                    for demand in self._pending_demands:
                        first_demand.setdefault((demand.station, demand.iid), demand.sequence)
                    policies = sorted(self.policies.items(),
                                      key=lambda pair: first_demand.get(pair[0], math.inf))
                    for key, policy in policies:
                        ip = len(self.available(*key)) + unreceived[key] - unmet[key]
                        trigger = (ip <= policy['REORDER_QTY'] if policy['TRIGGER'] == 'THRESHOLD'
                                   else self._periodic_due_at.get(key) == self.env.now)
                        if trigger and policy['TARGET_QTY'] > ip:
                            self.order(*key, policy['TARGET_QTY'] - ip, reason=policy['TRIGGER'])
                            created = True
                            # Sponsor only the portion that no available candidate can fill.
                            self._fulfil()
                            unreceived, unmet = self._balances()
                    # Keep a tick eligible through every same-time stabilization,
                    # including zero-time receipts that schedule another phase.
                    # Timestamp equality expires eligibility between periods;
                    # committed orders remain intact and prevent double ordering.
                if not created:
                    break
        finally:
            self._running = False

    def _fulfil(self):
        pending = sorted(self._pending_demands + self._pending_orders,
                         key=lambda r: (r.created, r.sequence))
        for row in pending:
            if isinstance(row, Demand):
                stock = self.available(row.station, row.iid)
                if stock:
                    part = stock[0]
                    self._store(row.station, row.iid).items.remove(part)
                    self.components.move(part, 'held', row.station)
                    row.fulfilled, row.completed = 1, self.env.now
                    row.event.succeed(part)
            elif row.unallocated:
                for route in self.routes[(row.station, row.iid)]:
                    source = route['FROM_STID']
                    parts = self.available(source, row.iid)[:row.unallocated]
                    if parts:
                        self._dispatch(row, route, parts)
                    if not row.unallocated:
                        break
        self._pending_demands = [r for r in self._pending_demands if not r.fulfilled]
        self._pending_orders = [r for r in self._pending_orders if r.unallocated or r.in_transit]

    def _dispatch(self, order, route, parts):
        if len(self.shipments) >= self.max_shipments:
            raise RuntimeError('供应运输记录超过每轮规模上限，停止计算')
        source = route['FROM_STID']
        # Removing U removes the one sponsor claim, even for an alternate source.
        order.dispatch(len(parts))
        for part in parts:
            self._store(source, order.iid).items.remove(part)
            self.components.move(part, 'transport', order.station)
        shipment = Shipment(f'S{len(self.shipments)+1}', order.id, route['ROUTEID'],
                            source, order.station, order.iid, list(parts), self.env.now,
                            self.env.now + route['TRANSIT_H'])
        self.shipments.append(shipment)
        self.env.process(self._arrive(shipment))
        if self.log:
            self.log(source, '供应发运', order.iid)

    def _arrive(self, shipment):
        yield self.env.timeout(shipment.arrival - self.env.now)
        self._order_ids[shipment.order].receive(shipment.quantity)
        shipment.received = True
        for part in shipment.parts:
            self.return_part(shipment.destination, part)
        if self.log:
            self.log(shipment.destination, '供应到货', shipment.iid)

    def snapshot(self):
        unreceived, unmet = self._balances()
        stocks = []
        for key in sorted(self.stores):
            available = len(self.available(*key))
            stocks.append({'station': key[0], 'iid': key[1], 'available': available,
                           'reserved': 0, 'unreceived': unreceived[key], 'unmet': unmet[key],
                           'inventory_position': available + unreceived[key] - unmet[key],
                           'target': self.policies.get(key, {}).get('TARGET_QTY')})
        orders = [asdict(r) for r in self.orders[:self.detail_limit]]
        shipments = [dict(asdict(r), quantity=r.quantity) for r in self.shipments[:self.detail_limit]]
        demands = [{k: v for k, v in vars(r).items() if k != 'event'}
                   for r in self.demands[:self.detail_limit]]
        totals = {'order_count': len(self.orders), 'shipment_count': len(self.shipments),
                  'demand_count': len(self.demands), 'requested': sum(r.quantity for r in self.orders),
                  'shipped': sum(r.quantity for r in self.shipments),
                  'received': sum(r.received for r in self.orders)}
        detail_counts = {name: {'total': total, 'retained': min(total, self.detail_limit),
                                'truncated': total > self.detail_limit}
                         for name, total in [('orders', len(self.orders)), ('shipments', len(self.shipments)),
                                             ('demands', len(self.demands)), ('stocks', len(stocks))]}
        return {'orders': orders, 'shipments': shipments, 'stocks': stocks[:self.detail_limit],
                'demands': demands, 'totals': totals, 'detail_counts': detail_counts,
                'truncated': any(r['truncated'] for r in detail_counts.values())}

    def validate(self):
        stocked = [p for store in self.stores.values() for p in store.items]
        installed = [p for p, location in self.components.locations.items() if location == 'installed']
        self.components.validate(installed, stocked)
        for (station, iid), stock in self.stores.items():
            for part in stock.items:
                record = self.components.records[part]
                assert record['site'] == station and record['iid'] == iid
                assert self.eligible(part), '待发库存含不可用实物'
        if self._initial_counts is not None:
            assert self._initial_counts == Counter(r['iid'] for r in self.components.records.values()), '实物数量不守恒'
            assert self._initial_ids == set(self.components.records) == set(self.components.locations), '实物身份不守恒'
        transit, received, inflight_parts = Counter(), Counter(), []
        for shipment in self.shipments:
            assert shipment.quantity > 0 and len(shipment.parts) == len(set(shipment.parts))
            if shipment.received:
                received[shipment.order] += shipment.quantity
            else:
                transit[shipment.order] += shipment.quantity
                inflight_parts.extend(shipment.parts)
                assert all(self.components.locations[p] == 'transport' for p in shipment.parts)
        assert len(inflight_parts) == len(set(inflight_parts)), '实物重复在途'
        assert not set(inflight_parts) & set(stocked)
        for order in self.orders:
            order.validate()
            assert order.in_transit == transit[order.id] and order.received == received[order.id]
            assert order.sponsor == self.routes[(order.station, order.iid)][0]['FROM_STID']
        return True
