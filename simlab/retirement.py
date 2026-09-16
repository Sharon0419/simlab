"""Lifetime limits on physical identities, independent of effective repair age."""
import math


class Retirement:
    def __init__(self, service):
        self.service, self.parts, self.env = service, service.parts, service.env
        self.rules = {r['IID']: r for r in service.tables.get('SimLabItemRetirement', [])}
        self.enabled = bool(self.rules or service.tables.get('SimLabPurchasePolicy'))
        self.rows = []
        self.total = 0

    def tree(self, part):
        yield self.parts.records[part]
        for child in self.parts.records[part]['children']:
            if child is not None:
                yield from self.tree(child)

    def reason(self, record):
        rule = self.rules.get(record['iid'], {})
        if rule.get('LIMIT_H') and record['lifetime_hours'] >= float(rule['LIMIT_H']) - 1e-10:
            return 'LIMIT_H'
        if rule.get('LIMIT_REPAIRS') and record.get('corrective_repairs', 0) >= int(float(rule['LIMIT_REPAIRS'])):
            return 'LIMIT_REPAIRS'
        return None

    def remaining(self, record, rate):
        rule = self.rules.get(record['iid'], {})
        if not rate or not rule.get('LIMIT_H') or record.get('retirement_due') or record.get('retired'):
            return math.inf
        ancestor = record
        while ancestor['parent']:
            ancestor = self.parts.records[ancestor['parent']]
            if ancestor.get('retirement_due') or ancestor.get('retired'):
                return math.inf
        return max(0., float(rule['LIMIT_H']) - record['lifetime_hours']) / rate

    def due(self):
        if not self.rules:
            return
        with self.service.registration_batch():
            # Physical creation order puts parents before descendants.
            for record in list(self.parts.records.values()):
                reason = self.reason(record)
                if reason:
                    self.request(record['id'], reason)

    def request(self, part, reason):
        record = self.parts.records[part]
        ancestor = record
        while True:
            if ancestor.get('retired') or ancestor.get('retirement_due'):
                return
            if not ancestor['parent']:
                break
            ancestor = self.parts.records[ancestor['parent']]
        record['retirement_due'] = reason
        service = self.service
        members = {r['id'] for r in self.tree(part)}
        for job in service.jobs:
            if job['part'] in members and job['status'] == 'queued':
                job.update(status='cancelled_retirement', ended_at=self.env.now)
        if service.clocks:
            for member in members:
                service.clocks.clocks.pop(member, None)
        asset, slot = service.locate(part)
        root = service.root(part)
        if not record['parent'] and asset is None:
            self.dispose(part, reason)
            return
        station = asset['home'] if asset else self.parts.records[root]['site']
        mid = self.parts.records[record['parent']]['iid'] if record['parent'] else asset['sid']
        service.create_job(part, 'RETIREMENT', mid, station, asset, slot)
        service.advance()

    def dispose(self, part, reason=None, asset=''):
        record = self.parts.records[part]
        if record.get('retired'):
            return
        reason = reason or record.get('retirement_due') or 'PARENT_RETIREMENT'
        self.service.supply.withdraw(part)
        for member in self.tree(part):
            member.update(retired=True, retirement_due=reason if member['id'] == part else 'PARENT_RETIREMENT')
            self.total += 1
            if len(self.rows) < 10000:
                self.rows.append(dict(part=member['id'], iid=member['iid'], time=self.env.now,
                    reason=member['retirement_due'], lifetime_hours=member['lifetime_hours'],
                    corrective_repairs=member.get('corrective_repairs', 0), site=record['site'], asset=asset))
            if self.service.clocks:
                self.service.clocks.clocks.pop(member['id'], None)
            for job in self.service.jobs:
                if job['part'] == member['id'] and job['status'] == 'queued':
                    job.update(status='cancelled_retirement', ended_at=self.env.now)
        self.service.quarantined.discard(part)
        self.parts.move(part, 'retired', record['site'])

    def snapshot(self):
        if not self.enabled:
            return {}
        rows = []
        for record in list(self.parts.records.values())[:10000]:
            root = self.parts.records[self.service.root(record['id'])]
            rows.append(dict(part=record['id'], iid=record['iid'], parent=record['parent'] or '',
                lifetime_hours=record['lifetime_hours'], corrective_repairs=record.get('corrective_repairs', 0),
                retired=record.get('retired', False), retirement_due=record.get('retirement_due', ''),
                site=root['site'], location=self.parts.locations[root['id']]))
        return dict(retirements=self.rows, retirements_total=self.total, retirements_truncated=self.total>len(self.rows),
                    lifetimes=rows, lifetimes_total=len(self.parts.records), lifetimes_truncated=len(self.parts.records)>len(rows))
