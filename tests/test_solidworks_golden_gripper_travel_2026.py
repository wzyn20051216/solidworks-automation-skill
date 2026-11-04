"""@brief P0-2.1 离线合成故障；不得计入真实 CAD 或复制到真机证据目录。"""
import copy
import csv
import itertools
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import solidworks_golden_gripper_travel_2026 as case
import golden_workflow_harness as harness
from golden_workflow_support import evidence_paths,load_runtime_config


def snapshot(output,left=-40,right=22):
    """@brief 明确离线构造的几何/组件/配合数据，仅测试验收器拒绝错误的能力。"""
    spec=case.load_spec(); poses=case.positions_for(left,right,spec)
    components=[{'role':role,'id':index,'name':role,'path':str(output/'parts'/(i['part']+'.SLDPRT')),'file_exists':True,
        'file_sha256':'OFFLINE','fixed':i['fixed'],'suppression':2,'constrained_status':2 if role.startswith(('slider_','finger_')) else 3,'transform':poses[role]}
        for index,(role,i) in enumerate(spec['instances'].items(),1)]
    ids={c['role']:c['id'] for c in components}; mates=[]; limits={}
    for m in case.mate_contract(spec):
        mates.append({'name':m['name'],'type':m['type'],'suppressed':False,'health':{'health_status':'healthy'},
            'entities':[{'role':r,'component_id':ids[r],'reference_present':True,'entity_params':[0,0,1]} for r in m['roles']]})
        if 'minimum_mm' in m: limits[m['name']]={'advanced':True,'minimum_mm':m['minimum_mm'],'maximum_mm':m['maximum_mm'],
            'distance_mm':(poses[m['roles'][0]][11]-poses[m['roles'][1]][11])*1000}
    bom=[{'item':index,'file':str(output/'parts'/(name+'.SLDPRT')),'quantity':sum(i['part']==name for i in spec['instances'].values()),
          'part_number':'P021-'+name.upper(),'description':case.description(name,spec),'material':p['material'],'excluded_from_bom':False}
         for index,(name,p) in enumerate(spec['parts'].items(),1)]
    pairs=[('base','support_left'),('base','support_right'),('support_left','endplate_left'),('support_right','endplate_right')]
    pairs.extend((a,b) for a in ('endplate_left','endplate_right') for b in ('tie_left','tie_right'))
    for side in ('left','right'):
        pairs.append(('slider_'+side,'finger_'+side))
        pairs.extend((component+'_'+side,'finger_pin_'+side+'_'+suffix) for component in ('slider','finger') for suffix in ('a','b'))
    if left==-58:pairs.append(('slider_left','support_left'))
    if left==-22:pairs.append(('slider_left','base'))
    if right==4:pairs.append(('slider_right','base'))
    if right==40:pairs.append(('slider_right','support_right'))
    return {'rebuild':True,'components':components,'reference_files':sorted({c['path'] for c in components}),'reference_errors':[],
        'mates':{'status':'pass','errors':[],'mates':mates},'limits':limits,'neutral':{'bodies':case.expected_neutral(spec),'errors':[]},'bom':bom,
        'interference':{'status':'pass','interference_count':0,'items':[],'errors':[]},
        'coincidence':{'status':'warn','interference_count':len(pairs),'errors':[],'options':{'treat_coincidence_as_interference':True},
            'items':[{'volume_mm3':0,'components':[{'name':a},{'name':b}]} for a,b in pairs]}}


def request(role,target,actual=None,persist=True):
    """@brief 合成请求保留原始位姿，故障测试会故意破坏这些字段。"""
    t=case.transform(case.load_spec()['instances'][role],target); a=list(t)
    if actual is not None:a[11]=actual/1000
    wanted=next(m for m in case.mate_contract() if m['name']==role+'_travel_limit')
    reference=case.load_spec()['instances'][wanted['roles'][1]]['translation_mm'][2];distance=target-reference
    return {'role':role,'requested_mm':target,'requested_transform':t,'request_readback':list(t),'solver_success':True,'actual_transform':a,
        'positioning_method':'native_limit_mate_current_distance' if persist else 'native_transform_request_no_parameter_commit',
        'mate_update':{'modified':True,'advanced':True,'reference_origin_mm':reference,'distance_mm':distance,
            'minimum_mm':min(wanted['minimum_mm'],distance),'maximum_mm':max(wanted['maximum_mm'],distance)} if persist else {}}


