"""Closed-loop, serial-LRU discrete event simulation, independent of the UI."""
from collections import Counter
import math
import platform
import numpy as np
import simpy
from . import __version__
from .compiler import compile_model
from .project import model_hash, now
from .missions import MissionManager, GAP_LABELS
from .flight import FlightManager
from .components import Components
from .aging_components import AgingComponents
from .maintenance import Workshop, aggregate as aggregate_maintenance
from .redundancy import asset_capable, fault_summary, RedundantExposure

STATES = {'available': '可用', 'waiting_spare': '等待备件',
          'planned_wait': '计划维修等待资源', 'planned_maintenance': '计划维修作业',
          'returning_failed': '故障返航（尚未落地）',
          'waiting_resource': '等待拆装资源', 'replacement': '拆装作业'}

class ResourcePool:
    """Atomically acquire a complete resource bundle, strict FIFO per station."""
    def __init__(self, env, capacities, schedules=None):
        self.env = env
        self.capacity = capacities.copy()
        self.free = capacities.copy()
        self.queue = []
        self.area = Counter()
        self.last = env.now
        self.schedules = schedules or {}
        if self.schedules:
            env.process(self.openings())

    def openings(self):
        for time in sorted({start for spans in self.schedules.values() for start, _ in spans}):
            yield self.env.timeout(time - self.env.now)
            self.dispatch()

    def on_shift(self, key):
        return key not in self.schedules or any(start <= self.env.now < end for start, end in self.schedules[key])

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
            if station not in blocked and all(self.free.get(k, 0) >= q and (q == 0 or self.on_shift(k)) for k, q in bundle.items()):
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

    def cancel(self, event):
        """Remove an ungranted ground request; granted resources need release."""
        for request in self.queue:
            if request[2] is event:
                self.queue.remove(request)
                event.succeed(False)
                self.dispatch()
                return True
        return False

