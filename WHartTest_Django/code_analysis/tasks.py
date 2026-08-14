"""code_analysis 异步任务：OpenAPI 分析 & 组件源码分析。"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

import httpx
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('code_analysis')

SPEC_DIR_NAME = 'specs'

INTERACTIVE_TAGS = {'button', 'input', 'select', 'textarea', 'a', 'label', 'option', 'svg'}
COMPONENT_EXTENSIONS = ('.vue', '.jsx', '.tsx')
JS_LIKE_EXTENSIONS = ('.js', '.ts', '.mjs', '.cjs')


def _spec_media_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / 'code_projects' / SPEC_DIR_NAME


def _resolve_spec_path(task, warnings) -> str:
    """解析 Spec 来源为本地文件路径。"""
    if task.source == 'spec_url':
        url = (task.spec_name or '').strip()
        if not url:
            raise ValueError('spec_url 为空')
        try:
            resp = httpx.get(url, timeout=10.0, follow_redirects=True)
            resp.raise_for_status()
            raw = resp.content
        except Exception as e:
            raise ValueError(f'下载 spec_url 失败: {e}')
        if not raw:
            raise ValueError('spec_url 返回内容为空')
        tmp_dir = tempfile.mkdtemp(prefix='ca_spec_')
        ext = Path(url.split('?')[0]).suffix.lower() or '.yaml'
        if ext not in ('.json', '.yaml', '.yml'):
            ext = '.yaml'
        path = os.path.join(tmp_dir, f'spec{ext}')
        with open(path, 'wb') as fh:
            fh.write(raw)
        return path

    # upload 来源：文件在创建任务时已落盘（扩展名可能经内容嗅探，使用 glob 匹配）
    matches = sorted(_spec_media_dir().glob(f'spec_{task.id}.*'))
    if not matches:
        raise ValueError('上传的 Spec 文件不存在，请重新上传')
    return str(matches[0])


@shared_task
def run_spec_analysis(task_id):
    """解析 OpenAPI 文档 -> 生成建议 -> 落库。"""
    from .models import SpecAnalysisSuggestion, SpecAnalysisTask

    try:
        task = SpecAnalysisTask.objects.get(id=task_id)
    except SpecAnalysisTask.DoesNotExist:
        return {'error': f'task {task_id} not found'}

    task.status = 'running'
    task.save(update_fields=['status'])
    warnings = list(task.warnings or [])

    try:
        from .openapi_parser import load_spec, normalize_operations
        from .spec_suggest import generate_suggestions

        spec_path = _resolve_spec_path(task, warnings)
        spec = load_spec(spec_path)
        operations = normalize_operations(spec)
        if not operations:
            raise ValueError('OpenAPI 文档中未发现任何接口操作')

        payloads = generate_suggestions(operations, use_llm=task.use_llm, warnings=warnings)

        rows = [SpecAnalysisSuggestion(task=task, payload=p) for p in payloads]
        if rows:
            SpecAnalysisSuggestion.objects.bulk_create(rows)

        task.status = 'completed'
        task.finished_at = timezone.now()
        task.warnings = warnings
        task.save(update_fields=['status', 'finished_at', 'warnings'])
        logger.info('[code_analysis] spec task %s completed, suggestions=%s', task_id, len(rows))
        return {'task_id': task_id, 'status': 'completed', 'suggestions': len(rows)}
    except Exception as e:
        logger.exception('[code_analysis] spec task %s failed: %s', task_id, e)
        warnings.append(f'任务失败：{e}')
        task.status = 'failed'
        task.finished_at = timezone.now()
        task.warnings = warnings
        task.save(update_fields=['status', 'finished_at', 'warnings'])
        return {'task_id': task_id, 'status': 'failed', 'error': str(e)}


# ---------------- 组件分析 ----------------

def _is_component_file(path: str) -> bool:
    if path.endswith(COMPONENT_EXTENSIONS):
        return True
    if path.endswith(JS_LIKE_EXTENSIONS):
        norm = '/' + path.lstrip('/')
        return '/src/' in norm
    return False


def _select_component_files(snapshot, file_filter):
    files = list(snapshot.files.filter(is_deleted=False))
    files = [f for f in files if _is_component_file(f.path)]
    if file_filter:
        patterns = file_filter if isinstance(file_filter, list) else [file_filter]
        patterns = [str(p) for p in patterns if str(p).strip()]
        if patterns:
            files = [f for f in files if any(p in f.path for p in patterns)]
    return files


def _extract_props(el) -> dict:
    props = el.get('props') or {}
    return {str(k): v for k, v in props.items() if v is not None}


def _static_classes(props) -> list:
    cls = str(props.get('class') or props.get('className') or '')
    return [c for c in cls.split() if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', c)]


def _locator_signals(el):
    props = _extract_props(el)
    signals = []
    for key in ('data-testid', 'data-test', 'data-cy'):
        v = props.get(key)
        if v and str(v) not in ('true', 'True'):
            signals.append({'type': 'test_id', 'value': str(v)})
    role = props.get('role')
    if role:
        label = props.get('aria-label') or el.get('text')
        if label:
            signals.append({'type': 'role', 'value': f'{role}:{label}'})
    if props.get('placeholder'):
        signals.append({'type': 'placeholder', 'value': str(props['placeholder'])})
    if props.get('aria-label'):
        signals.append({'type': 'label', 'value': str(props['aria-label'])})
    if props.get('label-for'):
        signals.append({'type': 'label', 'value': str(props['label-for'])})
    if props.get('id'):
        signals.append({'type': 'id', 'value': str(props['id'])})
    if props.get('name'):
        signals.append({'type': 'name', 'value': str(props['name'])})
    return signals


def _css_fallback(el):
    props = _extract_props(el)
    classes = _static_classes(props)
    tag = el.get('tag') or ''
    if classes:
        return {'type': 'css', 'value': f'{tag}.{classes[0]}' if tag else f'.{classes[0]}'}
    if props.get('id'):
        return {'type': 'css', 'value': f'#{props["id"]}'}
    return None


def _xpath_fallback(el):
    tag = el.get('tag') or '*'
    text = (el.get('text') or '').strip()
    if text and len(text) <= 60:
        return {'type': 'xpath', 'value': f'//{tag}[contains(normalize-space(.), "{text}")]'}
    props = _extract_props(el)
    classes = _static_classes(props)
    if classes:
        return {'type': 'xpath', 'value': f'//{tag}[contains(@class, "{classes[0]}")]'}
    return None


def _dedupe_signals(signals, seen):
    result = []
    for s in signals:
        key = (s.get('type'), s.get('value'))
        if key in seen:
            continue
        seen.add(key)
        result.append(s)
    return result


def _build_locator_slots(el):
    """按优先级生成 locator slots；无稳定定位信号返回 None。"""
    signals = _locator_signals(el)
    seen = set()
    signals = _dedupe_signals(signals, seen)

    tag = (el.get('tag') or '').lower()
    text = (el.get('text') or '').strip()
    props = _extract_props(el)
    has_class = bool(_static_classes(props))
    has_text_placeholder = bool(text or props.get('placeholder') or props.get('aria-label'))

    primary = signals[0] if signals else None
    backups = signals[1:] if signals else []

    if primary is None:
        # 无属性级信号时的回退：交互元素 + 文本/占位符，或任意带静态 class 的元素
        if tag in INTERACTIVE_TAGS and has_text_placeholder:
            primary = _css_fallback(el) or _xpath_fallback(el)
        elif has_class:
            primary = _css_fallback(el)
        elif tag in INTERACTIVE_TAGS and text:
            primary = _xpath_fallback(el)

    if primary is None:
        return None

    if len(backups) < 2:
        extras = list(backups)
        for fb in (_css_fallback(el), _xpath_fallback(el)):
            if fb is None:
                continue
            key = (fb.get('type'), fb.get('value'))
            if key in seen:
                continue
            seen.add(key)
            extras.append(fb)
        backups = extras[:2]

    return {
        'primary': primary,
        'backups': backups[:2],
        'iframe': None,
    }


def _page_name_from_path(path: str) -> str:
    parts = path.replace('\\', '/').rstrip('/').split('/')
    base = parts[-1]
    stem = os.path.splitext(base)[0] if '.' in base else base
    if not stem or stem.lower() in ('index', 'app', 'main'):
        stem = parts[-2] if len(parts) > 1 else stem
    return (stem or '未命名页面')[:64]


def _element_name(el, primary) -> str:
    tag = (el.get('tag') or 'element').lower()
    text = (el.get('text') or '').strip()
    base = None
    if tag in ('button', 'a', 'label') and text:
        base = text
    elif primary:
        base = str(primary.get('value') or '')
    name = f'{tag}_{base}' if base else tag
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[^\w\u4e00-\u9fff\-\.]', '_', name)
    return (name or f'{tag}_element')[:60]


def _build_element_payload(path, el):
    """构造 ElementSuggestion payload；无稳定定位信号返回 None。"""
    slots = _build_locator_slots(el)
    if slots is None:
        return None
    return {
        'page_name': _page_name_from_path(path),
        'file_path': path,
        'element_name': _element_name(el, slots['primary']),
        'locator_slots': slots,
    }


@shared_task
def run_component_analysis(task_id):
    """解析快照中的组件文件 -> 生成元素定位建议。"""
    from .models import ComponentAnalysisTask, ElementSuggestion

    try:
        task = ComponentAnalysisTask.objects.select_related('code_project', 'snapshot').get(id=task_id)
    except ComponentAnalysisTask.DoesNotExist:
        return {'error': f'task {task_id} not found'}

    task.status = 'running'
    task.save(update_fields=['status'])
    warnings = list(task.warnings or [])

    try:
        from .component_parser import ComponentParserError, parser_manager

        snapshot = task.snapshot
        if snapshot is None:
            snapshot = (
                task.code_project.snapshots.order_by('-version_no').first()
                or task.code_project.snapshots.order_by('-created_at').first()
            )
        if snapshot is None:
            raise ValueError('未找到可分析的代码快照，请先上传代码包')

        files = _select_component_files(snapshot, task.file_filter)
        if not files:
            warnings.append('未找到可分析的组件文件（.vue/.jsx/.tsx 或 src/ 下的 .js/.ts）')

        suggestions = []
        skipped_content = 0
        parse_errors = []
        for cf in files:
            if not cf.content_stored or not cf.content:
                skipped_content += 1
                continue
            try:
                result = parser_manager.parse_file(cf.path, cf.content)
            except ComponentParserError as e:
                raise e
            except Exception as e:
                parse_errors.append(f'{cf.path}: {e}')
                continue
            for el in (result or {}).get('elements') or []:
                payload = _build_element_payload(cf.path, el)
                if payload is not None:
                    suggestions.append(ElementSuggestion(task=task, payload=payload))

        if suggestions:
            ElementSuggestion.objects.bulk_create(suggestions)

        if skipped_content:
            warnings.append(f'{skipped_content} 个文件无存储内容（>200KB 或二进制），已跳过')
        if parse_errors:
            warnings.append('解析失败：' + '; '.join(parse_errors[:10]))

        task.status = 'completed'
        task.finished_at = timezone.now()
        task.warnings = warnings
        task.save(update_fields=['status', 'finished_at', 'warnings'])
        logger.info('[code_analysis] component task %s completed, suggestions=%s', task_id, len(suggestions))
        return {'task_id': task_id, 'status': 'completed', 'suggestions': len(suggestions)}
    except Exception as e:
        logger.exception('[code_analysis] component task %s failed: %s', task_id, e)
        warnings.append(f'任务失败：{e}')
        task.status = 'failed'
        task.finished_at = timezone.now()
        task.warnings = warnings
        task.save(update_fields=['status', 'finished_at', 'warnings'])
        return {'task_id': task_id, 'status': 'failed', 'error': str(e)}


# ---------------- 变更影响检测 / Git 导入 ----------------

@shared_task
def auto_detect_changes(code_project_id, snapshot_id):
    """
    zip/git 导入后自动检测变更影响（仅当 ≥2 快照时执行）。
    失败仅记录日志，绝不抛出 celery 任务。
    """
    from .models import CodeProject

    try:
        code_project = CodeProject.objects.get(id=code_project_id)
        snapshot = code_project.snapshots.get(id=snapshot_id)
        if code_project.snapshots.count() < 2:
            return {'skipped': True, 'reason': 'only_one_snapshot'}
        from .linkage import detect_changes
        summary = detect_changes(code_project, snapshot)
        logger.info('[code_analysis] auto_detect_changes cp=%s snap=%s -> %s', code_project_id, snapshot_id, summary)
        return summary
    except Exception as e:
        logger.exception('[code_analysis] auto_detect_changes failed cp=%s snap=%s: %s', code_project_id, snapshot_id, e)
        return {'error': str(e)}


def _git_env():
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    env.setdefault('GIT_HTTP_LOW_SPEED_LIMIT', '1')
    env.setdefault('GIT_HTTP_LOW_SPEED_TIME', '300')
    return env


def _repo_dir(code_project) -> Path:
    """持久化 git 镜像目录。"""
    return Path(settings.MEDIA_ROOT) / 'code_projects' / str(code_project.id) / 'repo'


def _run_git(args, cwd=None, timeout=300):
    import subprocess
    return subprocess.run(
        args, cwd=cwd, env=_git_env(), timeout=timeout, capture_output=True, text=True,
    )


def _head_commit(repo_dir) -> str:
    rev = _run_git(['git', '-C', str(repo_dir), 'rev-parse', 'HEAD'], timeout=30)
    return (rev.stdout or '').strip() if rev.returncode == 0 else 'unknown'


def _ensure_mirror(code_project, git_url, branch):
    """
    确保持久化镜像存在且 origin 与 git_url 一致；返回 repo_dir。

    - 首次 / origin 变更：git clone --depth 1 [--branch X] url repo_dir
    - 后续：git fetch origin --prune + git reset --hard FETCH_HEAD
      （简化策略：直接重置工作区到远端目标分支，不做本地合并）
    """
    import shutil

    repo_dir = _repo_dir(code_project)
    mirror_ok = False
    if (repo_dir / '.git').exists():
        origin_url = _run_git(
            ['git', '-C', str(repo_dir), 'remote', 'get-url', 'origin'], timeout=30
        ).stdout.strip()
        mirror_ok = bool(origin_url) and origin_url == git_url

    if not mirror_ok:
        if repo_dir.exists():
            logger.info('[code_analysis] origin 与项目 git_url 不一致，重建镜像: %s -> %s',
                        _run_git(['git', '-C', str(repo_dir), 'remote', 'get-url', 'origin'], timeout=30).stdout.strip()[:80] if (repo_dir / '.git').exists() else '(空)',
                        git_url[:80])
            shutil.rmtree(repo_dir, ignore_errors=True)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        clone_cmd = ['git', 'clone', '--depth', '1']
        if branch and branch.lower() not in ('head', 'default'):
            clone_cmd += ['--branch', branch]
        clone_cmd += [git_url, str(repo_dir)]
        result = _run_git(clone_cmd, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f'git clone 失败: {(result.stderr or result.stdout).strip()[:500]}')
        return repo_dir

    # 镜像 origin 匹配：增量同步
    # 浅克隆需要补齐历史，保证行级 diff（git diff prev_commit new_commit）可用
    if (repo_dir / '.git' / 'shallow').exists():
        result = _run_git(['git', 'fetch', '--unshallow', 'origin'], cwd=repo_dir, timeout=600)
        if result.returncode != 0:
            logger.warning('[code_analysis] unshallow 失败，回退普通 fetch: %s',
                           (result.stderr or result.stdout).strip()[:300])
            result = _run_git(['git', 'fetch', 'origin', '--prune'], cwd=repo_dir, timeout=300)
    else:
        result = _run_git(['git', 'fetch', 'origin', '--prune'], cwd=repo_dir, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f'git fetch 失败: {(result.stderr or result.stdout).strip()[:500]}')
    result = _run_git(['git', 'reset', '--hard', 'FETCH_HEAD'], cwd=repo_dir, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f'git reset 失败: {(result.stderr or result.stdout).strip()[:500]}')
    if branch and branch.lower() not in ('head', 'default'):
        _run_git(['git', 'checkout', '-q', branch], cwd=repo_dir, timeout=60)
    return repo_dir


@shared_task
def run_git_import(snapshot_id):
    """
    将代码导入为快照（持久化镜像复用）：

    1. 确保镜像存在并同步到最新（首次 clone / 后续 fetch+reset）；
    2. 若 HEAD 与上一快照 commit_ref 相同 -> 删除新快照，返回 up_to_date；
    3. 变更时 ingest_directory 全量索引 -> 记录 commit_ref -> 自动检测变更。
    失败时删除该 snapshot 并返回错误（不抛出任务）。
    """
    import subprocess  # noqa: F401 (供 _run_git 使用)

    from .models import CodeProjectSnapshot

    try:
        snapshot = CodeProjectSnapshot.objects.select_related('code_project').get(id=snapshot_id)
    except CodeProjectSnapshot.DoesNotExist:
        return {'error': f'snapshot {snapshot_id} not found'}

    code_project = snapshot.code_project
    git_url = (code_project.git_url or '').strip()
    branch = (code_project.repo_branch or '').strip()

    if not git_url:
        snapshot.delete()
        return {'error': 'git_url 为空', 'status': 'failed'}

    try:
        repo_dir = _ensure_mirror(code_project, git_url, branch)
        commit = _head_commit(repo_dir)

        # up-to-date 判断（非首次导入）：HEAD 未变化则无操作
        prev_snapshot = (
            code_project.snapshots.exclude(id=snapshot.id).order_by('-version_no').first()
        )
        if prev_snapshot is not None and prev_snapshot.commit_ref and prev_snapshot.commit_ref == commit:
            snapshot.delete()
            return {'snapshot_id': snapshot.id, 'status': 'up_to_date', 'commit_ref': commit}

        from .ingest import ingest_directory
        file_count, skipped = ingest_directory(snapshot, repo_dir)

        snapshot.commit_ref = commit
        snapshot.save(update_fields=['commit_ref'])

        # 自动检测变更影响（≥2 快照时）
        if code_project.snapshots.count() >= 2:
            auto_detect_changes.delay(code_project.id, snapshot.id)

        logger.info('[code_analysis] git import ok snapshot=%s commit=%s files=%s', snapshot_id, commit, file_count)
        return {
            'snapshot_id': snapshot.id,
            'commit_ref': commit,
            'file_count': file_count,
            'skipped': skipped,
            'status': 'completed',
        }
    except Exception as e:
        logger.exception('[code_analysis] git import failed snapshot=%s: %s', snapshot_id, e)
        try:
            snapshot.delete()
        except Exception:
            pass
        return {'snapshot_id': snapshot_id, 'status': 'failed', 'error': str(e)}


@shared_task
def sync_all_git_code_projects():
    """
    定时同步所有 git 代码项目（django-celery-beat 每日调度）。

    对每个 git 项目：创建快照行并复用 run_git_import；
    HEAD 未变化时内部自动删除无操作快照。逐项目容错，绝不抛出。
    """
    from .models import CodeProject, CodeProjectSnapshot

    results = []
    projects = (
        CodeProject.objects.filter(source_type='git_url')
        .exclude(git_url__isnull=True)
        .exclude(git_url='')
    )
    for code_project in projects:
        try:
            snapshot = CodeProjectSnapshot.objects.create(
                code_project=code_project,
                version_no=code_project.snapshots.count() + 1,
                commit_ref='pending',
            )
            result = run_git_import.run(snapshot.id)
            results.append({'code_project_id': code_project.id, 'result': result})
            logger.info('[code_analysis] sync git project %s -> %s', code_project.id, result)
        except Exception as e:
            logger.exception('[code_analysis] sync git project %s failed: %s', code_project.id, e)
            results.append({'code_project_id': code_project.id, 'error': str(e)})
    return results
