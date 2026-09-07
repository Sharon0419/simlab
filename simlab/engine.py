"""Closed-loop, serial-LRU discrete event simulation, independent of the UI."""
from collections import Counter
import math
import platform
import numpy as np
import simpy
from . import __version__
from .compiler import compile_model
from .project import model_hash, now

STATES = {'available': '可用', 'waiting_spare': '等待备件',
          'waiting_resource': '等待拆装资源', 'replacement': '拆装作业'}

class ResourcePool:
    """Atomically acquire a complete resource bundle, strict FIFO per station."""
    def __init__(self, env, capacities):
        self.env = env
        self.capacity = capacities.copy()
        self.free = capacities.copy()
        self.queue = []
        self.area = Counter()
        self.last = env.now

    def update(self):
        elapsed = self.env.now - self.last
        for key, cap in self.capacity.items():
            self.area[key] += (cap - self.free[key]) * elapsed
        self.last = self.env.now

    def request(self, station, needs):
        event = self.env.event()
        bundle = {(station, rid): qty for rid, qty in needs.items()}
        if not bundle:
            event.succeed()
            return event
        self.queue.append((station, bundle, event))
        self.dispatch()
        return event

    def dispatch(self):
        blocked = set()
        remaining = []
        for station, bundle, event in self.queue:
            if station not in blocked and all(self.free.get(k, 0) >= q for k, q in bundle.items()):
                self.update()
                for key, qty in bundle.items():
                    self.free[key] -= qty
                event.succeed()
            else:
                blocked.add(station)
                remaining.append((station, bundle, event))
        self.queue = remaining

    def release(self, station, needs):
        self.update()
        for rid, qty in needs.items():
            key = (station, rid)
            self.free[key] += qty
            assert self.free[key] <= self.capacity[key]
        self.dispatch()

def run_one(config, replication=0, progress=None):
    env = simpy.Environment()
    failure_rng = np.random.default_rng(np.random.SeedSequence([replication, 0, config['seed']]))
    repair_rng = np.random.default_rng(np.random.SeedSequence([replication, 1, config['seed']]))
    replace_rng = np.random.default_rng(np.random.SeedSequence([replication, 2, config['seed']]))
    pool = ResourcePool(env, config['capacity'])
    stores, locations, assets, events, samples = {}, {}, [], [], []
    failures = Counter()
    serial = 0
    event_count = 0
    def token(iid, location):
        nonlocal serial
        serial += 1
        name = f'{iid}#{serial}'
        locations[name] = location
        return name
    def store(station, iid):
        return stores.setdefault((station, iid), simpy.Store(env))
    for (station, iid), qty in config['stock'].items():
        for _ in range(qty):
            store(station, iid).put(token(iid, 'stock'))
    def log(asset, action, item=''):
        nonlocal event_count
        event_count += 1
        if config['log'] and replication == 0 and len(events) < 5000:
            events.append({'time': round(env.now, 5), 'asset': asset, 'event': action, 'item': item})
    def duration(spec, rng):
        mean = spec['mean']
        return float(rng.exponential(mean)) if spec['random'] and mean else mean
    def state(asset, next_state):
        asset['times'][asset['state']] += env.now - asset['last']
        asset['last'] = env.now
        asset['state'] = next_state
    def repair(fleet, iid, part):
        root, home = fleet['root'], fleet['home']
        locations[part] = 'transport'
        if root != home:
            yield env.timeout(config['links'][home]['outward'])
        rule = config['repairs'][(root, iid)]
        locations[part] = 'repair_queue'
        yield pool.request(root, rule['resources'])
        locations[part] = 'repair'
        yield env.timeout(duration(rule['time'], repair_rng))
        pool.release(root, rule['resources'])
        locations[part] = 'stock'
        yield store(root, iid).put(part)
        log(root, '部件修复返库', iid)
    def replenish(fleet, iid):
        part = yield store(fleet['root'], iid).get()
        locations[part] = 'transport'
        yield env.timeout(config['links'][fleet['home']]['inward'])
        locations[part] = 'stock'
        yield store(fleet['home'], iid).put(part)
        log(fleet['home'], '补充备件到达', iid)
    def operate(asset, fleet):
        rates = np.array([p['rate'] * fleet['util'] for p in asset['slots']], dtype=float)
        total = float(rates.sum())
        if total == 0:
            return
        while True:
            yield env.timeout(float(failure_rng.exponential(1 / total)))
            slot = asset['slots'][int(failure_rng.choice(len(rates), p=rates / total))]
            iid, broken = slot['iid'], slot['token']
            failures[iid] += 1
            log(asset['id'], '发生故障', iid)
            rule = config['replacements'][(fleet['sid'], iid, fleet['home'])]
            replacement_time = duration(rule['time'], replace_rng)
            state(asset, 'waiting_resource')
            yield pool.request(fleet['home'], rule['resources'])
            state(asset, 'replacement')
            yield env.timeout(replacement_time * config['remove_fraction'])
            pool.release(fleet['home'], rule['resources'])
            slot['token'] = None
            env.process(repair(fleet, iid, broken))
            if fleet['root'] != fleet['home']:
                env.process(replenish(fleet, iid))
            state(asset, 'waiting_spare')
            spare = yield store(fleet['home'], iid).get()
            locations[spare] = 'held'
            state(asset, 'waiting_resource')
            yield pool.request(fleet['home'], rule['resources'])
            state(asset, 'replacement')
            yield env.timeout(replacement_time * (1-config['remove_fraction']))
            pool.release(fleet['home'], rule['resources'])
            slot['token'] = spare
            locations[spare] = 'installed'
            state(asset, 'available')
            log(asset['id'], '恢复可用', iid)
    for fleet in config['fleets']:
        for index in range(fleet['quantity']):
            slots = []
            for part in fleet['parts']:
                for _ in range(part['quantity']):
                    slots.append({'iid': part['iid'], 'rate': part['rate'], 'token': token(part['iid'], 'installed')})
            asset = {'id': f"{fleet['sid']}@{fleet['unit']}-{index+1:03d}", 'slots': slots,
                     'state': 'available', 'last': 0, 'times': Counter()}
            assets.append(asset)
            env.process(operate(asset, fleet))
    initial_parts = len(locations)
    def observe():
        while True:
            samples.append({'time': env.now, 'available': sum(a['state'] == 'available' for a in assets) / len(assets)})
            if progress:
                progress(min(env.now / config['horizon'], 1))
            yield env.timeout(config['interval'])
    env.process(observe())
    env.run(until=config['horizon'])
    samples.append({'time': env.now, 'available': sum(a['state'] == 'available' for a in assets) / len(assets)})
    totals = Counter()
    for asset in assets:
        state(asset, asset['state'])
        totals.update(asset['times'])
    pool.update()
    denominator = config['horizon'] * len(assets)
    assert abs(sum(totals.values()) - denominator) < max(1e-6, denominator * 1e-9)
    installed = [slot['token'] for a in assets for slot in a['slots'] if slot['token'] is not None]
    stocked = [p for s in stores.values() for p in s.items]
    assert len(installed) == len(set(installed))
    assert len(stocked) == len(set(stocked))
    assert not set(installed) & set(stocked)
    assert len(locations) == initial_parts
    assert sum(loc == 'installed' for loc in locations.values()) == len(installed)
    assert sum(loc == 'stock' for loc in locations.values()) == len(stocked)
    return {'availability': totals['available'] / denominator, 'failures': sum(failures.values()),
            'downtime': {s: totals[s] / len(assets) for s in STATES if s != 'available'},
            'samples': samples, 'events': events, 'events_truncated': event_count > len(events) if config['log'] and replication == 0 else False,
            'item_failures': dict(failures),
            'resources': {f'{station}/{rid}': pool.area[(station, rid)] / (cap * config['horizon']) if cap else 0
                          for (station, rid), cap in pool.capacity.items()},
            'parts': {'initial': initial_parts, 'final': sum(Counter(locations.values()).values()),
                      'locations': dict(Counter(locations.values()))}}

