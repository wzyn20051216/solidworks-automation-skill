"""@brief P0-2 离线合成证据故障注入；不启动 CAD，不计入任何真实验收统计。"""
import copy
import csv
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import solidworks_golden_parallel_gripper_2026 as case
import golden_workflow_harness as harness
from golden_workflow_support import evidence_paths,load_runtime_config


def synthetic_report(output,pid=1234):
    """@brief 构造明确标注为离线测试用途的输入，用于攻击验收判定而非冒充真机。"""
    spec=case.load_spec()
    report={'case_id':case.CASE_ID,'output_dir':str(output),'trace_run_id':'offline_'+output.name,
        'backend':'real-solidworks-2026','mock':False,'version':{'year':2026},
        'connection':{'process_id':pid,'actual_version':2026,'requested_version':2026,'started_by_cad_studio':True},
        'process_created_at':'2026-10-26T00:00:00+00:00','processes_before':{},
        'runtime_config':load_runtime_config(case_id=case.CASE_ID),
        'runtime_diagnostics':{'status':'pass','blocked_reasons':[],
            'checks':dict.fromkeys(('windows','python_64_bit','pythoncom','win32com','comtypes'),True)},
        'cleanup':{'status':'pass','owned_pid':pid,'remaining_documents':0,'exit_requested':True,'processes_after':{},'errors':[]}}
    parts={}
    for name,p in spec['parts'].items():
        volume,center=case.part_properties(p)
        dims=p.get('size_mm',[p.get('diameter_mm'),p.get('diameter_mm'),p.get('length_mm')])
        holes=[{'diameter_mm':p['hole_diameter_mm'],'position_mm':[*xy,0],'axial_length_mm':dims[2]} for xy in p.get('hole_centers_mm',[])]
        snap={'body_count':1,'geometry':{'errors':[],'envelope_mm':dict(zip(('length','width','height'),dims)),'holes':holes},
            'mass':{'volume_mm3':volume,'errors':[],'density_kg_m3':2700},'thickness_mm':dims[2],
            'material':{'name':spec['material_entry'],'database':'offline-fixture'},
            'sketch_quality':{'status':'pass','sketches':[{}]*(2 if holes else 1)},
            'features':{'features':[{'type':'Boss'}]+([{'type':'Cut'}] if holes else [])},
            'circular_edges':[[*xy,z,p['hole_diameter_mm']/2,True] for xy in p.get('hole_centers_mm',[]) for z in (0,dims[2])]}
        parts[name]={'built':copy.deepcopy(snap),'reopened':copy.deepcopy(snap)}
    report['parts']=parts
    native={'rebuild':True,'components':[],'reference_errors':[],
        'mates':{'status':'pass','errors':[],'mates':[]},'interference':{'status':'pass','interference_count':0,'items':[],'errors':[]},
        'neutral':{'bodies':[],'errors':[]},'bom':[]}
    for index,(role,instance) in enumerate(spec['instances'].items(),1):
        part=spec['parts'][instance['part']]; moving=role.startswith(('slider_','finger_'))
        dofs={'status':'pass','errors':[],'return_code':0,
            'rotation_axis_1':{'state':0},'rotation_axis_2':{'state':0},
            'translation_axis_1':{'state':3 if moving else 0,'vector':[0,0,1] if moving else None},'translation_axis_2':{'state':0}}
        transform=[1,0,0,0,1,0,0,0,1,*[v/1000 for v in instance['translation_mm']],1,0,0,0]
        path=str(output/'parts'/(instance['part']+'.SLDPRT'))
        native['components'].append({'id':index,'role':role,'name':role,'path':path,'file_exists':True,'file_sha256':'offline-placeholder',
            'fixed':instance['fixed'],'suppression':2,'constrained_status':2 if moving else 3,'transform':transform,'dofs':dofs})
        volume,center=case.part_properties(part)
        cylinders=[]
        for xy in part.get('hole_centers_mm',[[0,0]] if 'diameter_mm' in part else []):
            diameter=part.get('hole_diameter_mm',part.get('diameter_mm'))
            length=part.get('size_mm',[0,0,part.get('length_mm')])[2]
            cylinders.append({'diameter_mm':diameter,'origin_mm':[xy[0]+instance['translation_mm'][0],xy[1],0],
                'axis':[0,0,1],'internal':bool(part.get('hole_centers_mm')),'area_mm2':math_pi()*diameter*length})
        native['neutral']['bodies'].append({'volume_mm3':volume,'center_mm':[a+b for a,b in zip(center,instance['translation_mm'])],'cylinders':cylinders})
    native['reference_files']=sorted({c['path'] for c in native['components']})
    ids={c['role']:c['id'] for c in native['components']}
    for mate in case.mate_contract():
        native['mates']['mates'].append({'name':mate['name'],'type':mate['type'],'suppressed':False,
            'health':{'health_status':'healthy'},'lock_rotation':mate.get('lock_rotation',False),
            'entities':[{'role':r,'component_id':ids[r],'reference_present':True,'reference_type':0,'entity_params':[0,0,1]} for r in mate['roles']]})
    for name in spec['parts']:
        native['bom'].append({'item':len(native['bom'])+1,'part_number':'P0-2-'+name.upper(),'description':case.part_description(name,spec['parts'][name]),'material':'6061-T6',
            'quantity':sum(i['part']==name for i in spec['instances'].values()),'file':str(output/'parts'/f'{name}.SLDPRT'),
            'configuration':'Default','component':name,'excluded_from_bom':False})
    report.update(built=copy.deepcopy(native),reopened=copy.deepcopy(native),step_reopened=copy.deepcopy(native['neutral']))
    original={c['role']:c['transform'] for c in native['components']}
    probes=[]
    for role in ('slider_left','slider_right'):
        for mode in ('tz_negative','tz_positive','tx','ty','rx','ry','rz'):
            after=copy.deepcopy(original)
            if mode.startswith('tz_'):
                for key in (role,role.replace('slider','finger')): after[key][11]+=(-1 if mode=='tz_negative' else 1)*.002
            requested=case.probe_target(original[role],mode,spec)
            probes.append({'role':role,'mode':mode,'solver_success':True,'restored':True,
                'before':copy.deepcopy(original),'requested':requested,'transform_readback':copy.deepcopy(requested),
                'after':after,'end':copy.deepcopy(original)})
    report['motion_probes']=probes
    collision=copy.deepcopy(native)
    collision['interference']={'status':'warn','interference_count':1,'items':[{'volume_mm3':10}],'errors':[]}
    suppressed=copy.deepcopy(native)
    next(m for m in suppressed['mates']['mates'] if m['name']=='slider_left_guide')['suppressed']=True
    report['native_fault_controls']={'interference':{'solver_success':True,'restored':True,'snapshot':collision},
                                     'suppressed_mate':{'restored':True,'snapshot':suppressed}}
    report['review']={'evaluation':{'status':'pass','issues':[],'manual_review_required':True},
        'checks':dict.fromkeys(('rebuild_succeeded','model_available','previews_created','previews_not_blank','expected_outputs_exist','feature_summary_available','feature_errors_absent'),True),
        'previews':[{'path':str(output/'review'/f'{case.CASE_ID}_{v}.bmp'),'exists':True,'likely_blank':False,'width':1600,'height':1000} for v in case.VIEWS]}
    return report


