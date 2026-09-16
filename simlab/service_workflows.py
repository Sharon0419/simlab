"""Physical repair actions attached to workflow completion boundaries."""
from .workflow_config import bound_plan


def plan_for(service, job):
    if job['_off']:
        return bound_plan(service.config, 'OFF_ITEM', iid=job['iid'],
                          station=job['station'], kind=job['kind'])
    return bound_plan(service.config, 'MAINTENANCE', rule=job['rule'],
                      method='RETIREMENT' if job['kind'] == 'RETIREMENT' else job['method'])


def execute(service, job, plan):
    s = service
    part = job['part']
    record = s.parts.records[part]
    physical = {}

    def before(action, node):
        if action == 'INSTALL':
            job['status'] = 'waiting_spare'
            if job['_asset']:
                s.set_state(job['_asset'], 'waiting_spare')
            spare = yield s.supply.request_part(job['station'], job['iid'], owner=job['id'])
            physical['spare'] = spare
            s.reservations[spare] = job
        elif action == 'IN_PLACE' and record['children']:
            yield from s.children(job)

    def after(action, node):
        if action == 'REMOVE':
            parent = physical['parent'] = record['parent']
            if parent:
                if job['kind'] == 'RETIREMENT':
                    job['_assembly'] = parent
                physical['index'] = s.parts.detach(parent, part)
            else:
                job['_slot']['token'] = None
                s.parts.move(part, 'held', job['station'])
            if job['kind'] == 'RETIREMENT':
                s.retirement.dispose(part, asset=job['asset'])
            else:
                off = s.create_job(part, job['kind'], job['parent'], job['station'], off=True)
                off['status'] = 'starting'
            for pending in s.jobs:
                if pending is not job and s.root(pending['part']) == part and pending['status'] == 'queued':
                    pending.update(_asset=None, _slot=None, asset='')
                    if pending['part'] == part:
                        pending.update(_off=True, method='OFF_ITEM')
            if job['kind'] != 'RETIREMENT':
                s.locks[part] = off['id']
                s.env.process(s.run(off, part))
        elif action == 'INSTALL':
            spare = physical.pop('spare')
            if s.runtime:
                s.runtime.due()
            s.reservations.pop(spare, None)
            if not s.eligible(spare):
                s.quarantined.add(spare)
                for pending in s.jobs:
                    if pending['status'] == 'queued' and s.root(pending['part']) == spare:
                        pending.update(_asset=None, _slot=None, asset='')
                s.advance()
                return 'retry'
            parent = physical['parent']
            if parent:
                s.parts.attach(parent, physical['index'], spare)
                if job['kind'] == 'RETIREMENT' and all(c and not s.parts.records[c]['broken'] for c in s.parts.records[parent]['children']):
                    s.parts.restore(parent)
            else:
                job['_slot']['token'] = spare
                s.parts.move(spare, 'installed', job['station'])
        elif action == 'SERVICE' and record['children']:
            # The parent's own resources have already been released. Child
            # repairs may request the same pool without self-deadlocking.
            yield from s.children(job)

    def changed(workflow):
        states = {n['status'] for n in workflow['nodes']}
        if 'working' in states:
            job['status'] = 'working'
            if job['_asset']:
                s.set_state(job['_asset'], 'replacement')
        elif 'waiting' in states:
            job['status'] = 'waiting_resource'
            if job['_asset']:
                s.set_state(job['_asset'], 'waiting_resource')

    context = dict(activity='OFF_ITEM' if job['_off'] else 'MAINTENANCE', owner=job['id'],
        asset=job['asset'], part=part, station=job['station'], kind=job['kind'], method=job['method'])
    workflow = s.workflows.start(plan, context, before=before, after=after, on_change=changed)
    yield workflow['event']
    if not record['children'] and (job['_off'] or job['method'] == 'IN_PLACE'):
        s.finish_leaf(job)
