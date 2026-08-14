"""前端组件解析器管理器。

克隆 orchestrator_integration/builtin_tools/persistent_playwright.py 的模式：
通过 stdin/stdout 与长驻 Node.js 子进程做逐行 JSON-RPC 通信；
进程崩溃自动重启；线程安全；请求超时 30s。
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger('code_analysis')


class ComponentParserError(RuntimeError):
    pass


class _NodeComponentProcess:
    """单个长驻 Node 进程，托管 @vue/compiler-sfc + @babel/parser。"""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: Dict[str, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._stderr_tail: deque = deque(maxlen=200)
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None

    def _server_script_path(self) -> str:
        return str(Path(__file__).parent / 'js' / 'component_parser_server.js')

    def _start(self) -> None:
        with self._start_lock:
            if self._proc is not None and self._proc.poll() is None:
                return

            node_bin = os.environ.get('NODE_BIN') or shutil.which('node')
            if not node_bin:
                raise ComponentParserError('组件解析器不可用：未找到 node 可执行文件')

            script = self._server_script_path()
            if not Path(script).exists():
                raise ComponentParserError('组件解析器不可用：缺少 component_parser_server.js')

            try:
                self._proc = subprocess.Popen(
                    [node_bin, script],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,
                )
            except Exception as e:
                self._proc = None
                raise ComponentParserError(f'组件解析器不可用：Node 子进程启动失败 ({e})')

            self._stdout_thread = threading.Thread(
                target=self._stdout_reader, name='ca-stdout', daemon=True
            )
            self._stderr_thread = threading.Thread(
                target=self._stderr_reader, name='ca-stderr', daemon=True
            )
            self._stdout_thread.start()
            self._stderr_thread.start()

            try:
                resp = self.request('ping', params={}, timeout_seconds=10)
                if not resp.get('ok', False):
                    raise ComponentParserError(self._format_response_error(resp))
            except Exception:
                self.terminate(graceful=False)
                raise

            logger.info('[code_analysis] 组件解析器 Node 进程启动成功')

    def _stdout_reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            raw = (line or '').strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                self._stderr_tail.append(f'[stdout] {raw[:500]}')
                continue
            req_id = msg.get('id')
            if not req_id:
                continue
            with self._pending_lock:
                q = self._pending.get(req_id)
            if q is not None:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass
        self._fail_all_pending('组件解析器进程已退出')

    def _stderr_reader(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for line in self._proc.stderr:
            raw = (line or '').rstrip('\n')
            if raw:
                self._stderr_tail.append(raw[:500])

    def _fail_all_pending(self, reason: str) -> None:
        with self._pending_lock:
            items = list(self._pending.items())
            self._pending.clear()
        for req_id, q in items:
            try:
                q.put_nowait({'id': req_id, 'ok': False, 'error': reason})
            except Exception:
                continue

    def _ensure_alive(self) -> None:
        if self._proc is None:
            raise ComponentParserError('组件解析器不可用：进程未启动')
        if self._proc.poll() is not None:
            raise ComponentParserError('组件解析器不可用：进程已退出')

    def request(self, method: str, params: Dict[str, Any], timeout_seconds: int = 30) -> Dict[str, Any]:
        self._ensure_alive()
        assert self._proc is not None and self._proc.stdin is not None

        req_id = uuid.uuid4().hex
        q: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[req_id] = q

        payload = {'id': req_id, 'method': method, 'params': params or {}}
        try:
            with self._write_lock:
                self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
                self._proc.stdin.flush()
        except Exception as exc:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise ComponentParserError(f'组件解析器不可用：写入失败 ({exc})') from exc

        try:
            resp = q.get(timeout=timeout_seconds)
        except queue.Empty:
            self.terminate(graceful=False)
            raise TimeoutError(f'组件解析超时（{timeout_seconds}s）')
        finally:
            with self._pending_lock:
                self._pending.pop(req_id, None)

        return resp

    def terminate(self, graceful: bool = True) -> None:
        if self._proc is None:
            self._join_io_threads()
            return
        if self._proc.poll() is not None:
            self._proc = None
            self._join_io_threads()
            return
        if graceful:
            try:
                self.request('ping', params={}, timeout_seconds=3)
            except Exception:
                pass
        try:
            self._proc.terminate()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=3)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=3)
            except Exception:
                pass
        self._proc = None
        self._join_io_threads()
        with self._pending_lock:
            self._pending.clear()
        self._stderr_tail.clear()

    def _join_io_threads(self) -> None:
        for th in (self._stdout_thread, self._stderr_thread):
            if th is None:
                continue
            try:
                if th.is_alive():
                    th.join(timeout=2)
            except Exception:
                pass
        self._stdout_thread = None
        self._stderr_thread = None

    def _format_response_error(self, resp: Dict[str, Any]) -> str:
        pieces = []
        if resp.get('error'):
            pieces.append(str(resp['error']))
        if self._stderr_tail:
            pieces.append('\n'.join(self._stderr_tail))
        return '\n'.join(pieces).strip() or '组件解析器未知错误'


class ComponentParserManager:
    """全局单例管理器：复用/重启 Node 子进程。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._proc: Optional[_NodeComponentProcess] = None
        atexit.register(self.close)

    def parse_file(self, path: str, content: str) -> dict:
        """解析单个源码文件，返回 {path, elements:[...]}。"""
        with self._lock:
            if self._proc is None or self._proc._proc is None or self._proc._proc.poll() is not None:
                if self._proc is not None:
                    try:
                        self._proc.terminate(graceful=False)
                    except Exception:
                        pass
                self._proc = _NodeComponentProcess()
                try:
                    self._proc._start()
                except Exception:
                    self._reset()
                    raise
            try:
                resp = self._proc.request('parse_file', {'path': path, 'content': content}, timeout_seconds=30)
            except (ComponentParserError, TimeoutError):
                self._reset()
                raise
            if not resp.get('ok', False):
                err = resp.get('error') or '解析失败'
                self._reset()
                raise ComponentParserError(f'组件解析器不可用：{err}')
            return resp.get('result') or {'path': path, 'elements': []}

    def _reset(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.terminate(graceful=False)
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._reset()


parser_manager = ComponentParserManager()