def math_pi():
    """@brief 离线几何夹具使用标准数学常数。"""
    import math
    return math.pi


def evidence_fixture(output,pid=1234):
    """@brief 写入合成测试文件；这些字节不是 CAD，不得放入真实运行证据目录。"""
    output.mkdir(parents=True)
    report=synthetic_report(output,pid)
    report['artifact_baseline']=harness.capture_artifact_baseline(output)
    for key in evidence_paths(case.CASE_ID,report['trace_run_id']) | case.extra_evidence():
        if key.startswith('trace/'):
            continue  # trace 必须由真实 Core 终态适配生成，不能预填占位文本。
        path=output/key; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('OFFLINE SYNTHETIC FIXTURE',encoding='utf-8')
    for snapshot in (report['built'],report['reopened']):
        for component in snapshot['components']: component['file_sha256']=case.sha256_file(Path(component['path']))
    for key in case.SNAPSHOT_KEYS: case.write_json(output/f'{key}.json',report[key])
    case.write_json(output/'runtime_config.json',report['runtime_config'])
    case.write_json(output/'runtime_diagnostics.json',report['runtime_diagnostics'])
    case.write_json(output/'spec.json',case.load_spec())
    case.write_json(output/f'review/{case.CASE_ID}_review_report.json',report['review'])
    rows=report['reopened']['bom']
    with (output/'bom.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    harness.adapt_terminal(case,report,output)
    integrity=harness.seal(case,output,report)
    result=harness.verdict(case,report,'blocked',integrity)
    report.update(acceptance_status=result['acceptance_status'],acceptance=result,evidence_integrity=integrity)
    assert harness.seal(case,output,report)['status']=='pass'
    return report


def test_offline_expected_block_never_becomes_completion(tmp_path):
    report=evidence_fixture(tmp_path/'run-01')
    assert report['task_status']=='blocked' and report['acceptance_status']=='passed' and report['manual_review_required'] is True
    assert harness.verdict(case,report,'completed',harness.inspect_evidence(case,tmp_path/'run-01',report))['acceptance_status']=='failed'


@pytest.mark.parametrize('fault',['missing_component','wrong_position','suppressed_mate','failed_mate','missing_reference','interference',
    'wrong_bom','step_mismatch','unknown_dof','extra_rotation','failed_rebuild','review_fail','review_warn','cleanup',
    'motion_cached_success','no_real_interference_detection','wrong_mate_entity'])
def test_expected_block_rejects_all_assembly_faults(tmp_path,fault):
    report=evidence_fixture(tmp_path/'run-01')
    native=report['reopened']
    if fault=='missing_component': native['components'].pop()
    elif fault=='wrong_position': native['components'][1]['transform'][9]+=.01
    elif fault=='suppressed_mate': native['mates']['mates'][0]['suppressed']=True
    elif fault=='failed_mate': native['mates']['mates'][0]['health']['health_status']='error'
    elif fault=='missing_reference': native['components'][0]['file_exists']=False
    elif fault=='interference': native['interference']={'status':'warn','interference_count':1,'items':[{'volume_mm3':100}],'errors':[]}
    elif fault=='wrong_bom': native['bom'][0]['quantity']+=1
    elif fault=='step_mismatch': report['step_reopened']['bodies'][0]['volume_mm3']+=1
    elif fault=='unknown_dof': native['components'][5]['dofs']['status']='blocked'
    elif fault=='extra_rotation': native['components'][5]['dofs']['rotation_axis_1']['state']=3
    elif fault=='failed_rebuild': native['rebuild']=False
    elif fault.startswith('review_'): report['review']['evaluation']['status']=fault.split('_')[1]
    elif fault=='cleanup': report['cleanup']['status']='failed'
    elif fault=='motion_cached_success': report['motion_probes'][0]['after']['slider_left'][9]+=.01
    elif fault=='wrong_mate_entity': native['mates']['mates'][0]['entities'][0]['component_id']=999
    else: report['native_fault_controls']['interference']['snapshot']['interference']['interference_count']=0
    result=harness.verdict(case,report,'blocked',{'status':'pass','errors':[]})
    assert result['acceptance_status']=='failed' and result['failed_checks']


@pytest.mark.parametrize('artifact',['parts/rod.SLDPRT',case.CASE_ID+'.SLDASM','bom.csv','reopened.json'])
def test_missing_artifact_and_tampering_remain_failures(tmp_path,artifact):
    report=evidence_fixture(tmp_path/'run-01')
    path=tmp_path/'run-01'/artifact
    path.write_text('TAMPERED',encoding='utf-8')
    assert harness.inspect_evidence(case,tmp_path/'run-01',report)['status']=='fail'
    path.unlink()
    assert harness.inspect_evidence(case,tmp_path/'run-01',report)['status']=='fail'


def test_five_unique_real_instances_required(tmp_path):
    reports=[evidence_fixture(tmp_path/f'run-{i:02d}',pid=1000+i) for i in range(1,6)]
    assert harness.summarize(case,reports,'blocked')['acceptance_status']=='passed'
    assert harness.summarize(case,reports[:4],'blocked')['acceptance_status']=='failed'
    assert harness.summarize(case,[reports[0]]*5,'blocked')['acceptance_status']=='failed'


@pytest.mark.parametrize('fault',['wrong_position','cleanup','review_fail'])
def test_cli_fault_exit_code(tmp_path,monkeypatch,fault):
    def failed_case(_case,output,*args):
        report=evidence_fixture(output)
        if fault=='wrong_position': report['reopened']['components'][0]['transform'][9]+=.1
        elif fault=='cleanup': report['cleanup']['status']='failed'
        else: report['review']['evaluation']['status']='fail'
        return report
    monkeypatch.setattr(harness,'run_once',failed_case)
    assert case.main(['--output',str(tmp_path/'suite'),'--runs','5','--expected-terminal','blocked'])==1


def test_assembly_config_cannot_weaken_mounting_case(tmp_path):
    path=tmp_path/'config.json'; (tmp_path/'template.asmdot').write_text('OFFLINE',encoding='utf-8')
    path.write_text('{"assembly_template":"template.asmdot"}',encoding='utf-8')
    assert load_runtime_config(path,case.CASE_ID)['assembly_template']==str(tmp_path/'template.asmdot')
    with pytest.raises(ValueError): load_runtime_config(path)


@pytest.mark.parametrize('fault',['core_terminal','trace_run','bom_csv','ledger'])
def test_rehash_cannot_hide_wrong_terminal_trace_or_delivery(tmp_path,fault):
    """@brief 改写并重新计算清单仍必须检查语义，不能仅验证哈希。"""
    output=tmp_path/'run-01'; report=evidence_fixture(output)
    if fault=='core_terminal':
        report['execution_core']['status']='completed'
        assert harness.verdict(case,report,'blocked',{'status':'pass','errors':[]})['acceptance_status']=='failed'
    elif fault=='trace_run':
        path=output/'trace/events'/f"{report['trace_run_id']}.jsonl"
        events=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        events[0]['run_id']='foreign_run'
        path.write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf-8')
        assert harness.seal(case,output,report)['status']=='fail'
    elif fault=='bom_csv':
        (output/'bom.csv').write_text('quantity\n99\n',encoding='utf-8')
        assert harness.seal(case,output,report)['status']=='fail'
    else:
        path=output/'ledgers'/f'{output.name}.ledger.json'
        ledger=json.loads(path.read_text(encoding='utf-8'));ledger['runId']='foreign_run'
        case.write_json(path,ledger)
        manifest_path=output/'sha256.json'; manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        for row in manifest:
            if row['path'].startswith('ledgers/'):
                row.update(sha256=case.sha256_file(path),size_bytes=path.stat().st_size)
        case.write_json(manifest_path,manifest)
        assert harness.inspect_evidence(case,output,report)['status']=='fail'


def test_expected_block_requires_five_and_preserves_existing_outputs(tmp_path):
    """@brief 参数门禁在任何 CAD 副作用前执行；已有目录不覆盖。"""
    with pytest.raises(SystemExit): case.main(['--output',str(tmp_path/'new'),'--expected-terminal','blocked'])
    assert not (tmp_path/'new').exists()
    (tmp_path/'existing').mkdir()
    with pytest.raises(FileExistsError): case.main(['--output',str(tmp_path/'existing')])


def test_native_transform_requires_double_array_and_exact_readback():
    """@brief 回归首轮真实 Z 偏移空写入；编组类型或回读不符必须拒绝。"""
    from scripts.sw_assembly import create_math_transform
    import pythoncom
    class Math:
        def _FlagAsMethod(self,name):
            assert name=='CreateTransform'
            self.flagged=True
        def CreateTransform(self, argument):
            assert self.flagged is True
            assert argument.varianttype==pythoncom.VT_ARRAY|pythoncom.VT_R8
            return type('Transform',(),{'ArrayData':argument.value})()
    sw=type('SW',(),{'GetMathUtility':lambda _:Math()})()
    values=[1,0,0,0,1,0,0,0,1,0,0,-.07,1,0,0,0]
    assert list(create_math_transform(sw,values).ArrayData)==values
    sw.GetMathUtility=lambda:type('BadMath',(),{'CreateTransform':lambda _,arg:type('T',(),{'ArrayData':[0]*16})()})()
    with pytest.raises(RuntimeError): create_math_transform(sw,values)


def test_cached_success_cannot_replace_actual_six_axis_request(tmp_path):
    """@brief 空写入、未发出旋转请求或返回错误姿态都不能算约束方向验证。"""
    report=synthetic_report(tmp_path/'offline')
    probes=report['motion_probes']
    assert case.motion_evidence_valid(probes,case.load_spec())
    probes[2]['transform_readback']=probes[2]['before']['slider_left']
    assert not case.motion_evidence_valid(probes,case.load_spec())


def test_projection_may_slide_z_but_cannot_admit_rotation(tmp_path):
    """@brief 回归真实求解器投影：允许自由轴移动，严格拒绝已发现的额外绕 Z 转动。"""
    report=synthetic_report(tmp_path/'offline')
    probes=report['motion_probes']
    ry=next(p for p in probes if p['role']=='slider_left' and p['mode']=='ry')
    for role in ('slider_left','finger_left'): ry['after'][role][11]-=.0009
    assert case.motion_evidence_valid(probes,case.load_spec())
    rz=next(p for p in probes if p['role']=='slider_left' and p['mode']=='rz')
    for role in ('slider_left','finger_left'): rz['after'][role][:9]=[.99875026,-.04997917,0,.04997917,.99875026,0,0,0,1]
    assert not case.motion_evidence_valid(probes,case.load_spec())


def test_suite_does_not_launch_another_instance_after_cleanup_failure(tmp_path,monkeypatch):
    """@brief 即使缓存验收写着 passed，异常清理也必须停止后续实例启动。"""
    calls=[]
    def failed_case(_case,output,*args):
        calls.append(output)
        report=evidence_fixture(output)
        report['cleanup']['status']='failed'
        return report
    monkeypatch.setattr(harness,'run_once',failed_case)
    assert case.main(['--output',str(tmp_path/'suite'),'--runs','5','--expected-terminal','blocked'])==1
    assert len(calls)==1
