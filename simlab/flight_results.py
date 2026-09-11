"""Flight assessment presentation and lossless native CSV exports."""
import csv
import json

REASONS = {'not_started':'尚未起飞', 'awaiting_success_point':'尚未到成功点',
           'success_point_reached':'已达到成功点', 'aborted_before_success_point':'成功点前中止',
           'cancelled_unready':'就绪飞机不足，取消'}
PHASES = {'OUT':'出航', 'ON_STATION':'任务区', 'BACK':'返航', 'LANDED':'计划落地'}
STATUSES = {'scheduled':'待执行','launched':'飞行中','completed':'完整完成','aborted':'中止','cancelled':'取消'}
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
        columns+=['flight_status','members','launched_at','ended_at','landed_at','abort_phase']+SUCCESS_FIELDS+PHASE_FIELDS
        rows=[(i,t) for i,r in enumerate(result['replication_results'],1) for t in r['mission']['tasks']]
    else:
        columns+=['full_window_rate']
        if 'minimum_rate' in mission:
            columns+=['minimum','priority','relief_hours','tolerance_hours','minimum_rate','qualified_rate','below_hours','longest_below_hours']
        if mission.get('flight'):
            columns+=['flight_prep_hours','out_fraction','return_fraction','success_fraction','success_point',
                      'started_rate','success_rate','successful_aircraft_sorties','completed_rate','aborted_rate','cancelled_rate']+PHASE_FIELDS
        rows=[('',dict(t,**{k+'_rate':v for k,v in t.get('flight_rates',{}).items()})) for t in mission['tasks']]
    with open(path,'w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['run_id','model_hash','seed','engine','replication']+columns)
        for replication,t in rows:
            values=[t.get(k) for k in columns]
            values=[json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for v in values]
            writer.writerow([run['id'],run['model_hash'],result['seed'],result['engine'],replication]+values)
