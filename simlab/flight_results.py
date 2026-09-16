"""Flight assessment presentation and lossless native CSV exports."""
import csv
import json

REASONS = {'not_started':'尚未起飞', 'awaiting_success_point':'尚未到成功点',
           'success_point_reached':'已达到成功点', 'aborted_before_success_point':'成功点前中止',
           'cancelled_unready':'就绪飞机不足，取消'}
PHASES = {'OUT':'出航', 'ON_STATION':'任务区', 'BACK':'返航', 'LANDED':'计划落地'}
STATUSES = {'scheduled':'待执行','launched':'飞行中','completed':'完整完成','aborted':'中止','cancelled':'取消'}
CANCEL_REASONS={'fleet_shortage':'部署飞机不足','maintenance':'健康飞机不足','airborne':'其他飞行占用',
                'planned_maintenance':'计划维修到期或执行中',
                'preparation_wait':'准备仍在排队','preparing':'准备尚未完成'}
GROUND_STATUSES={'waiting':'排队中','working':'作业中','completed':'正常完成','assumed_ready':'首波假设接续完成'}
PLANNED_STATUSES={'deferred':'等待落地、故障修复或前序作业','waiting':'等待资源或班次','working':'维修中','completed':'已完成'}
PHASE_FIELDS = ['out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours','abort_return_aircraft_hours']
SUCCESS_FIELDS = ['success_fraction','success_point','successful','success_at','success_phase','success_reason','successful_members']


def export_tasks(run, path, detailed=False):
    result=run['result']
    mission=result.get('mission')
    if not mission:
        raise ValueError('本实验没有任务结果。')
    columns=['id','start','end','quantity','demand_hours','supplied_hours','gap_hours']
    if detailed:
        if not mission.get('flight'):
            raise ValueError('逐轮飞行明细仅用于固定飞行实验。')
        columns+=['flight_status','members','launched_at','ended_at','landed_at','abort_phase','cancel_reason','launch_readiness']+SUCCESS_FIELDS+PHASE_FIELDS
        rows=[(i,t) for i,r in enumerate(result['replication_results'],1) for t in r['mission']['tasks']]
    else:
        columns+=['full_window_rate']
        if 'minimum_rate' in mission:
            columns+=['minimum','priority','relief_hours','tolerance_hours','minimum_rate','qualified_rate','below_hours','longest_below_hours']
        if mission.get('flight'):
            columns+=['flight_prep_hours','out_fraction','return_fraction','success_fraction','success_point',
                      'started_rate','success_rate','successful_aircraft_sorties','completed_rate','aborted_rate','cancelled_rate','cancel_rates']+PHASE_FIELDS
        rows=[('',dict(t,**{k+'_rate':v for k,v in t.get('flight_rates',{}).items()})) for t in mission['tasks']]
    with open(path,'w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['run_id','model_hash','seed','engine','replication']+columns)
        for replication,t in rows:
            values=[t.get(k) for k in columns]
            values=[json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for v in values]
            writer.writerow([run['id'],run['model_hash'],result['seed'],result['engine'],replication]+values)


def export_ground(run,path):
    result=run['result']
    if not (result.get('mission') or {}).get('ground'):raise ValueError('本实验没有资源约束准备作业结果。')
    columns=['id','asset','station','task','resources','duration','requested_at','started_at','ended_at','status','wait_hours','work_hours']
    with open(path,'w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['run_id','model_hash','seed','engine','replication']+columns)
        for i,rep in enumerate(result['replication_results'],1):
            for job in rep['mission']['ground']['jobs']:
                writer.writerow([run['id'],run['model_hash'],result['seed'],result['engine'],i]+
                                [json.dumps(job[k],ensure_ascii=False) if isinstance(job[k],dict) else job[k] for k in columns])


def export_planned(run, path):
    result = run['result']
    if not (result.get('mission') or {}).get('planned'):
        raise ValueError('本实验没有日历计划维修结果。')
    columns = ['id','rule','asset','station','task','resources','duration','due_at','requested_at',
               'started_at','ended_at','status','deferred_hours','wait_hours','work_hours']
    if 'clocks' in result['mission']['planned']:
        columns += ['trigger','interval_hours','cycle_hours','overrun_hours']
    with open(path, 'w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['run_id','model_hash','seed','engine','replication']+columns)
        for i, rep in enumerate(result['replication_results'], 1):
            for job in rep['mission']['planned']['jobs']:
                writer.writerow([run['id'],run['model_hash'],result['seed'],result['engine'],i]+
                    [json.dumps(job.get(k),ensure_ascii=False) if isinstance(job.get(k),dict)
                     else job.get(k,'calendar' if k=='trigger' else '') for k in columns])


def export_inspection_clocks(run, path):
    result = run['result']
    if 'clocks' not in ((result.get('mission') or {}).get('planned') or {}):
        raise ValueError('本实验没有飞行小时检查计时结果。')
    columns=['asset','rule','initial_hours','flown_hours','hours_since_check','interval_hours','completed_checks','due','overrun_hours']
    with open(path,'w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['run_id','model_hash','seed','engine','replication']+columns)
        for i,rep in enumerate(result['replication_results'],1):
            for clock in rep['mission']['planned']['clocks']:
                writer.writerow([run['id'],run['model_hash'],result['seed'],result['engine'],i]+[clock[k] for k in columns])


def export_aging(run, path, events=False):
    result = run['result']
    if 'aging' not in result:
        raise ValueError('本实验没有部件年龄结果。')
    kind = 'events' if events else 'instances'
    columns = (['time', 'part', 'iid', 'event', 'age_before', 'age_after', 'lifetime_hours', 'repair']
               if events else ['part', 'iid', 'parent', 'age', 'lifetime_hours', 'broken', 'location', 'site'])
    with open(path, 'w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['run_id', 'model_hash', 'seed', 'engine', 'replication', 'truncated'] + columns)
        for index, rep in enumerate(result['replication_results'], 1):
            aging = rep['aging']
            for row in aging[kind]:
                writer.writerow([run['id'], run['model_hash'], result['seed'], result['engine'],
                                 index, aging[kind + '_truncated']] + [row[k] for k in columns])