def report_fixture(output,pid=1234,seal=False):
    """@brief 所有非真实字节只写 pytest 临时目录，并由真实 Core 生成终态 trace。"""
    spec=case.load_spec(); native=snapshot(output); parts={}
    for name,p in spec['parts'].items():
        contract=case.part_contract(name,spec); bosses=len(p.get('bosses',[])) or (3 if 'head_diameter' in p else 1)
        cuts=sum(k in p for k in ('guide','tie','finger_holes','mount'))
        snap={'body_count':1,'neutral':{'bodies':[contract],'errors':[]},'geometry':{'envelope_mm':dict(zip(('length','width','height'),contract['size_mm']))},
            'mass':{'errors':[],'density_kg_m3':p['density_kg_m3']},'thickness_mm':p.get('length',p.get('size',[0,0,0])[2]),'material':{'name':p['material'],'database':'OFFLINE'},
            'sketch_quality':{'status':'pass','sketches':[{}]*(bosses+cuts)},'features':{'features':[{'type':'Boss'}]*bosses+[{'type':'Cut'}]*cuts},
            'planes':[{'axis':2,'coordinate_mm':z} for z in (54,62)]}
        parts[name]={'built':copy.deepcopy(snap),'reopened':copy.deepcopy(snap)}
    report={'evidence_origin':'offline_synthetic_fixture','case_id':case.CASE_ID,'output_dir':str(output),'trace_run_id':'offline_'+output.name,
        'backend':'real-solidworks-2026','mock':False,'version':{'year':2026},'process_created_at':'2026-10-26T00:00:00+00:00','processes_before':{},
        'connection':{'process_id':pid,'actual_version':2026,'requested_version':2026,'started_by_cad_studio':True},
        'runtime_config':load_runtime_config(case_id=case.CASE_ID),'runtime_diagnostics':{'status':'pass','blocked_reasons':[],
            'checks':dict.fromkeys(('windows','python_64_bit','pythoncom','win32com','comtypes'),True)},
        'cleanup':{'status':'pass','owned_pid':pid,'remaining_documents':0,'exit_requested':True,'processes_after':{},'errors':[]},
        'parts':parts,'built':copy.deepcopy(native),'reopened':copy.deepcopy(native),'step_reopened':copy.deepcopy(native['neutral']),
        'tolerance_report':case.tolerance_contract(spec),'travel_report':[]}
    for left,right in itertools.product(spec['travel_mm']['slider_left'],spec['travel_mm']['slider_right']):
        report['travel_report'].append({'left_mm':left,'right_mm':right,'solver_success':True,
            'requests':[request('slider_left',left),request('slider_right',right)],'snapshot':snapshot(output,left,right)})
    controls={'overtravel':[],'physical_overtravel':[]}
    for role,b in spec['travel_mm'].items():
        for target,actual in ((b[0]-2,b[0]),(b[-1]+2,b[-1])):
            r=request(role,target,actual,persist=False); r['actual_mm']=actual; r['within_bounds']=True
            r['snapshot']=snapshot(output,actual if role=='slider_left' else -40,actual if role=='slider_right' else 22); controls['overtravel'].append(r)
            physical=snapshot(output,target if role=='slider_left' else -40,target if role=='slider_right' else 22)
            req=request(role,target);physical['limits'][role+'_travel_limit'].update({k:req['mate_update'][k] for k in ('minimum_mm','maximum_mm')})
            stop=('support_left' if target<-58 else 'base') if role=='slider_left' else ('base' if target<4 else 'support_right')
            physical['interference']={'status':'warn','errors':[],'interference_count':1,'items':[{'volume_mm3':100,'components':[{'name':role},{'name':stop}]}]}
            controls['physical_overtravel'].append({'request':req,'snapshot':physical,'restored':True})
    suppressed=copy.deepcopy(native); next(m for m in suppressed['mates']['mates'] if m['name']=='slider_left_travel_limit')['suppressed']=True
    collision=copy.deepcopy(suppressed);collision['interference']={'status':'warn','errors':[],'interference_count':1,
        'items':[{'volume_mm3':100,'components':[{'name':'base'},{'name':'slider_left'}]}]}
    controls.update(suppressed_mate={'snapshot':suppressed,'restored':True},collision={'snapshot':collision,'request':request('slider_left',-3),'restored':True})
    report['native_fault_controls']=controls
    report['review']={'evaluation':{'status':'pass','issues':[],'manual_review_required':True},
        'checks':dict.fromkeys(('rebuild_succeeded','model_available','previews_created','previews_not_blank','expected_outputs_exist','feature_summary_available','feature_errors_absent'),True),
        'previews':[{'path':str(output/'review'/f'{case.CASE_ID}_{v}.bmp'),'exists':True,'likely_blank':False} for v in case.VIEWS]}
    if not seal:return report
    output.mkdir(parents=True)
    report['artifact_baseline']=harness.capture_artifact_baseline(output)
    for key in evidence_paths(case.CASE_ID,report['trace_run_id'])|case.extra_evidence():
        if key.startswith('trace/'):continue
        p=output/key;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('OFFLINE SYNTHETIC FIXTURE',encoding='utf-8')
    for snap in (report['built'],report['reopened']):
        for c in snap['components']:c['file_sha256']=case.sha256_file(Path(c['path']))
    for key in (*case.SNAPSHOT_KEYS,'runtime_config','runtime_diagnostics'):case.write_json(output/f'{key}.json',report[key])
    case.write_json(output/'spec.json',spec);case.write_json(output/f'review/{case.CASE_ID}_review_report.json',report['review'])
    with (output/'bom.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(report['reopened']['bom'][0]));w.writeheader();w.writerows(report['reopened']['bom'])
    harness.adapt_terminal(case,report,output); integrity=harness.seal(case,output,report)
    verdict=harness.verdict(case,report,'blocked',integrity);report.update(acceptance=verdict,acceptance_status=verdict['acceptance_status'],evidence_integrity=integrity)
    assert harness.seal(case,output,report)['status']=='pass'
    return report


def test_p021_contract_and_expected_manual_gate(tmp_path):
    r=report_fixture(tmp_path/'run-01',seal=True)
    assert all(case.workflow_checks(r).values())
    assert r['acceptance_status']=='passed' and r['task_status']=='blocked' and r['manual_review_required'] is True
    assert harness.verdict(case,r,'completed',{'status':'pass','errors':[]})['acceptance_status']=='failed'
    assert len(case.load_spec()['instances'])==17 and len(case.mate_contract())==48


@pytest.mark.parametrize('fault',['missing_limit','wrong_stroke','mate_failed','missing_endplate','wrong_clearance','missing_center_stop','collision',
    'unknown_interference','lost_intended_contact','fake_zero_contact','cached_request','actual_overtravel','unknown_limit','wrong_pin_position',
    'wrong_bom','step_mismatch','cleanup','review_warn','review_fail','masked_collision_control','masked_suppression_control','stale_material','wrong_density','rivet_opposite_side',
    'nominal_limit_expanded','missing_physical_overtravel','wrong_physical_stop','cad_disconnect'])
def test_p021_rejects_faults(tmp_path,fault):
    r=report_fixture(tmp_path/'offline'); row=r['travel_report'][0]; snap=row['snapshot']
    if fault=='missing_limit':snap['mates']['mates'].pop()
    elif fault=='wrong_stroke':r['travel_report'].pop()
    elif fault=='mate_failed':snap['mates']['mates'][0]['health']['health_status']='error'
    elif fault=='missing_endplate':snap['components']=[c for c in snap['components'] if c['role']!='endplate_left']
    elif fault=='wrong_clearance':r['parts']['slider']['reopened']['neutral']['bodies'][0]['cylinders'][0]['diameter_mm']-=.1
    elif fault=='missing_center_stop':r['parts']['base']['reopened']['planes']=[]
    elif fault=='collision':snap['interference']={'status':'warn','errors':[],'interference_count':1,'items':[{'volume_mm3':100}]}
    elif fault=='unknown_interference':snap['interference']['interference_count']=None
    elif fault=='lost_intended_contact':snap['coincidence']['items']=[];snap['coincidence']['interference_count']=0
    elif fault=='fake_zero_contact':snap['coincidence']['status']='blocked'
    elif fault=='cached_request':row['requests'][0]['request_readback'][11]+=.002
    elif fault=='actual_overtravel':r['native_fault_controls']['overtravel'][0]['actual_transform'][11]=-.06
    elif fault=='unknown_limit':next(iter(snap['limits'].values()))['advanced']=False
    elif fault=='wrong_pin_position':next(c for c in snap['components'] if c['role']=='finger_pin_left_a')['transform'][9]+=.01
    elif fault=='rivet_opposite_side':next(c for c in snap['components'] if c['role']=='finger_pin_left_a')['transform'][11]-=.018
    elif fault=='wrong_bom':r['reopened']['bom'][0]['quantity']+=1
    elif fault=='step_mismatch':r['step_reopened']['bodies'][0]['volume_mm3']+=1
    elif fault=='cleanup':r['cleanup']['status']='failed'
    elif fault=='cad_disconnect':r['error']='COM disconnected; remaining document state unknown'
    elif fault=='stale_material':r['parts']['rod']['reopened']['material']['name']='6061-T6 (SS)'
    elif fault=='wrong_density':r['parts']['rod']['reopened']['mass']['density_kg_m3']=1000
    elif fault=='nominal_limit_expanded':snap['limits']['slider_left_travel_limit']['maximum_mm']+=2
    elif fault=='missing_physical_overtravel':r['native_fault_controls']['physical_overtravel'].pop()
    elif fault=='wrong_physical_stop':r['native_fault_controls']['physical_overtravel'][0]['snapshot']['interference']['items'][0]['components'][1]['name']='finger_right'
    elif fault.startswith('review_'):r['review']['evaluation']['status']=fault.split('_')[1]
    elif fault=='masked_collision_control':r['native_fault_controls']['collision']['snapshot']['interference']['interference_count']=0
    else:next(m for m in r['native_fault_controls']['suppressed_mate']['snapshot']['mates']['mates'] if m['name']=='slider_left_travel_limit')['suppressed']=False
    assert harness.verdict(case,r,'blocked',{'status':'pass','errors':[]})['acceptance_status']=='failed'


@pytest.mark.parametrize('artifact',['parts/endplate.SLDPRT','parts/tie_rivet.SLDPRT','travel_report.json','tolerance_report.json'])
def test_p021_evidence_tamper_or_loss(tmp_path,artifact):
    p=tmp_path/'run-01';r=report_fixture(p,seal=True)
    (p/artifact).write_text('TAMPERED',encoding='utf-8');assert harness.inspect_evidence(case,p,r)['status']=='fail'
    (p/artifact).unlink();assert harness.inspect_evidence(case,p,r)['status']=='fail'


def test_p021_cleanup_failure_stops_new_instance(tmp_path,monkeypatch):
    calls=[]
    def run(_case,output,*args):
        calls.append(output);r=report_fixture(output,seal=True);r['cleanup']['status']='failed';return r
    monkeypatch.setattr(harness,'run_once',run)
    assert case.main(['--output',str(tmp_path/'suite'),'--runs','5','--expected-terminal','blocked'])==1
    assert len(calls)==1


def test_p021_fit_is_proposal_with_traceable_limits():
    s=case.load_spec(); f=case.tolerance_contract(s)
    assert f['manufacturing_release'] is False and len(f['fit']['unconfirmed'])>=5
    assert f['diametral_clearance_limits_mm']==pytest.approx([.005,.029])
    assert s['fit']['shaft_limits_mm'][0]<=s['parts']['rod']['diameter']<=s['fit']['shaft_limits_mm'][1]
    assert s['fit']['hole_limits_mm'][0]<=s['guide_hole_diameter_mm']<=s['fit']['hole_limits_mm'][1]
