"""测试用例 <-> 代码关联、变更影响检测、用例名称解析。"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('code_analysis')

MAX_DIFF_FILES = 20
MAX_DIFF_HUNKS = 50

_HUNK_HEADER_RE = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def compare_snapshots(prev_snapshot, new_snapshot):
    """
    对比两个快照的 CodeFile（按 path），返回变更列表。

    每项: (diff_status, path, old_sha256, new_sha256, size_delta)
    """
    from .models import CodeFile

    prev_files = {f.path: f for f in CodeFile.objects.filter(snapshot=prev_snapshot)}
    new_files = {f.path: f for f in CodeFile.objects.filter(snapshot=new_snapshot)}

    changes = []
    for path in sorted(set(new_files) - set(prev_files)):
        nf = new_files[path]
        changes.append(('added', path, None, nf.sha256, nf.size))
    for path in sorted(set(prev_files) - set(new_files)):
        pf = prev_files[path]
        changes.append(('deleted', path, pf.sha256, None, -pf.size))
    for path in sorted(set(prev_files) & set(new_files)):
        pf, nf = prev_files[path], new_files[path]
        if pf.sha256 != nf.sha256:
            changes.append(('modified', path, pf.sha256, nf.sha256, nf.size - pf.size))
    return changes


def _diff_hunks(repo_dir, prev_commit, new_commit, path, max_hunks=MAX_DIFF_HUNKS):
    """对单个文件执行 git diff --unified=0，解析 hunk 列表。"""
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    result = subprocess.run(
        ['git', '-C', str(repo_dir), 'diff', '--unified=0', '--no-color',
         prev_commit, new_commit, '--', path],
        env=env, timeout=60, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:500])

    hunks = []
    current = None
    for line in (result.stdout or '').splitlines():
        m = _HUNK_HEADER_RE.match(line)
        if m:
            current = {
                'old_start': int(m.group(1)),
                'old_lines': int(m.group(2) or '0'),
                'new_start': int(m.group(3)),
                'new_lines': int(m.group(4) or '0'),
                'added': 0,
                'removed': 0,
            }
            hunks.append(current)
            if len(hunks) >= max_hunks:
                break
            continue
        if current is None:
            continue
        if line.startswith('+') and not line.startswith('+++'):
            current['added'] += 1
        elif line.startswith('-') and not line.startswith('---'):
            current['removed'] += 1
    return hunks


def _git_diff_summaries(code_project, prev_snapshot, new_snapshot, paths):
    """
    对 git 项目计算行级差异摘要（仅针对有 TestCodeLink 的变更文件）。

    返回 {path: {'hunks': [...], 'total_added': N, 'total_removed': N}}；
    任何 git 相关失败仅记录日志，返回空 dict，绝不抛出。
    """
    prev_commit = prev_snapshot.commit_ref
    new_commit = new_snapshot.commit_ref
    if not prev_commit or not new_commit or prev_commit == new_commit or not paths:
        return {}

    repo_dir = (
        Path(settings.MEDIA_ROOT) / 'code_projects' / str(code_project.id) / 'repo'
    )
    if not (repo_dir / '.git').exists():
        logger.warning('[code_analysis] repo mirror 不存在，跳过行级 diff: cp=%s', code_project.id)
        return {}

    summaries = {}
    for path in sorted(paths)[:MAX_DIFF_FILES]:
        try:
            hunks = _diff_hunks(repo_dir, prev_commit, new_commit, path)
            if not hunks:
                continue
            summaries[path] = {
                'hunks': hunks,
                'total_added': sum(h['added'] for h in hunks),
                'total_removed': sum(h['removed'] for h in hunks),
            }
        except Exception as e:
            logger.warning('[code_analysis] git diff 失败 %s: %s', path, e)
    return summaries


def detect_changes(code_project, new_snapshot):
    """
    检测 code_project 中新快照相对上一快照的变更，并对已关联的测试用例：
    - 将相关 TestCodeLink 置为 outdated；
    - 创建 ChangeImpactRecord（git 项目附带行级 diff_summary）。

    返回摘要 dict。仅在 celery 任务/显式接口中调用，异常自行处理。
    """
    from .models import ChangeImpactRecord, CodeFile, TestCodeLink

    prev_snapshot = (
        code_project.snapshots.exclude(id=new_snapshot.id).order_by('-version_no').first()
    )
    if prev_snapshot is None:
        return {
            'changed_files': 0,
            'added': 0,
            'modified': 0,
            'deleted': 0,
            'impacted_links': 0,
            'records_created': 0,
            'prev_snapshot_id': None,
            'new_snapshot_id': new_snapshot.id,
        }

    new_files = {f.path: f for f in CodeFile.objects.filter(snapshot=new_snapshot)}
    changes = compare_snapshots(prev_snapshot, new_snapshot)

    # git 项目：仅对存在关联的变更文件计算行级差异
    diff_summaries = {}
    if code_project.source_type == 'git_url' and changes:
        linked_paths = set(
            TestCodeLink.objects.filter(
                project=code_project.project,
                code_file__path__in=[c[1] for c in changes],
                status='linked',
            ).values_list('code_file__path', flat=True)
        )
        if linked_paths:
            diff_summaries = _git_diff_summaries(
                code_project, prev_snapshot, new_snapshot, list(linked_paths)
            )

    impacted_link_ids = set()
    records_created = 0
    with transaction.atomic():
        for diff_status, path, old_sha, new_sha, size_delta in changes:
            links = list(
                TestCodeLink.objects.filter(
                    project=code_project.project,
                    code_file__path=path,
                    status='linked',
                ).only('id', 'testcase_type', 'testcase_id')
            )
            if not links:
                continue
            link_ids = [l.id for l in links]
            impacted_link_ids.update(link_ids)
            TestCodeLink.objects.filter(id__in=link_ids).update(
                status='outdated',
                last_verified_at=timezone.now(),
                updated_at=timezone.now(),
            )
            for l in links:
                ChangeImpactRecord.objects.create(
                    snapshot=new_snapshot,
                    code_file=new_files.get(path) if diff_status != 'deleted' else None,
                    path=path,
                    testcase_type=l.testcase_type,
                    testcase_id=l.testcase_id,
                    diff_status=diff_status,
                    old_sha256=old_sha,
                    new_sha256=new_sha,
                    size_delta=size_delta,
                    diff_summary=diff_summaries.get(path, {}),
                )
                records_created += 1

    return {
        'changed_files': len(changes),
        'added': sum(1 for c in changes if c[0] == 'added'),
        'modified': sum(1 for c in changes if c[0] == 'modified'),
        'deleted': sum(1 for c in changes if c[0] == 'deleted'),
        'impacted_links': len(impacted_link_ids),
        'records_created': records_created,
        'prev_snapshot_id': prev_snapshot.id,
        'new_snapshot_id': new_snapshot.id,
    }


def resolve_testcase_name(testcase_type, testcase_id):
    """
    解析 testcase 名称：
    - functional -> testcases.TestCase.name
    - api        -> api_testcases.ApiTestCase.name
    - ui         -> ui_automation.UiElement.name（优先），回退 UiTestCase.name
    """
    try:
        if testcase_type == 'functional':
            from testcases.models import TestCase
            return TestCase.objects.filter(id=testcase_id).values_list('name', flat=True).first()
        if testcase_type == 'api':
            from api_testcases.models import ApiTestCase
            return ApiTestCase.objects.filter(id=testcase_id).values_list('name', flat=True).first()
        if testcase_type == 'ui':
            from ui_automation.models import UiElement
            el = UiElement.objects.filter(id=testcase_id).values_list('name', flat=True).first()
            if el:
                return el
            from ui_automation.models import UiTestCase
            return UiTestCase.objects.filter(id=testcase_id).values_list('name', flat=True).first()
    except Exception as e:
        logger.warning('[code_analysis] resolve_testcase_name failed: %s', e)
    return None
