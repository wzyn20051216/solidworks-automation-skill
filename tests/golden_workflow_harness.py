"""@brief P0-2 用例级执行壳；复用 P0-1.2 契约，不改变其已验证安装板流程。"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import traceback
import uuid

from solidworks_golden_mounting_bracket_2026 import (ROOT, write_json, sha256_file, write_artifact_ledger,
                                                     execute_with_core, MANUAL_REVIEW_BLOCK)
from golden_workflow_support import (CASE_REGISTRY, evidence_paths, safe_output_path, load_runtime_config,
                                     diagnose_runtime, valid_process_identity, validate_core_trace)


def checks_for(case, report):
    """@brief 用例规则与真实实例、环境和清理共同判定；任何未知都不能通过。"""
    connection, cleanup = report.get('connection', {}), report.get('cleanup', {})
    pid = connection.get('process_id')
    diagnostics = report.get('runtime_diagnostics', {})
    checks = {'execution_error_free': not report.get('error'),
        'runtime': diagnostics.get('status') == 'pass' and diagnostics.get('blocked_reasons') == []
            and all(diagnostics.get('checks', {}).get(k) is True for k in ('windows','python_64_bit','pythoncom','win32com','comtypes')),
        'real_owned_2026': report.get('backend') == 'real-solidworks-2026' and report.get('mock') is False
            and report.get('version', {}).get('year') == 2026 and connection.get('actual_version') == 2026
            and connection.get('requested_version') == 2026 and connection.get('started_by_cad_studio') is True
            and valid_process_identity(pid, report.get('process_created_at')) and report.get('processes_before') == {},
        'safe_cleanup': cleanup.get('status') == 'pass' and cleanup.get('owned_pid') == pid
            and cleanup.get('remaining_documents') == 0 and cleanup.get('exit_requested') is True
            and cleanup.get('processes_after') == {} and cleanup.get('errors') == []}
    try:
        checks.update(case.workflow_checks(report))
    except (KeyError, TypeError, ValueError, IndexError, ArithmeticError):
        checks['case_evidence_readable'] = False
    return checks


def adapt_terminal(case, report, output):
    """@brief 仅向 Core 适配已结束的 CAD 事实，不冒充 Core 调度装配过程。"""
    checks = checks_for(case, report)
    evaluation = report.get('review', {}).get('evaluation', {})
    raw = {'status':'ok' if all(checks.values()) else 'blocked' if 'BLOCKED:' in report.get('error','') else 'failed',
           'manual_review_required':evaluation.get('manual_review_required', True)}
    if raw['status'] != 'blocked':
        raw['success'] = all(checks.values())
    core = execute_with_core(handler=lambda _:raw, run_id=report['trace_run_id'], tool_name='golden_terminal_adapter',
        capability_id='assembly_and_mates', requires_review=True,
        reviewer_result={'status':evaluation.get('status'), 'manual_review_required':evaluation.get('manual_review_required',True),
                         'evidence':[{'path':report.get('review_path'),'scope':'original_review'}]},
        trace_dir=output/'trace').to_dict()
    expected = core['status'] == 'blocked' and all(checks.values()) and evaluation.get('manual_review_required') is True
    report.update(execution_core=core, core_scope='terminal_adaptation_only', workflow_checks=checks,
        status=core['status'], task_status=core['status'], manual_review_required=evaluation.get('manual_review_required'),
        blocking_reasons=[MANUAL_REVIEW_BLOCK] if expected else [k for k,v in checks.items() if not v])


def inspect_evidence(case, output, report):
    """@brief 回读全覆盖哈希、Ledger、快照、原始 Review 及实际 Core trace。"""
    try:
        output = Path(output)
        safe_output_path(output, output)
        load = lambda p: json.loads(safe_output_path(output,p).read_text(encoding='utf-8'))
        entries = {}
        for item in load(output/'sha256.json'):
            path = safe_output_path(output, output/item['path'])
            key = path.relative_to(output).as_posix()
            if key in entries or not path.is_file() or path.stat().st_size <= 0:
                raise ValueError('MISSING_DUPLICATE_OR_EMPTY_ARTIFACT')
            if item['size_bytes'] != path.stat().st_size or item['sha256'] != sha256_file(path):
                raise ValueError('ARTIFACT_HASH_MISMATCH')
            entries[key] = item
        actual = set()
        for path in output.rglob('*'):
            safe_output_path(output,path)
            if path.is_file() and path != output/'sha256.json':
                actual.add(path.relative_to(output).as_posix())
        ledger_key = f'ledgers/{output.name}.ledger.json'
        required = evidence_paths(case.CASE_ID,report['trace_run_id']) | case.extra_evidence() | {ledger_key}
        if set(entries) != actual or not required.issubset(entries):
            raise ValueError('EVIDENCE_COVERAGE_INCOMPLETE')
        for name in ('report','runtime_config','runtime_diagnostics',*case.SNAPSHOT_KEYS):
            if load(output/f'{name}.json') != (report if name == 'report' else report.get(name)):
                raise ValueError('EVIDENCE_CONTENT_MISMATCH: '+name)
        basename = CASE_REGISTRY[case.CASE_ID]['basename']
        if load(output/f'review/{basename}_review_report.json') != report.get('review'):
            raise ValueError('REVIEW_CONTENT_MISMATCH')
        ledger = load(output/ledger_key)
        if (ledger['executor'] != 'solidworks-com-pywin32' or ledger['status'] != report['task_status']
            or ledger['jobId'] != output.name or ledger['runId'] != report['trace_run_id']
            or ledger['verification'] != [report['execution_core']]):
            raise ValueError('LEDGER_PROVENANCE_MISMATCH')
        paths = set()
        for item in ledger['artifacts']:
            path = safe_output_path(output,Path(item['path']))
            key = path.relative_to(output).as_posix()
            if (key in paths or key not in entries or item.get('producedThisRun') is not True or not item['exists']
                or item['isDirectory'] or item['sha256'] != entries[key]['sha256'] or item['sizeBytes'] != entries[key]['size_bytes']):
                raise ValueError('LEDGER_ARTIFACT_INVALID')
            paths.add(key)
        if paths != set(entries)-{ledger_key}:
            raise ValueError('LEDGER_COVERAGE_INCOMPLETE')
        events = [json.loads(s) for s in (output/'trace/events'/f"{report['trace_run_id']}.jsonl").read_text(encoding='utf-8').splitlines()]
        validate_core_trace(events,report,report['trace_run_id'])
        case.inspect_delivery(output, report)
        return {'status':'pass','errors':[]}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error:
        return {'status':'fail','errors':[f'{type(error).__name__}: {error}']}


def seal(case, output, report):
    """@brief 写入报告及产物账本；报告/清单的循环引用按 P0-1.2 规则排除。"""
    for path in [output, output/'report.json', output/'sha256.json', output/'ledgers'/f'{output.name}.ledger.json',*output.rglob('*')]:
        safe_output_path(output,path)
    write_json(output/'report.json',report)
    ledger = output/'ledgers'/f'{output.name}.ledger.json'
    files = [p for p in output.rglob('*') if p.is_file() and p not in {output/'sha256.json',ledger}]
    write_artifact_ledger(output,{'id':output.name,'runId':report['trace_run_id'],'executor':'solidworks-com-pywin32',
        'status':report['task_status'],'cwd':str(output)}, {'artifacts':[{'kind':p.suffix.lstrip('.'),'path':str(p)} for p in files],
        'artifactBaseline':{'schemaVersion':'2.0','entries':{},'complete':True,'truncated':False,'scannedCount':0,'errors':[]},
        'verification':[report['execution_core']]})
    files.append(ledger)
    write_json(output/'sha256.json',[{'path':p.relative_to(output).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha256_file(p)} for p in sorted(files)])
    return inspect_evidence(case,output,report)


def verdict(case, report, expected, integrity):
    """@brief 显式预期人工阻塞可验收，但任何其它错误均不放行。"""
    checks = checks_for(case,report)
    core = report.get('execution_core',{})
    verification = core.get('verification') or {}
    checks.update(evidence_integrity=integrity.get('status')=='pass' and integrity.get('errors')==[],
        terminal_consistent=report.get('task_status')==expected and report.get('status')==expected and core.get('status')==expected,
        core_execution=core.get('execution',{}).get('success') is True and core.get('exception') is None,
        core_verification=verification.get('status')=='PASS' and verification.get('error_code') is None and core.get('requires_review') is True,
        core_scope=report.get('core_scope')=='terminal_adaptation_only')
    if expected == 'blocked':
        checks['only_expected_manual_block'] = (report.get('manual_review_required') is True and verification.get('manual_review_required') is True
            and report.get('review',{}).get('evaluation',{}).get('manual_review_required') is True
            and report.get('blocking_reasons')==[MANUAL_REVIEW_BLOCK] and core.get('step',{}).get('status')=='blocked'
            and (core.get('recovery') or {}).get('decision')=='user_action_required')
    else:
        checks['no_manual_requirement'] = report.get('manual_review_required') is False and verification.get('manual_review_required') is False
    return {'acceptance_status':'passed' if all(checks.values()) else 'failed','expected_terminal':expected,
            'checks':checks,'failed_checks':[k for k,v in checks.items() if not v]}


def run_once(case, output, expected, runtime_config=None):
    """@brief 每轮独立目录并保留全部失败；CAD 生命周期由具体用例安全拥有。"""
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    report={'schema_version':'1.2','case_id':case.CASE_ID,'backend':'real-solidworks-2026','mock':False,
        'task_status':'failed','status':'failed','acceptance_status':'failed','expected_terminal':expected,
        'trace_run_id':'golden_'+uuid.uuid4().hex,'generated_at':datetime.now(timezone.utc).isoformat(),'output_dir':str(output)}
    with (output/'run.log').open('w',encoding='utf-8',buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
        try:
            report['source_sha']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
            try:
                report['runtime_config']=load_runtime_config(runtime_config,case.CASE_ID)
            except (OSError,ValueError,TypeError) as error:
                raise RuntimeError(f'BLOCKED: 运行配置不可用: {error}') from error
            report['runtime_diagnostics']=diagnose_runtime(report['runtime_config'])
            if report['runtime_diagnostics']['status']!='pass':
                raise RuntimeError('BLOCKED: 运行时诊断失败')
            for command,name in ((['scripts/sw_preflight.py'],'preflight'),(['scripts/cad_studio.py','doctor'],'doctor')):
                result=subprocess.run([sys.executable,'-X','utf8',*command],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
                (output/f'{name}.log').write_text(result.stdout+result.stderr,encoding='utf-8')
                if result.returncode:
                    raise RuntimeError('BLOCKED: '+name+' 失败')
                if name=='doctor': report['doctor']=json.loads(result.stdout)
            case.run_cad(output,report)
        except Exception:
            report['error']=traceback.format_exc()
            print(report['error'],flush=True)
        report.setdefault('runtime_config',{})
        report.setdefault('runtime_diagnostics',{'status':'blocked','blocked_reasons':['not_executed']})
        for name in ('runtime_config','runtime_diagnostics'):
            write_json(output/f'{name}.json',report[name])
        adapt_terminal(case,report,output)
        print(json.dumps({'task_status':report['task_status'],'blocking_reasons':report['blocking_reasons'],
                          'cleanup':report.get('cleanup')},ensure_ascii=False),flush=True)
    try:
        integrity=seal(case,output,report)
        result=verdict(case,report,expected,integrity)
        report.update(evidence_integrity=integrity,acceptance=result,acceptance_status=result['acceptance_status'])
        final=seal(case,output,report)
        if final['status']!='pass': raise ValueError(str(final))
    except Exception:
        report.update(acceptance_status='failed',evidence_integrity={'status':'fail','errors':[traceback.format_exc()]})
        if 'acceptance' in report: report['acceptance']['acceptance_status']='failed'
        try: write_json(safe_output_path(output,output/'report.json'),report)
        except ValueError: write_json(safe_output_path(output,output/'finalization_error.json'),report)
    print(f"{output.name}: acceptance_status={report['acceptance_status']}, task_status={report['task_status']}",flush=True)
    return report


def summarize(case,reports,expected):
    """@brief 套件再次回读证据，不能重复同一实例、trace 或用不足五轮冒充验收。"""
    rows=[]
    for report in reports:
        result=verdict(case,report,expected,inspect_evidence(case,Path(report['output_dir']),report))
        if report.get('acceptance_status') != result['acceptance_status']:
            result['acceptance_status']='failed'
            result['failed_checks'].append('stored_acceptance_mismatch')
        rows.append({'report':str(Path(report['output_dir'])/'report.json'),'task_status':report.get('task_status'),**result})
    identities=[(r.get('connection',{}).get('process_id'),r.get('process_created_at')) for r in reports]
    traces=[r.get('trace_run_id') for r in reports]
    checks={'all_accepted':bool(rows) and all(r['acceptance_status']=='passed' for r in rows),
        'independent_instances':len(set(identities))==len(identities), 'independent_traces':len(set(traces))==len(traces),
        'five_runs':expected!='blocked' or len(rows)==5}
    tasks=[r['task_status'] for r in rows]
    task='failed' if not tasks or any(t not in ('completed','blocked') for t in tasks) else 'blocked' if 'blocked' in tasks else 'completed'
    return {'case_id':case.CASE_ID,'backend':'real-solidworks-2026','mock':False,'task_status':task,
        'acceptance_status':'passed' if all(checks.values()) else 'failed','expected_terminal':expected,'suite_checks':checks,'runs':rows,
        'metrics':{'run_count':len(rows),'test_acceptance_count':sum(r['acceptance_status']=='passed' for r in rows),
            'task_completion_count':tasks.count('completed'),'false_completion_count':sum(
                (r.get('task_status')=='completed' or r.get('execution_core',{}).get('status')=='completed')
                and (r.get('manual_review_required') is not False or row['acceptance_status']!='passed') for r,row in zip(reports,rows)),
            'cleanup_success_count':sum(checks_for(case,r)['safe_cleanup'] for r in reports)}}


def main(case,argv=None):
    """@brief 严格默认完成模式，显式 blocked 必须五轮且逐轮验收全部满足。"""
    parser=argparse.ArgumentParser(description=case.__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--runs',type=int,choices=range(1,6),default=1)
    parser.add_argument('--expected-terminal',choices=('completed','blocked'),default='completed')
    parser.add_argument('--runtime-config',type=Path)
    args=parser.parse_args(argv)
    if args.expected_terminal=='blocked' and args.runs!=5: parser.error('预期 blocked 必须五轮')
    args.output.mkdir(parents=True,exist_ok=False)
    reports=[]
    for i in range(1,args.runs+1):
        report=run_once(case,args.output/f'run-{i:02d}',args.expected_terminal,args.runtime_config)
        reports.append(report)
        # 包括异常清理在内的失败发生后不再启动实例；不足五轮的套件仍明确失败。
        current=verdict(case,report,args.expected_terminal,inspect_evidence(case,Path(report['output_dir']),report))
        if current['acceptance_status']!='passed':
            break
    result=summarize(case,reports,args.expected_terminal)
    write_json(args.output/'summary.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return 0 if result['acceptance_status']=='passed' else 1