def t95(n):
    values = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
              2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
              2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]
    df = n-1
    if df <= 30:
        return values[df-1]
    z = 1.959963984540054
    return z + (z**3+z)/(4*df) + (5*z**5+16*z**3+3*z)/(96*df**2)

def simulate(tables, progress=None):
    config = compile_model(tables)
    results = []
    for rep in range(config['replications']):
        callback = (lambda fraction, r=rep: progress((r+fraction)/config['replications'])) if progress else None
        results.append(run_one(config, rep, callback))
    availability = np.array([r['availability'] for r in results])
    mean = float(availability.mean())
    half = t95(len(results)) * float(availability.std(ddof=1)) / math.sqrt(len(results)) if len(results) > 1 else None
    samples = [{'time': row['time'], 'available': float(np.mean([r['samples'][i]['available'] for r in results]))}
               for i, row in enumerate(results[0]['samples'])]
    if progress:
        progress(1.0)
    return {'engine': __version__, 'created': now(), 'model_hash': model_hash(tables),
            'versions': {'python': platform.python_version(), 'simpy': simpy.__version__, 'numpy': np.__version__},
            'seed': config['seed'], 'replications': len(results), 'horizon': config['horizon'],
            'fleet_size': config['count'], 'point': config['point'], 'availability': mean,
            'ci95': [max(0, mean-half), min(1, mean+half)] if half is not None else None,
            'p05': float(np.quantile(availability, 0.05)), 'p95': float(np.quantile(availability, 0.95)),
            'failures': float(np.mean([r['failures'] for r in results])), 'samples': samples,
            'downtime': {key: float(np.mean([r['downtime'][key] for r in results])) for key in results[0]['downtime']},
            'resources': {key: float(np.mean([r['resources'][key] for r in results])) for key in results[0]['resources']},
            'events': results[0]['events'], 'events_truncated': results[0]['events_truncated'],
            'replication_results': [{k: v for k, v in r.items() if k not in ('samples', 'events')} for r in results],
            'assumptions': '一层串联 LRU；连续使用率；指数故障；故障后系统暂停运行；两级维修闭环；资源组合原子申请；无任务调度。'}
