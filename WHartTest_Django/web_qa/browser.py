"""agent-browser CLI 子进程封装（web-qa-bot src/browser.ts 的 Python 移植）。

- argv 数组 + 无 shell；每条命令前缀 ['--session', session_id]
- 默认命令超时 30s
- eval_js 支持 --stdin（长脚本走 stdin）
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, List, Optional


class BrowserError(Exception):
    """agent-browser 命令执行失败。"""


class AgentBrowser:
    """agent-browser CLI 封装。"""

    def __init__(
        self,
        session_id: str,
        executable: str = 'agent-browser',
        timeout: int = 30,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
    ):
        self.session_id = session_id
        self.executable = executable
        self.timeout = timeout
        self.env = env
        self.cwd = cwd
        self.launched = False

    def _argv(self, args: List[str]) -> List[str]:
        return [self.executable, '--session', self.session_id] + list(args)

    def _run(self, args: List[str], timeout: Optional[int] = None, use_stdin: Optional[str] = None) -> str:
        argv = self._argv(args)
        env = dict(os.environ)
        if self.env:
            env.update(self.env)
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                input=use_stdin,
                env=env,
                cwd=self.cwd,
            )
        except subprocess.TimeoutExpired as e:
            raise BrowserError(
                f'agent-browser 命令超时({timeout or self.timeout}s): {" ".join(args)}'
            ) from e
        except FileNotFoundError as e:
            raise BrowserError(
                f'agent-browser CLI 不存在，请先执行: npm install -g agent-browser'
            ) from e

        output = (result.stderr or '').strip() or (result.stdout or '').strip()
        if result.returncode != 0:
            raise BrowserError(
                f'agent-browser 命令失败: {" ".join(args)}\n{output}'
            )
        return (result.stdout or '').strip()

    # ---------------- 生命周期 / 导航 ----------------

    def open(self, url: str) -> str:
        self.launched = True
        return self._run(['open', url], timeout=60)

    def close(self) -> None:
        if not self.launched:
            return
        try:
            self._run(['close'], timeout=10)
        except BrowserError:
            pass
        finally:
            self.launched = False

    # ---------------- 快照 / 截图 ----------------

    def snapshot(self, interactive: bool = True) -> str:
        args = ['snapshot', '-i'] if interactive else ['snapshot']
        return self._run(args)

    def snapshot_full(self) -> str:
        return self._run(['snapshot'])

    def screenshot(self, path: str) -> str:
        return self._run(['screenshot', path], timeout=max(self.timeout, 60))

    # ---------------- 交互 ----------------

    def click(self, ref: str) -> str:
        return self._run(['click', ref])

    def type(self, ref: str, text: str) -> str:
        return self._run(['type', ref, text])

    def fill(self, ref: str, text: str) -> str:
        return self._run(['fill', ref, text])

    def select(self, ref: str, value: str) -> str:
        return self._run(['select', ref, value])

    def check(self, ref: str) -> str:
        return self._run(['check', ref])

    def uncheck(self, ref: str) -> str:
        return self._run(['uncheck', ref])

    def hover(self, ref: str) -> str:
        return self._run(['hover', ref])

    def press(self, key: str) -> str:
        return self._run(['press', key])

    def wait(self, *args) -> str:
        return self._run(['wait'] + list(args))

    def scroll_into_view(self, ref: str) -> str:
        return self._run(['scrollintoview', ref])

    # ---------------- 查询 ----------------

    def get_text(self, ref: str) -> str:
        return self._run(['get', 'text', ref])

    def get_value(self, ref: str) -> str:
        return self._run(['get', 'value', ref])

    def get_count(self, selector: str) -> int:
        out = self._run(['get', 'count', selector])
        try:
            return int(float(out))
        except (TypeError, ValueError):
            return 0

    def get_url(self) -> str:
        return self._run(['get', 'url'])

    def get_title(self) -> str:
        return self._run(['get', 'title'])

    def is_visible(self, ref: str) -> bool:
        out = self._run(['is', 'visible', ref])
        return 'true' in out.lower()

    def is_enabled(self, ref: str) -> bool:
        out = self._run(['is', 'enabled', ref])
        return 'true' in out.lower()

    # ---------------- eval ----------------

    def eval_js(self, script: str, use_stdin: bool = True) -> Any:
        """执行 JS，返回 JSON 解析后的结果。"""
        if use_stdin:
            out = self._run(['eval', '--stdin'], use_stdin=script)
        else:
            out = self._run(['eval', script])
        try:
            return json.loads(out)
        except (TypeError, ValueError):
            return out

    # ---------------- find（语义定位）----------------

    def find(self, locator_kind: str, value: str, action: str = 'click', **kw) -> Any:
        """agent-browser find；成功返回数据，失败抛 BrowserError。

        locator_kind: role/text/label/placeholder/alt/title/testid/first/last/nth
        kw: name(str), exact(bool)
        """
        args = ['--json', 'find', locator_kind, value, action]
        name = kw.get('name')
        if name:
            args += ['--name', name]
        if kw.get('exact'):
            args += ['--exact']
        out = self._run(args)
        try:
            data = json.loads(out)
        except (TypeError, ValueError):
            return {'success': bool(out)}
        if not data.get('success'):
            raise BrowserError(str(data.get('error') or 'find failed'))
        return data