def run_one(config, replication=0, progress=None):
    if config.get('m3'):
        from .m3_engine import run_one as run_m3
        return run_m3(config, replication, progress)
    env = simpy.Environment()
    failure_rng = np.random.default_rng(np.random.SeedSequence([replication, 0, config['seed']]))
    repair_rng = np.random.default_rng(np.random.SeedSequence([replication, 1, config['seed']]))
    replace_rng = np.random.default_rng(np.random.SeedSequence([replication, 2, config['seed']]))
    pool = ResourcePool(env, config['capacity'], config.get('schedules'))
    workflow_runner = None
    if config.get('workflows'):
        from .workflows import WorkflowExecutor
        workflow_runner = WorkflowExecutor(env, pool, config['workflows']['plans'],
            np.random.default_rng(np.random.SeedSequence([replication, 5, config['seed']])))
    mission_manager = None
    redundant_clock = None
    aging_enabled = bool(config.get('aging') or config.get('redundancy'))
    components = (AgingComponents(config.get('children', {}), config.get('aging', {}), env)
                  if aging_enabled else Components(config.get('children', {})))
    components.redundancy = config.get('redundancy', {})
    stores, locations, assets, events, samples = {}, components.locations, [], [], []
    failures = Counter()
    event_count = 0
    def token(iid, location, site=''):
        return components.create(iid, location, site)
    def store(station, iid):
        return stores.setdefault((station, iid), simpy.Store(env))
    for (station, iid), qty in config['stock'].items():
        for _ in range(qty):
            store(station, iid).put(token(iid, 'stock', station))
    def log(asset, action, item=''):
        nonlocal event_count
        event_count += 1
        if config['log'] and replication == 0 and len(events) < 5000:
            events.append({'time': round(env.now, 5), 'asset': asset, 'event': action, 'item': item})
    def duration(spec, rng):
        mean = spec['mean']
        return float(rng.exponential(mean)) if spec['random'] and mean else mean
    def state(asset, next_state):
        if redundant_clock:
            redundant_clock.integrate()
        asset['times'][asset['state']] += env.now - asset['last']
        asset['last'] = env.now
        asset['state'] = next_state
        if mission_manager:
            mission_manager.rebalance()
        if redundant_clock:
            redundant_clock.changed()
    workshop = Workshop(env, config, components, pool, store, repair_rng, log) if config.get('children') else None
    def repair(fleet, iid, part):
        if workshop:
            yield from workshop.repair(fleet, iid, part)
            return
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
        components.restore(part)
        locations[part] = 'stock'
        yield store(root, iid).put(part)
        log(root, '部件修复返库', iid)
    def replenish(fleet, iid):
        part = yield store(fleet['root'], iid).get()
        components.move(part, 'transport', fleet['home'])
        yield env.timeout(config['links'][fleet['home']]['inward'])
        components.move(part, 'stock', fleet['home'])
        yield store(fleet['home'], iid).put(part)
        log(fleet['home'], '补充备件到达', iid)
    def repair_slot(asset, fleet, slot):
        iid, broken = slot['iid'], slot['token']
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
        components.move(spare, 'held', fleet['home'])
        state(asset, 'waiting_resource')
        yield pool.request(fleet['home'], rule['resources'])
        state(asset, 'replacement')
        yield env.timeout(replacement_time * (1-config['remove_fraction']))
        pool.release(fleet['home'], rule['resources'])
        slot['token'] = spare
        components.move(spare, 'installed', fleet['home'])

    def record_failure(asset, slot, leaf):
        components.fail(slot['token'], leaf)
        iid=components.records[leaf]['iid']
        failures[iid] += 1
        log(asset['id'], '发生故障', iid)
        if workshop:
            log(slot['token'], '故障叶子', leaf)

    def operate(asset, fleet):
        if config.get('redundancy'):
            yield from operate_redundant(asset, fleet)
            return
        rates = np.array([p['rate'] * fleet['util'] for p in asset['slots']], dtype=float)
        total = float(rates.sum())
        if total == 0 and not aging_enabled:
            return
        while True:
            if workshop or aging_enabled:
                slot, leaf = yield from components.failure(env, asset, fleet, failure_rng, bool(mission_manager))
            else:
                remaining = float(failure_rng.exponential(1 / total))
            if not workshop and not aging_enabled and mission_manager:
                # Preserve the remaining running-time budget across standby
                # periods and reassignment; do not resample at every dispatch.
                while remaining > 0:
                    if asset['mission'] is None:
                        yield asset['assignment_event']
                        continue
                    start = env.now
                    deadline = env.timeout(remaining)
                    outcome = yield deadline | asset['assignment_event']
                    # A completed timeout exhausts the budget exactly. Floating
                    # subtraction can leave a sub-ULP remainder and loop forever.
                    remaining = 0 if deadline in outcome else max(0, remaining - (env.now - start))
            elif not workshop and not aging_enabled:
                yield env.timeout(remaining)
            if not workshop and not aging_enabled:
                slot = asset['slots'][int(failure_rng.choice(len(rates), p=rates / total))]
                leaf = slot['token']
            record_failure(asset, slot, leaf)
            pending_slots=[slot]
            if isinstance(mission_manager, FlightManager) and asset['mission'] is not None:
                state(asset, 'returning_failed')
                # No repair starts in the air. Remaining healthy components can
                # still fail; each failed LRU enters the repair queue once.
                while asset['mission'] is not None:
                    extra = yield from components.failure(env,asset,fleet,failure_rng,True,stop_on_landing=True)
                    if extra is None:
                        break
                    extra_slot, extra_leaf = extra
                    record_failure(asset,extra_slot,extra_leaf)
                    if extra_slot not in pending_slots:
                        pending_slots.append(extra_slot)
            for broken_slot in pending_slots:
                yield from repair_slot(asset,fleet,broken_slot)
            state(asset, 'available')
            log(asset['id'], '恢复可用', ','.join(s['iid'] for s in pending_slots))

    def operate_redundant(asset, fleet):
        while True:
            if not asset['_pending_repairs']:
                yield asset['_fault_event']
            while asset['mission'] is not None:
                yield asset['assignment_event']
            pending = asset['_pending_repairs']
            for slot in pending:
                yield from repair_slot(asset, fleet, slot)
            asset['_pending_repairs'] = []
            asset['_fault_event'] = env.event()
            asset.pop('repair_pending', None)
            state(asset, 'available')
            log(asset['id'], '恢复可用', ','.join(s['iid'] for s in pending))

    def redundant_failed(asset, slot, leaf):
        record_failure(asset, slot, leaf)
        asset['repair_pending'] = True
        if slot not in asset['_pending_repairs']:
            asset['_pending_repairs'].append(slot)
        if not asset['_fault_event'].triggered:
            asset['_fault_event'].succeed()
        log(asset['id'], '冗余组状态', fault_summary(components, asset, config['redundancy']))
        if asset['mission'] is None or not asset_capable(components, asset, config['redundancy']):
            state(asset, 'returning_failed' if isinstance(mission_manager, FlightManager)
                  and asset['mission'] is not None else 'waiting_resource')
    for fleet in config['fleets']:
        for index in range(fleet['quantity']):
            slots = []
            for part in fleet['parts']:
                for _ in range(part['quantity']):
                    slots.append({'iid': part['iid'], 'rate': part['rate'], 'envf': part['envf'], 'token': token(part['iid'], 'installed', fleet['home'])})
            asset = {'id': f"{fleet['sid']}@{fleet['unit']}-{index+1:03d}", 'slots': slots,
                     'state': 'available', 'last': 0, 'times': Counter(),
                     'sid': fleet['sid'], 'unit': fleet['unit'], 'home': fleet['home'],
                     'mission': None, 'assignment_event': env.event()}
            assets.append(asset)
            if config.get('redundancy'):
                asset.update(_fleet=fleet, _pending_repairs=[], _fault_event=env.event())
            env.process(operate(asset, fleet))
    if config.get('redundancy'):
        redundant_clock = RedundantExposure(env, config, components, assets, failure_rng, redundant_failed)
        env.process(redundant_clock.run())
    if config.get('missions'):
        def planned_state(asset, next_state):
            # Called within rebalance: integrate equipment state without recursion.
            if redundant_clock:
                redundant_clock.integrate()
            asset['times'][asset['state']] += env.now-asset['last']
            asset['last'] = env.now
            asset['state'] = next_state
        manager_type = FlightManager if 'flight_prep_hours' in config['missions'][0] else MissionManager
        mission_manager = (manager_type(env, config['missions'], assets, log, resource_pool=pool,
                           planned_rules=config.get('planned', ()), set_state=planned_state)
                           if manager_type is FlightManager else manager_type(env, config['missions'], assets, log))
        if workflow_runner:
            mission_manager.workflow_runner = workflow_runner
        if redundant_clock:
            mission_manager.settle_faults = redundant_clock.settle_faults
            # Both assignment and completion wake the physical operating clock.
            original_rebalance = mission_manager.rebalance
            def rebalance_redundant():
                original_rebalance()
                redundant_clock.changed()
            mission_manager.rebalance = rebalance_redundant
    initial_parts = len(locations)
    initial_by_item = dict(Counter(r['iid'] for r in components.records.values()))
    def observe():
        while True:
            if mission_manager:
                yield env.timeout(0)
            sample = {'time': env.now, 'available': sum(a['state'] == 'available' for a in assets) / len(assets)}
            if mission_manager:
                sample.update(mission_manager.sample())
            samples.append(sample)
            if progress:
                progress(min(env.now / config['horizon'], 1))
            yield env.timeout(config['interval'])
    env.process(observe())
    env.run(until=config['horizon'])
    if redundant_clock:
        redundant_clock.integrate()
    if aging_enabled:
        components.finish_ages()
    if mission_manager:
        mission_manager._dispatching = True
        mission_manager.rebalance()
    sample = {'time': env.now, 'available': sum(a['state'] == 'available' for a in assets) / len(assets)}
    if mission_manager:
        sample.update(mission_manager.sample())
    samples.append(sample)
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
    components.validate(installed, stocked)
    instances = components.snapshot() if workshop else None
    if instances:
        assert instances['by_item'] == initial_by_item
    return {**({'workflows': workflow_runner.snapshot()} if workflow_runner else {}),
            **({'aging': components.age_snapshot()} if aging_enabled else {}),
            'availability': totals['available'] / denominator, 'failures': sum(failures.values()),
            'maintenance': workshop.snapshot() if workshop else None,
            'components': instances,
            'mission': mission_manager.finish() if mission_manager else None,
            'downtime': {s: totals[s] / len(assets) for s in STATES if s != 'available'
                         and (config.get('planned') or not s.startswith('planned_'))},
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
        one = run_one(config, rep, callback)
        if rep and one['mission'] is not None:
            one['mission']['intervals'] = []
        if rep and one['maintenance'] is not None:
            one['maintenance']['jobs'] = []
            one['components']['instances'] = []
        results.append(one)
    availability = np.array([r['availability'] for r in results])
    mean = float(availability.mean())
    half = t95(len(results)) * float(availability.std(ddof=1)) / math.sqrt(len(results)) if len(results) > 1 else None
    samples = [{'time': row['time'], 'available': float(np.mean([r['samples'][i]['available'] for r in results]))}
               for i, row in enumerate(results[0]['samples'])]
    mission = None
    if config['missions']:
        for i, sample in enumerate(samples):
            for key in ('demand', 'supplied', 'minimum'):
                sample[key] = float(np.mean([r['samples'][i][key] for r in results]))
        mission = {key: float(np.mean([r['mission'][key] for r in results]))
                   for key in ('demand_hours', 'supplied_hours', 'gap_hours', 'fulfillment', 'full_window_rate', 'minimum_rate', 'qualified_rate', 'below_hours')}
        mission['intervals'] = results[0]['mission']['intervals']
        mission['intervals_truncated'] = results[0]['mission']['intervals_truncated']
        values = np.array([r['mission']['fulfillment'] for r in results])
        margin = t95(len(results)) * float(values.std(ddof=1)) / math.sqrt(len(results)) if len(results) > 1 else None
        mission['ci95'] = [max(0, mission['fulfillment']-margin), min(1, mission['fulfillment']+margin)] if margin is not None else None
        mission['gap_reasons'] = {key: float(np.mean([r['mission']['gap_reasons'][key] for r in results])) for key in GAP_LABELS}
        mission['tasks'] = []
        if results[0]['mission'].get('flight'):
            mission['flight'] = {key: float(np.mean([r['mission']['flight'][key] for r in results]))
                                 for key in results[0]['mission']['flight']}
        if results[0]['mission'].get('ground'):
            mission['ground']={key:float(np.mean([r['mission']['ground'][key] for r in results]))
                               for key in results[0]['mission']['ground'] if key!='jobs'}
            mission['ground']['jobs']=results[0]['mission']['ground']['jobs']
        if results[0]['mission'].get('planned'):
            mission['planned'] = {key:float(np.mean([r['mission']['planned'][key] for r in results]))
                                  for key in results[0]['mission']['planned'] if key not in ('jobs','clocks')}
            mission['planned']['jobs'] = results[0]['mission']['planned']['jobs']
            if 'clocks' in results[0]['mission']['planned']:
                mission['planned']['clocks'] = results[0]['mission']['planned']['clocks']
        for i, first in enumerate(results[0]['mission']['tasks']):
            task = {key: first[key] for key in ('id', 'type', 'location', 'sid', 'quantity', 'start', 'end', 'demand_hours', 'minimum', 'priority', 'relief_hours', 'tolerance_hours')}
            for key in ('supplied_hours', 'gap_hours', 'below_hours', 'longest_below_hours', 'minimum_rate'):
                task[key] = float(np.mean([r['mission']['tasks'][i][key] for r in results]))
            task['full_window_rate'] = float(np.mean([r['mission']['tasks'][i]['gap_hours'] < 1e-9 for r in results]))
            task['qualified_rate'] = float(np.mean([r['mission']['tasks'][i]['qualified'] for r in results]))
            if 'flight_status' in first:
                task['flight_prep_hours'] = first['flight_prep_hours']
                task['out_fraction'] = first.get('out_fraction',0)
                task['return_fraction'] = first.get('return_fraction',0)
                task['success_fraction'] = first['success_fraction']
                task['success_point'] = first['success_point']
                task['success_rate'] = float(np.mean([r['mission']['tasks'][i]['successful'] for r in results]))
                task['started_rate'] = float(np.mean([r['mission']['tasks'][i]['launched_at'] is not None for r in results]))
                task['successful_aircraft_sorties'] = float(np.mean([len(r['mission']['tasks'][i]['successful_members']) for r in results]))
                for key in ('out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours','abort_return_aircraft_hours'):
                    task[key] = float(np.mean([r['mission']['tasks'][i][key] for r in results]))
                task['flight_rates'] = {status: float(np.mean([r['mission']['tasks'][i]['flight_status']==status for r in results]))
                                       for status in ('completed','aborted','cancelled')}
                task['cancel_rates'] = {reason:float(np.mean([r['mission']['tasks'][i]['cancel_reason']==reason for r in results]))
                                        for reason in ('fleet_shortage','maintenance','airborne','preparation_wait','preparing',
                                                       *(['planned_maintenance'] if config.get('planned') else []))}
            mission['tasks'].append(task)
    if progress:
        progress(1.0)
    result = {**({'aging': results[0]['aging']} if config.get('aging') or config.get('m3') or config.get('redundancy') else {}),
            'engine': __version__, 'created': now(), 'model_hash': model_hash(tables),
            'maintenance': aggregate_maintenance(results) if config.get('children') and not config.get('m3') else None,
            **({'supply': results[0]['supply'], 'service': results[0]['service']} if config.get('m3') else {}),
            'components': results[0]['components'],
            **({'workflows': results[0]['workflows']} if config.get('workflows') else {}),
            'mission': mission,
            'versions': {'python': platform.python_version(), 'simpy': simpy.__version__, 'numpy': np.__version__},
            'seed': config['seed'], 'replications': len(results), 'horizon': config['horizon'],
            'fleet_size': config['count'], 'point': config['point'], 'availability': mean,
            'ci95': [max(0, mean-half), min(1, mean+half)] if half is not None else None,
            'p05': float(np.quantile(availability, 0.05)), 'p95': float(np.quantile(availability, 0.95)),
            'failures': float(np.mean([r['failures'] for r in results])), 'samples': samples,
            'downtime': {key: float(np.mean([r['downtime'][key] for r in results])) for key in results[0]['downtime']},
            'resources': {key: float(np.mean([r['resources'][key] for r in results])) for key in results[0]['resources']},
            'events': results[0]['events'], 'events_truncated': results[0]['events_truncated'],
            'replication_results': [{k: v for k, v in r.items() if k not in ('samples', 'events', 'components', 'maintenance')} for r in results],
            'assumptions': ('实物叶子寿命：配置部件使用条件威布尔寿命，其他叶子使用指数故障；有效年龄按运行小时乘使用率累计，风险倍数不缩放年龄；维修按修复如新或最小修复，检查不重置年龄。' if config.get('aging') else
                'System/LRU/SRU 串联；基地换LRU、站内维修SRU；叶子指数故障；' if config.get('children') else '一层串联 LRU；指数故障；') + '两级维修闭环；资源组合原子申请；班内启动、跨班继续。' +
                ('固定飞行；整队起飞/故障中止，空中不补位；三阶段中止返航，落地后故障LRU依次处理；再次出动准备按资源组合排队、班内开始跨班继续，不累计故障；DAILY_READY按输入逐池执行，首波假设接续未完作业单列，故障机不恢复。' if mission and mission.get('ground') else
                 '固定飞行；每日全池保障；整队起飞/故障中止；空中不补位；TFOUT/TFRET三阶段及中止返航；返航健康部件继续故障，落地后故障LRU依次处理；保障无资源约束且不累计故障。' if mission and mission.get('flight') else
                 '固定值守窗口；优先级分配、不抢占；故障退出、按规则准备补位；待命和准备不累计运行故障；最低保障按事件积分。' if mission else '连续使用率；无任务调度。') +
                ('日历计划维修到期停派；在飞、故障维修及已有准备先完成；重复到期逐次排队，固定作业后重新准备，首波假设不跳过；计划资源等待与作业计入停机，不更换部件或重置故障时钟。' if config.get('planned') else '')+
                ('飞行小时检查逐架累计实际在空时间，包含中止返航；空中到期继续任务，落地检查。每周期一张工单，检查完成本项计时归零；与日历维修串行，全部完成统一准备；初始小时按输入，不改变部件年龄与故障预算。' if any('flight_interval' in r for r in config.get('planned',[])) else '')}

    if config.get('m3'):
        result['assumptions'] = ('M3 显式三级供应与维修；有向补给、按时长候补和拆分；唯一订单及实物守恒，无运输容量限制。'
            '修复性与预防性工单分别抽取一次原位/换件方式；送修采用显式有向最短路径，父子树串行锁定。'
            '叶子实物日历/有效运行预防时钟独立；库存和在途日历到期隔离，预防完成修复如新并保留终身小时。'
            '空中预防到期不单独中止；落地与整机计划维修、飞行检查共享串行地面队列，清空后统一准备。'
            '资源组合原子申请，班内启动、跨班继续；期末未完订单和作业保留。供应与服务顶层明细取首轮，各轮明细另列。')
    if config.get('redundancy'):
        result['assumptions'] = ('本项目启用同父项同型号n中取k，取代下述串联/任一故障中止假设：'
            '各型号组分别满足k；仍具工作能力的部件全部运行；在途仍满足能力继续任务，低于阈值返航；'
            '全部实物故障落地后维修，等待及作业期间禁止新任务；同刻故障与修复先结算再派遣。'
            + result['assumptions'])
    return result
