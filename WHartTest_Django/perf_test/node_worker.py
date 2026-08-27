"""分布式压测节点 Worker：从 master 拉取任务，本机跑 Locust，回报进度与结果。

不依赖数据库：任务内容（含渲染后的 locustfile、负载参数）由 master 经 claim 下发，
worker 仅按 HTTP 协议上报进度与结果，可独立部署到任意施压机。

用法
----
    python perf_test/node_worker.py \
        --base-url http://<master>/api/perf-test \
        --node-id 1 --token <JWT> --interval 5

依赖：requests、locust（与 master 同版本）。
"""

import argparse
import logging
import os
import subprocess
import time

import requests

from .runner import _build_command, _workdir_for, _prepare_workdir
from .services import (
    calc_peak_rps,
    parse_locust_history_csv,
    parse_locust_stats_csv,
)

logger = logging.getLogger(__name__)

_TIMEOUT_BUFFER = 120
_POLL_INTERVAL = 1.0


class NodeWorker:
    def __init__(self, base_url, node_id, token, interval=5):
        self.base_url = base_url.rstrip('/')
        self.node_id = node_id
        self.endpoint = f"{self.base_url}/nodes/{node_id}"
        self.interval = interval
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Bearer {token}'

    def _post(self, action, **payload):
        resp = self.session.post(f"{self.endpoint}/{action}/", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def run_forever(self):
        logger.info(f"节点 worker 启动 node_id={self.node_id} interval={self.interval}s")
        while True:
            try:
                data = self._post('claim')
                if data.get('has_task'):
                    self._execute(data['task'])
            except Exception as exc:
                logger.warning(f"worker 心跳失败: {exc}")
            time.sleep(self.interval)

    def _execute(self, task):
        execution_id = task['execution_id']
        logger.info(f"开始执行任务 execution={execution_id}")
        workdir = _prepare_workdir(execution_id, task['locustfile'])
        cmd = _build_command(
            workdir, task['host'], task['users'], task['spawn_rate'], task['duration']
        )
        try:
            self._run_and_report(execution_id, workdir, cmd, task['duration'])
        finally:
            import shutil

            shutil.rmtree(_workdir_for(execution_id), ignore_errors=True)

    def _run_and_report(self, execution_id, workdir, cmd, duration):
        log_path = os.path.join(workdir, 'locust.log')
        started = time.time()
        with open(log_path, 'w', encoding='utf-8') as log_file:
            proc = subprocess.Popen(cmd, cwd=workdir, stdout=log_file, stderr=subprocess.STDOUT)

        history_path = os.path.join(workdir, 'result_stats_history.csv')
        deadline = started + duration + _TIMEOUT_BUFFER
        try:
            while proc.poll() is None:
                if time.time() > deadline:
                    proc.terminate()
                    self._post('report', execution_id=execution_id, error='压测执行超时')
                    return
                elapsed = time.time() - started
                progress = min(99.0, round(elapsed / duration * 100, 1)) if duration else 0
                self._report_progress(execution_id, history_path, progress)
                time.sleep(_POLL_INTERVAL)
        except Exception:
            if proc.poll() is None:
                proc.terminate()
            raise
        finally:
            if proc.poll() is None:
                proc.terminate()

        if proc.returncode != 0:
            with open(log_path, encoding='utf-8', errors='ignore') as fp:
                tail = fp.read()[-2000:]
            self._post('report', execution_id=execution_id, error=f"Locust 执行失败: {tail}")
            return

        try:
            stats_path = os.path.join(workdir, 'result_stats.csv')
            with open(stats_path, encoding='utf-8') as fp:
                metrics = parse_locust_stats_csv(fp.read())
            series = []
            if os.path.exists(history_path):
                with open(history_path, encoding='utf-8') as fp:
                    series = parse_locust_history_csv(fp.read())
            metrics['peak_rps'] = calc_peak_rps(series)
            self._post(
                'report',
                execution_id=execution_id,
                stats=metrics,
                series=series,
            )
            logger.info(f"任务完成并上报 execution={execution_id}")
        except Exception as exc:
            logger.warning(f"解析/上报结果失败 execution={execution_id}: {exc}")
            self._post('report', execution_id=execution_id, error=str(exc))

    def _report_progress(self, execution_id, history_path, progress):
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
        self._post(
            'progress',
            execution_id=execution_id,
            progress=progress,
            rps=latest.get('rps', 0),
            users=latest.get('users', 0),
        )


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description='分布式压测节点 Worker')
    parser.add_argument('--base-url', required=True, help='master 的 perf_test API 前缀')
    parser.add_argument('--node-id', required=True, type=int, help='本节点在 master 注册的 ID')
    parser.add_argument('--token', required=True, help='API 访问 JWT')
    parser.add_argument('--interval', type=int, default=5, help='轮询间隔(秒)')
    args = parser.parse_args()

    NodeWorker(args.base_url, args.node_id, args.token, args.interval).run_forever()


if __name__ == '__main__':
    main()
