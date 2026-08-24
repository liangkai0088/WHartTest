"""Midscene.js 视觉引擎封装。

- 按 QaSuite.llm_config（LLMConfig 行）构造运行时环境变量
- 缓存：注入 agent.cache.id=<suite_id> + strategy=read-write（重放加速）
- 执行: midscene <yaml> --summary summary.json，cwd=run dir，超时 10min
- 解析 summary.json（pass/fail counts）+ report html

## LLMConfig → Midscene 环境变量映射（midscene 1.10.x，@midscene/shared DEFAULT_MODEL_CONFIG_KEYS）
  LLMConfig.name     -> MIDSCENE_MODEL_NAME
  LLMConfig.api_url  -> MIDSCENE_MODEL_BASE_URL（+ 旧版 OPENAI_BASE_URL）
  LLMConfig.api_key  -> MIDSCENE_MODEL_API_KEY（+ 旧版 OPENAI_API_KEY）
  LLMConfig.request_timeout -> MIDSCENE_MODEL_TIMEOUT
  MIDSCENE_MODEL_FAMILY -> 视觉 grounding 适配器家族（必需；缺失时回退通用 OpenAI 兼容
                           适配器，坐标解析/图片预处理不可靠）。按 base_url 自动探测，
                           可用环境变量 MIDSCENE_MODEL_FAMILY 显式覆盖。

## base_url -> MIDSCENE_MODEL_FAMILY 自动探测表
  base_url 包含                              family
  dashscope.aliyuncs.com                     按模型名细分：
                                              - 含 'qwen2.5-vl' -> qwen2.5-vl
                                              - 含 'vl'         -> qwen3-vl
                                              - 其余（qwen3.7 / qwen3.5 / -plus 等）-> qwen3
  open.bigmodel.cn                           glm-v
  ark.cn-beijing.volces.com                  doubao-seed
  generativelanguage.googleapis.com          gemini
  含 'openai'（api.openai.com 等）           gpt-5
  未知 host                                  qwen3（警告日志）
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from typing import Optional

import yaml

logger = logging.getLogger('web_qa')

MIDSCENE_TIMEOUT = 600  # 10min
MIDSCENE_BIN = 'midscene'

# LLMConfig → Midscene 环境变量映射（@midscene/shared DEFAULT_MODEL_CONFIG_KEYS）
ENV_KEYS = {
    'name': 'MIDSCENE_MODEL_NAME',
    'api_url': 'MIDSCENE_MODEL_BASE_URL',
    'api_key': 'MIDSCENE_MODEL_API_KEY',
}
LEGACY_ENV_KEYS = {
    'api_url': 'OPENAI_BASE_URL',
    'api_key': 'OPENAI_API_KEY',
}


class MidsceneError(Exception):
    """Midscene 执行失败。"""


def detect_model_family(base_url: str, model_name: str = '') -> str:
    """根据 LLMConfig.base_url（+ 模型名）自动探测 MIDSCENE_MODEL_FAMILY。

    探测结果均为 @midscene/core@1.10.12 已注册的适配器 family：
    qwen3 / qwen3-vl / qwen2.5-vl / glm-v / doubao-seed / gemini / gpt-5。
    """
    url = (base_url or '').strip().lower()
    model = (model_name or '').strip().lower()

    if 'dashscope.aliyuncs.com' in url:
        # 通义千问：按模型名细分（qwen2.5-vl 需先于通用 'vl' 判断）
        if 'qwen2.5-vl' in model:
            return 'qwen2.5-vl'
        if 'vl' in model:
            return 'qwen3-vl'
        # qwen3.7 / qwen3.5 / -plus 且不含 vl
        if ('qwen3.7' in model) or ('qwen3.5' in model) or ('-plus' in model):
            return 'qwen3'
        return 'qwen3'
    if 'open.bigmodel.cn' in url:
        return 'glm-v'
    if 'ark.cn-beijing.volces.com' in url:
        return 'doubao-seed'
    if 'generativelanguage.googleapis.com' in url:
        return 'gemini'
    if 'openai' in url:
        return 'gpt-5'
    logger.warning(
        '[web_qa] 无法识别 modelFamily，base_url=%s model=%s，回退 qwen3',
        base_url, model_name,
    )
    return 'qwen3'


def build_env(llm_config) -> dict:
    """根据 LLMConfig 行构造 midscene 运行环境变量。

    精确映射（midscene 1.10.x）：
      LLMConfig.name     -> MIDSCENE_MODEL_NAME
      LLMConfig.api_url  -> MIDSCENE_MODEL_BASE_URL（+ 旧版 OPENAI_BASE_URL）
      LLMConfig.api_key  -> MIDSCENE_MODEL_API_KEY（+ 旧版 OPENAI_API_KEY）
      LLMConfig.request_timeout -> MIDSCENE_MODEL_TIMEOUT
      MIDSCENE_MODEL_FAMILY      -> 视觉 grounding 适配器（环境变量可显式覆盖，
                                    否则按 base_url 自动探测，见 detect_model_family）
    浏览器：
      PUPPETEER_EXECUTABLE_PATH /usr/bin/chromium（容器内 playwright chromium 符号链接）
      PLAYWRIGHT_BROWSERS_PATH  /root/.cache/ms-playwright
    未配置 LLMConfig 时仅提供浏览器变量，midscene 会以清晰错误提示模型未配置。
    """
    env = dict(os.environ)

    if llm_config is not None:
        for attr, key in ENV_KEYS.items():
            value = getattr(llm_config, attr, None)
            if value:
                env[key] = str(value).strip()
        for attr, key in LEGACY_ENV_KEYS.items():
            value = getattr(llm_config, attr, None)
            if value:
                env.setdefault(key, str(value).strip())
        timeout = getattr(llm_config, 'request_timeout', None)
        if timeout:
            env.setdefault('MIDSCENE_MODEL_TIMEOUT', str(int(timeout)))
        # 显式环境变量覆盖优先，否则按 base_url 自动探测
        if not os.environ.get('MIDSCENE_MODEL_FAMILY'):
            env['MIDSCENE_MODEL_FAMILY'] = detect_model_family(
                getattr(llm_config, 'api_url', ''),
                getattr(llm_config, 'name', ''),
            )

    if not env.get('PUPPETEER_EXECUTABLE_PATH'):
        env['PUPPETEER_EXECUTABLE_PATH'] = os.environ.get(
            'PUPPETEER_EXECUTABLE_PATH', '/usr/bin/chromium'
        )
    env.setdefault('PLAYWRIGHT_BROWSERS_PATH', '/root/.cache/ms-playwright')
    env.setdefault('MIDSCENE_CHROME_PATH', os.environ.get('MIDSCENE_CHROME_PATH', '/usr/bin/chromium'))
    return env


def build_midscene_yaml(yaml_content: str, suite_id: int, base_url: str = '') -> str:
    """注入 agent.cache 配置，保证重放读缓存加速。"""
    try:
        data = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        # 非 YAML 时原样透传，由 midscene 报错
        return yaml_content

    if not isinstance(data, dict):
        return yaml_content

    if 'target' not in data and 'web' not in data and 'page' not in data and 'browser' not in data:
        if base_url:
            data['target'] = {'url': base_url}
        else:
            data['target'] = {'url': 'http://localhost'}

    agent = data.get('agent')
    if not isinstance(agent, dict):
        agent = {}
        data['agent'] = agent
    cache = agent.get('cache')
    if not isinstance(cache, dict):
        cache = {}
        agent['cache'] = cache
    cache.setdefault('id', f'suite-{suite_id}')
    cache.setdefault('strategy', 'read-write')

    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def parse_summary_file(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    summary = data.get('summary') or {}
    results = data.get('results') or []
    errors = [r.get('error') for r in results if r.get('error')]
    return {
        'total': summary.get('total', 0),
        'passed': summary.get('successful', 0),
        'failed': summary.get('failed', 0),
        'partial_failed': summary.get('partialFailed', 0),
        'not_executed': summary.get('notExecuted', 0),
        'errors': errors,
        'raw': data,
    }


def run_midscene(run_id: int) -> dict:
    """执行 midscene 引擎套件；绝不抛出。"""
    from .models import QaRun

    try:
        run = QaRun.objects.select_related('suite', 'suite__llm_config').get(id=run_id)
    except QaRun.DoesNotExist:
        return {'error': f'run {run_id} not found'}

    suite_model = run.suite
    run_dir = os.path.join(settings_media_root(), 'web_qa', 'runs', str(run_id))
    os.makedirs(run_dir, exist_ok=True)

    yaml_path = os.path.join(run_dir, 'suite.yaml')
    try:
        content = build_midscene_yaml(suite_model.yaml_content or '', suite_model.id, suite_model.base_url)
        with open(yaml_path, 'w', encoding='utf-8') as fh:
            fh.write(content)
    except Exception as e:  # noqa: BLE001
        logger.exception('[web_qa] midscene yaml write failed: %s', e)
        run.status = 'failed'
        run.error = f'Midscene YAML 写入失败: {e}'
        run.finished_at = _now()
        run.save(update_fields=['status', 'error', 'finished_at'])
        return {'run_id': run_id, 'status': 'failed', 'error': run.error}

    env = build_env(suite_model.llm_config)
    cmd = [MIDSCENE_BIN, 'suite.yaml', '--summary', 'summary.json']

    stdout, stderr = '', ''
    exit_code = None
    timed_out = False
    try:
        result = subprocess.run(
            cmd,
            cwd=run_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=MIDSCENE_TIMEOUT,
        )
        stdout, stderr = result.stdout or '', result.stderr or ''
        exit_code = result.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ''
        stderr = e.stderr or ''
        timed_out = True
    except FileNotFoundError as e:
        logger.exception('[web_qa] midscene CLI 不存在: %s', e)
        run.status = 'failed'
        run.error = 'midscene CLI 未安装，请执行: npm install -g @midscene/cli'
        run.finished_at = _now()
        run.save(update_fields=['status', 'error', 'finished_at'])
        return {'run_id': run_id, 'status': 'failed', 'error': run.error}

    run_dir_files = _collect_run_files(run_dir)

    summary = None
    summary_path = os.path.join(run_dir, 'midscene_run', 'output', 'summary.json')
    if os.path.exists(summary_path):
        try:
            summary = parse_summary_file(summary_path)
        except Exception as e:  # noqa: BLE001
            logger.warning('[web_qa] midscene summary parse failed: %s', e)

    error_msg = ''
    if timed_out:
        error_msg = f'Midscene 执行超时（{MIDSCENE_TIMEOUT}s）'
    elif summary:
        if summary['failed'] > 0 or summary['total'] == 0:
            error_msg = '; '.join(summary['errors'][:3])
    elif exit_code != 0:
        # 无 summary 且非零退出：抓取 CLI 错误
        tail = (stderr or stdout or '').strip().splitlines()
        error_msg = '\n'.join(tail[-5:]) if tail else f'Midscene 退出码 {exit_code}'

    status = 'passed'
    if timed_out:
        status = 'failed'
    elif summary is not None:
        status = 'passed' if summary['failed'] == 0 and summary['total'] > 0 else 'failed'
    elif exit_code != 0:
        status = 'failed'

    if run.status == 'cancelled':
        status = 'cancelled'

    report_md = build_midscene_report_md(suite_model, summary, error_msg, run_dir_files, run_dir)

    run.status = status
    run.error = error_msg
    run.summary = {
        'total': summary['total'] if summary else 0,
        'passed': summary['passed'] if summary else 0,
        'failed': summary['failed'] if summary else 0,
        'skipped': 0,
        'warnings': 0,
        'errors': summary['errors'] if summary else [],
        'timed_out': timed_out,
        'exit_code': exit_code,
    }
    run.result_json = {
        'engine': 'midscene',
        'exit_code': exit_code,
        'stdout_tail': (stdout or '').strip().splitlines()[-20:],
        'stderr_tail': (stderr or '').strip().splitlines()[-20:],
        'summary': summary,
        'report_html': run_dir_files.get('report_html'),
    }
    run.report_md = report_md
    run.finished_at = _now()
    run.save(update_fields=['status', 'error', 'summary', 'result_json', 'report_md', 'finished_at'])

    return {'run_id': run_id, 'status': status, 'error': error_msg}


def _collect_run_files(run_dir: str) -> dict:
    """定位 report html（复制到 run_dir/report.html）并返回路径映射。"""
    output = {'report_html': '', 'summary_json': ''}
    report_dir = os.path.join(run_dir, 'midscene_run', 'report')
    if os.path.isdir(report_dir):
        htmls = sorted(
            [f for f in os.listdir(report_dir) if f.endswith('.html')]
        )
        if htmls:
            src = os.path.join(report_dir, htmls[0])
            dst = os.path.join(run_dir, 'report.html')
            try:
                shutil.copy2(src, dst)
                output['report_html'] = dst
            except OSError as e:
                logger.warning('[web_qa] copy report html failed: %s', e)
                output['report_html'] = src
    summary_path = os.path.join(run_dir, 'midscene_run', 'output', 'summary.json')
    if os.path.exists(summary_path):
        output['summary_json'] = summary_path
    return output


def build_midscene_report_md(suite_model, summary: Optional[dict], error_msg: str, files: dict, run_dir: str) -> str:
    lines = []
    lines.append(f'# {suite_model.name}')
    lines.append('')
    lines.append(f'**生成时间:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append('**执行引擎:** midscene')
    lines.append(f'**URL:** {suite_model.base_url}')
    lines.append('')
    lines.append('## 摘要')
    lines.append('')
    lines.append('| 指标 | 值 |')
    lines.append('| --- | --- |')
    if summary:
        lines.append(f'| 文件总数 | {summary["total"]} |')
        lines.append(f'| 成功 | {summary["passed"]} |')
        lines.append(f'| 失败 | {summary["failed"]} |')
        lines.append(f'| 部分失败 | {summary["partial_failed"]} |')
        lines.append(f'| 未执行 | {summary["not_executed"]} |')
    else:
        lines.append('| 状态 | 失败（无 summary 输出） |')
    lines.append('')
    if error_msg:
        lines.append(f'**错误:**')
        lines.append('')
        lines.append('```')
        lines.append(error_msg[:2000])
        lines.append('```')
        lines.append('')
    if files.get('report_html'):
        rel = os.path.relpath(files['report_html'], run_dir)
        lines.append(f'**HTML 报告:** `{rel}`')
        lines.append('')
        lines.append(f'![Midscene 报告]({rel})')
        lines.append('')
    return '\n'.join(lines)


def settings_media_root() -> str:
    from django.conf import settings
    return str(settings.MEDIA_ROOT)


def _now():
    from django.utils import timezone
    return timezone.now()
