"""性能测试执行引擎：以子进程方式运行 Locust，监控进度并聚合落库。"""

import logging
import os
import shutil
import subprocess
import tempfile
import time

from .push import push_execution_update
from .services import (
    calc_peak_rps,
    infer_host,
    parse_locust_history_csv,
    parse_locust_stats_csv,
    render_locustfile,
)

logger = logging.getLogger(__name__)

LOCUST_BIN = os.environ.get('LOCUST_BIN', 'locust')
_POLL_INTERVAL = 1.0
_TIMEOUT_BUFFER = 120


def run_perf_test(execution_id):
    """执行一次压测，编排：准备脚本 → 起 Locust 子进程 → 监控 → 落库。"""
    from .models import PerfTestExecution

    execution = PerfTestExecution.objects.get(id=execution_id)
    try:
        ctx = _load_execution_context(execution)
        if ctx.get('node'):
            execution.node = ctx['node']
            execution.save(update_fields=['node'])
        workdir = _prepare_workdir(execution_id, ctx['locustfile'])
        cmd = _build_command(
            workdir, ctx['host'], ctx['users'], ctx['spawn_rate'], ctx['duration']
        )
        _run_and_monitor(execution, workdir, cmd, ctx['duration'])
        report = _save_report(execution, workdir)
        execution.complete()
        _dispatch_diagnosis(report)
        return {'status': 'completed'}
    except Exception as exc:
        logger.exception(f"压测执行失败 execution={execution_id}")
        execution.fail(str(exc))
        return {'status': 'failed', 'error': str(exc)}
    finally:
        shutil.rmtree(_workdir_for(execution_id), ignore_errors=True)


def _workdir_for(execution_id):
    return os.path.join(tempfile.gettempdir(), 'perf_test', str(execution_id))


def _load_execution_context(execution):
    """从执行记录提取运行上下文（负载参数、host、locustfile）。"""
    from .models import PerfTestPlan

    scenario = execution.scenario
    requests = list(scenario.requests.all().order_by('order', 'id'))
    if not requests:
        raise ValueError('场景下没有任何请求模板，无法执行')

    plan = PerfTestPlan.objects.filter(scenario=scenario).first()
    snapshot = execution.plan_snapshot or {}
    think_time = plan.think_time if plan else snapshot.get('think_time', 0)
    users = plan.users if plan else snapshot.get('users', 10)
    target_qps = plan.target_qps if plan else snapshot.get('target_qps')

    return {
        'requests': requests,
        'users': users,
        'spawn_rate': plan.spawn_rate if plan else snapshot.get('spawn_rate', 1),
        'duration': plan.duration if plan else snapshot.get('duration', 60),
        'host': infer_host(requests),
        'node': plan.node if plan else None,
        'locustfile': scenario.locustfile or render_locustfile(
            requests, think_time, target_qps=target_qps, users=users
        ),
    }


def _prepare_workdir(execution_id, locustfile):
    workdir = _workdir_for(execution_id)
    os.makedirs(workdir, exist_ok=True)
    with open(os.path.join(workdir, 'locustfile.py'), 'w', encoding='utf-8') as fp:
        fp.write(locustfile)
    return workdir


def _build_command(workdir, host, users, spawn_rate, duration):
    cmd = [
        LOCUST_BIN,
        '-f', os.path.join(workdir, 'locustfile.py'),
        '--headless',
        '--users', str(users),
        '--spawn-rate', str(spawn_rate),
        '--run-time', f"{duration}s",
        '--csv', os.path.join(workdir, 'result'),
        '--csv-full-history',
        '--only-summary',
    ]
    if host:
        cmd += ['--host', host]
    return cmd


def _run_and_monitor(execution, workdir, cmd, duration):
    execution.start()
    log_path = os.path.join(workdir, 'locust.log')
    with open(log_path, 'w', encoding='utf-8') as log_file:
        proc = subprocess.Popen(
            cmd, cwd=workdir, stdout=log_file, stderr=subprocess.STDOUT,
        )
    deadline = time.time() + duration + _TIMEOUT_BUFFER
    start = time.time()
    history_path = os.path.join(workdir, 'result_stats_history.csv')

    try:
        while proc.poll() is None:
            if time.time() > deadline:
                proc.terminate()
                raise RuntimeError('压测执行超时')
            elapsed = time.time() - start
            progress = min(99.0, round(elapsed / duration * 100, 1)) if duration else 0
            execution.update_progress(progress)
            _push_latest_snapshot(execution.id, history_path, progress)
            time.sleep(_POLL_INTERVAL)
    finally:
        if proc.poll() is None:
            proc.terminate()

    if proc.returncode != 0:
        with open(log_path, encoding='utf-8', errors='ignore') as fp:
            tail = fp.read()[-2000:]
        raise RuntimeError(f"Locust 执行失败: {tail}")


def _push_latest_snapshot(execution_id, history_path, progress):
    if not os.path.exists(history_path):
        return
    try:
        with open(history_path, encoding='utf-8') as fp:
            series = parse_locust_history_csv(fp.read())
    except (OSError, ValueError):
        return
    if not series:
        return
    latest = series[-1]
    push_execution_update(
        execution_id,
        {
            'progress': progress,
            'rps': latest.get('rps', 0),
            'users': latest.get('users', 0),
        },
    )


def _save_report(execution, workdir):
    from .models import PerfTestReport

    stats_path = os.path.join(workdir, 'result_stats.csv')
    history_path = os.path.join(workdir, 'result_stats_history.csv')

    with open(stats_path, encoding='utf-8') as fp:
        metrics = parse_locust_stats_csv(fp.read())

    series = []
    if os.path.exists(history_path):
        with open(history_path, encoding='utf-8') as fp:
            series = parse_locust_history_csv(fp.read())
    metrics['peak_rps'] = calc_peak_rps(series)
    metrics['rps_series'] = series

    report, _ = PerfTestReport.objects.update_or_create(
        execution=execution, defaults=metrics
    )
    return report


def _dispatch_diagnosis(report):
    """异步触发 AI 诊断，失败不影响压测执行结果。"""
    try:
        from .tasks import diagnose_perf_report

        diagnose_perf_report.delay(report.id)
    except Exception:
        logger.warning(f"触发 AI 诊断失败 report={report.id}", exc_info=True)
