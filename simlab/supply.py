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
    max_physical = 200000
    detail_limit = 10000

    def __init__(self, env, components, config, stores=None, log=None):
        self.env, self.components, self.config = env, components, config
        self.stores = {} if stores is None else stores
        self.log = log
        self.horizon = float(config.get('horizon', math.inf))
        self.orders, self.shipments, self.demands = [], [], []
        self.purchases = []
        self.created_ids = set()
        self.created_counts = Counter()
        self._order_options = {}
        self._purchase_due_at = {}
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
        self.purchase_policies = {}
        policy_rows = [(False, row) for row in tables.get('SimLabSupplyPolicy', [])]
        policy_rows += [(True, row) for row in tables.get('SimLabPurchasePolicy', [])]
        for purchase, raw in policy_rows:
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
            if purchase:
                row['LEAD_H'] = float(row['LEAD_H'])
                if not math.isfinite(row['LEAD_H']) or row['LEAD_H'] < 0:
                    raise ValueError('采购交期必须为有限非负数')
                self.purchase_policies[key] = row
            else:
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
        for key, policy in self.purchase_policies.items():
            if policy['TRIGGER'] == 'PERIODIC':
                self.env.process(self._periodic(key, policy, purchase=True))
        self.allocate()

    def _periodic(self, key, policy, purchase=False):
        when = policy['FIRST_H']
        while when < self.horizon:
            yield self.env.timeout(max(0, when - self.env.now))
            if purchase:
                self._purchase_due_at[key] = self.env.now
                self.allocate()
            else:
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

    def order(self, station, iid, quantity, reason='manual', options=None):
        """Commit an explicit replenishment once; policy calls use the same path."""
        if not math.isfinite(quantity) or int(quantity) != quantity or quantity < 0:
            raise ValueError('供应订单数量必须为有限非负整数')
        if not quantity:
            return None
        if len(self.orders) >= self.max_orders:
            raise RuntimeError('供应订单超过每轮规模上限，停止计算')
        routes = self.routes.get((station, iid), [])
        if not routes and not (options and options.get('purchase')):
            raise ValueError(f'站点 {station} 部件 {iid} 没有入向供应路线')
        row = Order(f'O{len(self.orders)+1}', self._next_sequence(), station, iid,
                    self.env.now, int(quantity), routes[0]['FROM_STID'] if routes else '', reason)
        if options is not None:
            self._order_options[row.id] = options
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
            if row.sponsor:
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
                    keys = list(dict.fromkeys([*self.policies, *self.purchase_policies]))
                    keys.sort(key=lambda key: first_demand.get(key, math.inf))
                    for key in keys:
                        ip = len(self.available(*key)) + unreceived[key] - unmet[key]
                        active = {}
                        for mode, policies, ticks in (
                            ('transfer', self.policies, self._periodic_due_at),
                            ('purchase', self.purchase_policies, self._purchase_due_at)):
                            policy = policies.get(key)
                            if policy and self._triggered(policy, key, ip, ticks) and policy['TARGET_QTY'] > ip:
                                active[mode] = policy
                        if active:
                            target = max(p['TARGET_QTY'] for p in active.values())
                            options = None if key not in self.purchase_policies else dict(
                                transfer=active.get('transfer'), purchase=active.get('purchase'),
                                base_ip=ip)
                            self.order(*key, target - ip, reason='/'.join(dict.fromkeys(
                                p['TRIGGER'] for p in active.values())), options=options)
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
                options = self._order_options.get(row.id)
                candidates = []
                dynamic_purchase = None
                policy = self.purchase_policies.get((row.station, row.iid))
                initial_purchase = (options and options.get('purchase') and row.created == self.env.now
                                    and row.quantity == row.unallocated)
                if policy and not initial_purchase:
                    # A committed transfer may still have no physical allocation.
                    # Its unallocated promise must not suppress a later purchase
                    # tick; convert that promise, rather than creating a duplicate.
                    unreceived, unmet = self._balances()
                    key = row.station, row.iid
                    ip = len(self.available(*key)) + unreceived[key] - unmet[key]
                    if self._triggered(policy, key, ip, self._purchase_due_at):
                        dynamic_purchase = max(0, policy['TARGET_QTY'] - ip + row.unallocated)
                if options is None or options.get('transfer'):
                    candidates.extend((r['TRANSIT_H'], 0, r['ROUTEID'], r)
                                      for r in self.routes[(row.station, row.iid)])
                if initial_purchase:
                    candidates.append((options['purchase']['LEAD_H'], 1, '', options['purchase']))
                elif dynamic_purchase:
                    candidates.append((policy['LEAD_H'], 1, '', policy))
                allocated_before = row.quantity - row.unallocated
                for _, mode, _, route in sorted(candidates):
                    allowed = row.unallocated
                    if mode and dynamic_purchase is not None:
                        allowed = min(allowed, max(0, dynamic_purchase
                                                  - (row.quantity - row.unallocated - allocated_before)))
                    elif options:
                        rule = options['purchase' if mode else 'transfer']
                        # Faster candidates have already covered part of this target.
                        allowed = min(allowed, max(0, rule['TARGET_QTY'] - options['base_ip']
                                                  - (row.quantity - row.unallocated)))
                    if mode:
                        if allowed:
                            self._purchase(row, route, allowed)
                        continue
                    source = route['FROM_STID']
                    parts = self.available(source, row.iid)[:allowed]
                    if parts:
                        self._dispatch(row, route, parts)
                    if not row.unallocated:
                        break
        self._pending_demands = [r for r in self._pending_demands if not r.fulfilled]
        self._pending_orders = [r for r in self._pending_orders if r.unallocated or r.in_transit]

    def _triggered(self, policy, key, ip, ticks):
        return (ip <= policy['REORDER_QTY'] if policy['TRIGGER'] == 'THRESHOLD'
                else ticks.get(key) == self.env.now)

    def _purchase(self, order, policy, quantity):
        if len(self.purchases) >= self.max_shipments:
            raise RuntimeError('采购记录超过每轮规模上限，停止计算')
        order.dispatch(quantity)
        row = dict(id=f'P{len(self.purchases)+1}', order=order.id, station=order.station,
                   iid=order.iid, quantity=quantity, created=self.env.now,
                   arrival=self.env.now + policy['LEAD_H'], received=False, parts=[])
        self.purchases.append(row)
        self.env.process(self._purchase_arrive(row))
        if self.log:
            self.log(order.station, '采购下单', order.iid)

    def _purchase_arrive(self, row):
        yield self.env.timeout(row['arrival'] - self.env.now)
        def physical_size(iid):
            return 1 + sum(spec['quantity'] * physical_size(spec['iid'])
                           for spec in self.components.definitions.get(iid, []))
        if len(self.components.records) + row['quantity'] * physical_size(row['iid']) > self.max_physical:
            raise RuntimeError('采购后实物规模超过每轮200000件上限，停止计算')
        self._order_ids[row['order']].receive(row['quantity'])
        row['received'] = True
        before = set(self.components.records)
        for _ in range(row['quantity']):
            part = self.components.create(row['iid'], 'held', row['station'])
            row['parts'].append(part)
            self.return_part(row['station'], part)
        new = set(self.components.records) - before
        self.created_ids.update(new)
        self.created_counts.update(self.components.records[p]['iid'] for p in new)
        if self.log:
            self.log(row['station'], '采购到货', row['iid'])

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
                           'target': max((p[key]['TARGET_QTY'] for p in (self.policies, self.purchase_policies)
                                          if key in p), default=None)})
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
        extra = {}
        if self.purchase_policies:
            extra['purchases'] = [dict(r, parts=list(r['parts'])) for r in self.purchases[:self.detail_limit]]
            detail_counts['purchases'] = dict(total=len(self.purchases), retained=len(extra['purchases']),
                                              truncated=len(self.purchases)>self.detail_limit)
            totals.update(purchase_count=len(self.purchases), purchased=sum(r['quantity'] for r in self.purchases),
                          purchase_received=sum(r['quantity'] for r in self.purchases if r['received']))
        return {**extra, 'orders': orders, 'shipments': shipments, 'stocks': stocks[:self.detail_limit],
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
            assert self._initial_counts + self.created_counts == Counter(r['iid'] for r in self.components.records.values()), '实物数量不守恒'
            assert self._initial_ids | self.created_ids == set(self.components.records) == set(self.components.locations), '实物身份不守恒'
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
        for purchase in self.purchases:
            assert purchase['quantity'] > 0
            (received if purchase['received'] else transit)[purchase['order']] += purchase['quantity']
            assert len(purchase['parts']) == (purchase['quantity'] if purchase['received'] else 0)
        for order in self.orders:
            order.validate()
            assert order.in_transit == transit[order.id] and order.received == received[order.id]
            routes = self.routes[(order.station, order.iid)]
            assert order.sponsor == (routes[0]['FROM_STID'] if routes else '')
        return True
