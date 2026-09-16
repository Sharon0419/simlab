"""M2 mixed maintenance/aging acceptance cases and packaged replay."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import simulate, run_one
from simlab.project import load_project, new_project, save_project, export_package, import_package
from simlab.flight_results import export_aging
from run_aircraft_inspection_case import audit

OUT = ROOT / 'docs/cases/2026-09-15-aircraft-aging'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = {}
    if not args.verify_only:
        old = load_project(ROOT / 'docs/cases/2026-09-15-aircraft-inspection/飞机飞行小时检查.sqlite')
        replay = simulate(old['tables'])
        for key in ('mission', 'events', 'replication_results', 'availability', 'resources', 'downtime'):
            assert replay[key] == old['runs'][0]['result'][key], key
        evidence['legacy_1000_equal'] = True
        for mode, title in [('PERFECT', '修复如新'), ('MINIMAL', '最小修复')]:
            tables = copy.deepcopy(old['tables'])
            tables['SimLabItemAging'] = []
            for item in tables['Item']:
                item['FRT'] = '0'
                tables['SimLabItemAging'].append(dict(IID=item['IID'], SHAPE='2', SCALE_H='40', INITIAL_H='20', REPAIR=mode))
            result = simulate(tables)
            audit(result)
            count = 0
            for rep in result['replication_results']:
                ages = rep['aging']
                assert not ages['events_truncated'] and not ages['instances_truncated']
                assert len(ages['instances']) == 48
                for event in ages['events']:
                    if event['event'] == 'repair':
                        count += 1
                        assert event['age_after'] == (0 if mode == 'PERFECT' else event['age_before'])
                for part in ages['instances']:
                    events = [e for e in ages['events'] if e['part'] == part['part'] and e['event'] == 'repair']
                    erased = sum(e['age_before']-e['age_after'] for e in events)
                    assert abs(part['lifetime_hours']-part['age']-erased) < 1e-7
            assert count > 0
            project = new_project(f'飞机部件老化 · {title} · 12架 · 1000次')
            project['tables'] = tables
            run = dict(id=f'aging-{mode}', name=title, status='completed', started=result['created'],
                       source_revision=project['revision'], snapshot=copy.deepcopy(tables),
                       model_hash=result['model_hash'], result=result)
            project['runs'] = [run]
            save_project(project, OUT / f'{mode}.sqlite')
            export_package(project, OUT / f'{mode}.simproj')
            assert import_package(OUT / f'{mode}.simproj')['runs'] == [run]
            export_aging(run, OUT / f'{mode}-ages.csv')
            export_aging(run, OUT / f'{mode}-events.csv', True)
            evidence[mode] = dict(replications=result['replications'], repairs=count, failures=result['failures'],
                                  success_rate=result['mission']['flight']['success_rate'], age_conservation=True)
            print(mode, evidence[mode], flush=True)
        (OUT / 'verification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    if args.exe:
        work = ROOT / 'build/qa-v092-replay'
        work.mkdir(parents=True, exist_ok=True)
        for mode in ('PERFECT', 'MINIMAL'):
            project = load_project(OUT / f'{mode}.sqlite')
            tables = copy.deepcopy(project['tables'])
            tables['Control'][0]['NREPS'] = '1'
            source = run_one(compile_model(tables))
            inp, output = work / f'{mode}-input.json', work / f'{mode}-result.json'
            inp.write_text(json.dumps(tables), encoding='utf-8')
            if output.exists():
                output.unlink()
            subprocess.run([str(args.exe.resolve()), '--worker', str(inp), str(output)], check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            packed = json.loads(output.read_text(encoding='utf-8'))
            stored = project['runs'][0]['result']
            assert packed['events'] == source['events'] == stored['events']
            for key, value in packed['replication_results'][0].items():
                assert value == source[key] == stored['replication_results'][0][key], key
        (OUT / 'release-verification.json').write_text(json.dumps(dict(engine=packed['engine'], both_modes_source_package_stored_equal=True)), encoding='utf-8')
        print('Both repair modes: source/package/stored first replication equal', flush=True)


if __name__ == '__main__':
    main()
