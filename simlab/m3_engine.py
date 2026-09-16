"""Explicit M3 runtime. Legacy execution and its random streams are untouched."""
from collections import Counter
import math
import numpy as np
import simpy
from .aging import remaining_age, risk_increment
from .aging_components import AgingComponents
from .missions import MissionManager
from .flight import FlightManager
from .preventive import PreventiveClocks
from .service import ServiceCoordinator
from .supply import SupplyNetwork
from .redundancy import capable, asset_capable, fault_summary


class Exposure:
    """One event-driven clock for physical lifetime, hazard and preventive cycles."""
    def __init__(self, env, config, parts, assets, service, failure_rng, failed):
        self.env, self.config, self.parts, self.assets = env, config, parts, assets
        self.service, self.rng, self.failed = service, failure_rng, failed
        self.last = env.now
        self.event = env.event()
        self.settling = False
        self.clocks = PreventiveClocks(env, parts, config['m3']['tables'])
        service.clocks, service.runtime = self.clocks, self

    def changed(self):
        if not self.event.triggered:
            self.event.succeed()

    def entries(self):
        for asset in self.assets:
            active = asset['mission'] is not None if self.config['missions'] else asset['state'] == 'available'
            if not active:
                continue
            fleet = asset['_fleet']
            for slot in asset['slots']:
                if slot['token'] is None:
                    continue
                root = self.parts.records[slot['token']]
                if self.config.get('redundancy') and not capable(self.parts, root['id'], self.config['redundancy']):
                    continue
                specs = {p['iid']:p for p in self.parts.definitions.get(root['iid'], [])}
                for leaf in self.parts.leaves(root['id']):
                    if leaf['broken']:
                        continue
                    aging = self.parts.rules.get(leaf['iid'])
                    factor = slot['envf'] * (specs[leaf['iid']]['envf'] if specs else 1.)
                    if aging:
                        shape, scale, multiplier = aging['shape'], aging['scale'], aging['application']*factor
                    else:
                        shape, scale = 1., 1.
                        multiplier = specs[leaf['iid']]['rate']*slot['envf'] if specs else slot['rate']
                    yield asset, slot, leaf, fleet['util'], shape, scale, multiplier

    def integrate(self):
        elapsed = self.env.now-self.last
        if elapsed <= 0:
            return
        operating = {}
        for _, _, record, util, shape, scale, multiplier in self.entries():
            hours = elapsed*util
            operating[record['id']] = hours
            if record['budget'] is not None:
                record['budget'] = max(0., record['budget'] - risk_increment(record['age'], hours, shape, scale, multiplier))
            record['age'] += hours
            record['lifetime_hours'] += hours
        if self.service.retirement.enabled:
            for record, rate in self.lifetime_entries():
                if record['id'] not in operating:
                    record['lifetime_hours'] += elapsed*rate
        self.clocks.integrate(elapsed, operating)
        self.last = self.env.now

    def lifetime_entries(self):
        for asset in self.assets:
            active = asset['mission'] is not None if self.config['missions'] else asset['state'] == 'available'
            if active:
                for slot in asset['slots']:
                    if slot['token']:
                        if self.config.get('redundancy') and not capable(self.parts, slot['token'], self.config['redundancy']):
                            continue
                        for record in self.service.retirement.tree(slot['token']):
                            if not record.get('retired') and (not self.config.get('redundancy') or not record.get('own_broken')):
                                yield record, asset['_fleet']['util']

    def settle_faults(self):
        if self.settling:
            return
        self.integrate()
        self.settling = True
        try:
            if self.config.get('redundancy'):
                # Include exhausted budgets at time zero / a landing boundary,
                # before the dispatcher has made a new assignment.
                due = []
                for asset in self.assets:
                    for slot in asset['slots']:
                        token = slot['token']
                        if token and capable(self.parts, token, self.config['redundancy']):
                            due.extend((asset, slot, r['id']) for r in self.parts.leaves(token)
                                if not r['broken'] and r['budget'] is not None and r['budget'] <= 1e-12)
                with self.service.registration_batch():
                    for asset, slot, leaf in due:
                        self.failed(asset, slot, leaf)
        finally:
            self.settling = False

    def due(self):
        self.integrate()
        self.service.retirement.due()
        manager = self.service.manager
        if manager and getattr(manager, 'planned', None):
            manager.planned.register_due()
        due_parts = self.clocks.due()
        if due_parts:
            with self.service.registration_batch():
                for part in due_parts:
                    self.service.preventive(part)

    def run(self):
        while True:
            self.integrate()
            self.service.retirement.due()
            # A true fault at the same instant takes precedence over unstarted PM.
            for asset, slot, record, util, shape, scale, multiplier in list(self.entries()):
                if multiplier and record['budget'] is not None and record['budget'] <= 1e-12:
                    self.failed(asset, slot, record['id'])
            self.due()
            self.service.advance()
            delay = math.inf
            rates = {}
            for _, _, record, util, shape, scale, multiplier in self.entries():
                rates[record['id']] = util
                if multiplier and record['budget'] is None:
                    record['budget'] = float(self.rng.exponential(1.))
                if util and multiplier:
                    delay = min(delay, remaining_age(record['age'], shape, scale, record['budget'], multiplier)/util)
            for part in self.clocks.clocks:
                delay = min(delay, self.clocks.remaining(part, rates.get(part, 0.)))
            if self.service.retirement.enabled:
                for record, rate in self.lifetime_entries():
                    delay = min(delay, self.service.retirement.remaining(record, rate))
            event = self.event
            self.event = self.env.event()
            if event.triggered:
                yield self.env.timeout(0)
                continue
            if math.isfinite(delay):
                yield self.env.timeout(max(0., delay)) | self.event
            else:
                yield self.event


