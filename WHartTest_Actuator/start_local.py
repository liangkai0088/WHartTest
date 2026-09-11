#!/usr/bin/env python3
"""Start the local headed actuator for docker-compose.local.yml.

Usage: python3 WHartTest_Actuator/start_local.py [--status]
Requires the actuator's .venv and config.toml. Logs and PID stay under data.
"""

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--api', default='http://127.0.0.1:8912')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    python = root / '.venv/bin/python'
    config = root / 'config.toml'
    if not python.is_file() or not config.is_file():
        parser.error('Install the actuator .venv and configure config.toml first.')
    api = urlsplit(args.api.rstrip('/'))
    if api.scheme not in ('http', 'https') or not api.hostname or api.query or api.fragment:
        parser.error('--api must be an HTTP(S) server URL without query or fragment.')
    ws = urlunsplit((
        'wss' if api.scheme == 'https' else 'ws', api.netloc,
        api.path + '/ws/ui/actuator/', '', '',
    ))
    os.umask(0o077)
    runtime = root / 'data/local-headed'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'actuator.pid').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            print(f'Local headed actuator running, PID {lock.read().strip()}')
            return
        if args.status:
            print('Local headed actuator stopped')
            return
        env = os.environ.copy()
        for key in ('NO_PROXY', 'no_proxy'):
            env[key] = ','.join(filter(None, [env.get(key), 'localhost', '127.0.0.1']))
        env['PYTHONUNBUFFERED'] = '1'
        env['WHARTTEST_BROWSER_PROXY'] = ''
        env['WHARTTEST_BROWSER_DIRECT'] = 'true'
        log_path = runtime / 'actuator.log'
        with log_path.open('ab') as log:
            # The child holds the file lock for its lifetime, including reconnects.
            process = subprocess.Popen(
                [str(python), str(root / 'main.py'), '--config', str(config),
                 '--server', ws, '--api', args.api.rstrip('/'),
                 '--id', 'local-headed', '--no-gui', '--headed'],
                cwd=runtime, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                pass_fds=(lock.fileno(),),
            )
        lock.seek(0)
        lock.truncate()
        lock.write(str(process.pid))
        lock.flush()
        time.sleep(1)
        if process.poll() is not None:
            raise SystemExit(f'Actuator failed to start. Check {log_path}')
        print(f'Local headed actuator started, PID {process.pid}. Log: {log_path}')


if __name__ == '__main__':
    main()
