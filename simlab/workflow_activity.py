"""Binding lookup before workflow compilation and aircraft-level time accounting."""


def configured_plan(tables, activity, rule):
    """Only identify replacement intent here; compile_workflows validates it later."""
    return next((r['WFID'] for r in tables.get('SimLabWorkflowBinding', [])
                 if r.get('ACTIVITY') == activity and r.get('RULEID') == rule), None)


def aircraft_timing(workflow, pool, now):
    """Partition elapsed aircraft hours, counting overlapping steps only once.

    Work takes precedence over concurrent waits. While no step works, an
    on-shift resource waiter takes precedence over off-shift waiters; otherwise
    the aircraft is shift-blocked. This measures aircraft occupation, not the
    sum of resource or individual step hours.
    """
    end = workflow['ended_at'] if workflow['ended_at'] is not None else now
    start = workflow['created_at']
    station = workflow['context']['station']
    nodes = [attempt for n in workflow['nodes'] for attempt in n.get('history', [])+[n]]
    boundaries = {start, end}
    work, waiting = [], []
    for n in nodes:
        node_end = n['ended_at'] if n['ended_at'] is not None else end
        requested = n['requested_at']
        began = n['started_at']
        if began is not None:
            work_end = n.get('work_ended_at', min(node_end, began+n['duration']))
            work.append((began, work_end))
            boundaries.update((began, work_end))
        if requested is not None:
            wait_end = began if began is not None else node_end
            waiting.append((requested, wait_end, n['resources']))
            boundaries.update((requested, wait_end))
            for rid, quantity in n['resources'].items():
                if quantity:
                    for a, b in pool.schedules.get((station, rid), []):
                        boundaries.update((a, b))
    points = sorted(t for t in boundaries if start <= t <= end)
    result = dict(work_hours=0., wait_shift_hours=0., wait_resource_hours=0.)
    for a, b in zip(points, points[1:]):
        if any(x <= a < y for x, y in work):
            key = 'work_hours'
        else:
            needs = [needs for x, y, needs in waiting if x <= a < y]
            def on_shift(needs):
                return all(not qty or any(x <= a < y for x, y in pool.schedules.get(
                    (station, rid), [(0, float('inf'))])) for rid, qty in needs.items())
            key = 'wait_shift_hours' if needs and not any(map(on_shift, needs)) else 'wait_resource_hours'
        result[key] += b-a
    result['wait_hours'] = result['wait_shift_hours']+result['wait_resource_hours']
    return result