class M3Missions(MissionManager):
    runtime = service = None

    def integrate(self):
        if self.runtime:
            self.runtime.integrate()
        super().integrate()

    def rebalance(self):
        super().rebalance()
        if self.service and self.service.config.get('redundancy'):
            self.service.advance()
        if self.runtime:
            self.runtime.changed()


def run_one(config, replication=0, progress=None):
    from .engine import ResourcePool, STATES
    env = simpy.Environment()
    rngs = [np.random.default_rng(np.random.SeedSequence([replication, label, config['seed']])) for label in range(5)]
    parts = AgingComponents(config.get('children', {}), config.get('aging', {}), env)
    parts.redundancy = config.get('redundancy', {})
    assets, events, samples, failures = [], [], [], Counter()
    event_count = 0
    manager = runtime = None
    pool = ResourcePool(env, config['capacity'], config.get('schedules'))

    def log(asset, action, item=''):
        nonlocal event_count
        event_count += 1
        if config['log'] and replication == 0 and len(events)<5000:
            events.append(dict(time=round(env.now, 5), asset=asset, event=action, item=item))

    def state(asset, next_state):
        if runtime:
            runtime.integrate()
        asset['times'][asset['state']] += env.now-asset['last']
        asset.update(state=next_state, last=env.now)
        if manager:
            manager.rebalance()
        if runtime:
            runtime.changed()

    supply = SupplyNetwork(env, parts, config, log=log)
    for fleet in config['fleets']:
        for index in range(fleet['quantity']):
            slots = [dict(iid=p['iid'], rate=p['rate'], envf=p['envf'],
                          token=parts.create(p['iid'], 'installed', fleet['home']))
                     for p in fleet['parts'] for _ in range(p['quantity'])]
            assets.append(dict(id=f"{fleet['sid']}@{fleet['unit']}-{index+1:03d}", slots=slots,
                state='available', last=0., times=Counter(), sid=fleet['sid'], unit=fleet['unit'],
                home=fleet['home'], mission=None, assignment_event=env.event(), _fleet=fleet))
    service = ServiceCoordinator(env, config, parts, supply, pool, rngs[3], rngs[4], state, log)
    service.corrective_rng, service.replace_rng = rngs[1], rngs[2]
    service.assets = assets

    def failed(asset, slot, leaf):
        parts.fail(slot['token'], leaf)
        failures[parts.records[leaf]['iid']] += 1
        log(asset['id'], '发生故障', parts.records[leaf]['iid'])
        service.corrective(asset, slot)
        if config.get('redundancy'):
            log(asset['id'], '冗余组状态', fault_summary(parts, asset, config['redundancy']))
        lost = not config.get('redundancy') or not asset_capable(parts, asset, config['redundancy'])
        if isinstance(manager, FlightManager) and asset['mission'] is not None and lost:
            state(asset, 'returning_failed')
        elif config.get('redundancy') and asset['mission'] is not None and lost:
            state(asset, 'waiting_resource')
            service.advance()

    runtime = Exposure(env, config, parts, assets, service, rngs[0], failed)
    if config['missions']:
        if 'flight_prep_hours' in config['missions'][0]:
            def planned_state(asset, next_state):
                runtime.integrate()
                asset['times'][asset['state']] += env.now-asset['last']
                asset.update(state=next_state, last=env.now)
                runtime.changed()
            manager = FlightManager(env, config['missions'], assets, log, resource_pool=pool,
                                    planned_rules=config.get('planned', []), set_state=planned_state)
            manager.m3_service = service
        else:
            manager = M3Missions(env, config['missions'], assets, log)
            manager.runtime, manager.service = runtime, service
        service.manager = manager
        if config.get('redundancy'):
            manager.settle_faults = runtime.settle_faults
    initial = len(parts.records)
    initial_by_item = dict(Counter(r['iid'] for r in parts.records.values()))
    supply.start()
    env.process(runtime.run())

    def sample():
        row = dict(time=env.now, available=sum(a['state']=='available' for a in assets)/len(assets))
        if manager:
            row.update(manager.sample())
        return row

    def observe():
        while True:
            yield env.timeout(0)
            samples.append(sample())
            if progress:
                progress(min(1., env.now/config['horizon']))
            yield env.timeout(config['interval'])
    env.process(observe())
    env.run(until=config['horizon'])
    runtime.integrate()
    if manager:
        manager._dispatching = True
        manager.rebalance()
    samples.append(sample())
    totals = Counter()
    for asset in assets:
        asset['times'][asset['state']] += env.now-asset['last']
        totals.update(asset['times'])
    denominator = config['horizon']*len(assets)
    assert abs(sum(totals.values())-denominator)<max(1e-6, denominator*1e-9)
    supply.validate()
    installed = [s['token'] for a in assets for s in a['slots'] if s['token'] is not None]
    stocked = [p for store in supply.stores.values() for p in store.items]
    parts.validate(installed, stocked)
    assert Counter(initial_by_item) + supply.created_counts == Counter(r['iid'] for r in parts.records.values())
    pool.update()
    return dict(aging=parts.age_snapshot(), supply=supply.snapshot(), service=service.snapshot(),
        availability=totals['available']/denominator, failures=sum(failures.values()), maintenance=None,
        components=parts.snapshot(), mission=manager.finish() if manager else None,
        downtime={s:totals[s]/len(assets) for s in STATES if s!='available'}, samples=samples,
        events=events, events_truncated=event_count>len(events) if config['log'] and replication==0 else False,
        item_failures=dict(failures), resources={f'{station}/{rid}':pool.area[(station,rid)]/(cap*config['horizon']) if cap else 0
                                               for (station,rid),cap in pool.capacity.items()},
        parts=dict(initial=initial, final=len(parts.records), locations=dict(Counter(parts.locations.values()))))
