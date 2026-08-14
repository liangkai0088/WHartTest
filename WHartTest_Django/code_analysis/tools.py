"""Agent 读码工具（供 mcp_tools.TOOL_REGISTRY 注册）。

每个工具签名: (request_user, arguments: dict) -> dict。
权限：项目成员（superuser 直接放行）；违反时抛 PermissionError。
"""

from __future__ import annotations

import re

MAX_LIST_FILES = 500
MAX_READ_CHARS = 20000
MAX_GREP_RESULTS = 50


def _require_project_member(request_user, project_id):
    if not request_user or not request_user.is_authenticated:
        raise PermissionError('User is not authenticated.')
    if request_user.is_superuser:
        return
    from projects.models import ProjectMember
    if not ProjectMember.objects.filter(
        project_id=project_id,
        user=request_user,
        role__in=['owner', 'admin', 'member'],
    ).exists():
        raise PermissionError('User is not a member of this project.')


def _get_code_project(project_id, code_project_id):
    from .models import CodeProject
    try:
        return CodeProject.objects.get(id=code_project_id, project_id=project_id)
    except CodeProject.DoesNotExist:
        raise ValueError(f'code_project {code_project_id} not found in project {project_id}')


def _latest_snapshot(code_project):
    return code_project.snapshots.order_by('-version_no').first()


def code_list_files(request_user, arguments):
    """列出代码项目最新快照中的文件（路径/语言/大小），最多 500 个。"""
    project_id = int(arguments.get('project_id') or 0)
    code_project_id = int(arguments.get('code_project_id') or 0)
    path_prefix = str(arguments.get('path_prefix') or '')

    _require_project_member(request_user, project_id)
    code_project = _get_code_project(project_id, code_project_id)
    snapshot = _latest_snapshot(code_project)
    if snapshot is None:
        return {'project_id': project_id, 'code_project_id': code_project_id, 'snapshot_id': None, 'total': 0, 'files': []}

    qs = snapshot.files.filter(is_deleted=False)
    if path_prefix:
        qs = qs.filter(path__startswith=path_prefix)
    files = list(qs.order_by('path').values('path', 'language', 'size')[:MAX_LIST_FILES])
    return {
        'project_id': project_id,
        'code_project_id': code_project_id,
        'snapshot_id': snapshot.id,
        'version_no': snapshot.version_no,
        'total': len(files),
        'files': files,
    }


def code_read_file(request_user, arguments):
    """读取代码项目最新快照中指定文件的内容（默认截断 20000 字符）。"""
    project_id = int(arguments.get('project_id') or 0)
    code_project_id = int(arguments.get('code_project_id') or 0)
    path = str(arguments.get('path') or '')
    try:
        max_chars = int(arguments.get('max_chars') or MAX_READ_CHARS)
    except (TypeError, ValueError):
        max_chars = MAX_READ_CHARS
    max_chars = max(200, min(max_chars, 200000))

    _require_project_member(request_user, project_id)
    code_project = _get_code_project(project_id, code_project_id)
    snapshot = _latest_snapshot(code_project)
    if snapshot is None:
        raise ValueError('该代码项目还没有任何快照')

    cf = snapshot.files.filter(path=path, is_deleted=False).first()
    if cf is None:
        raise ValueError(f'文件不存在: {path}')

    content = cf.content or ''
    truncated = len(content) > max_chars
    return {
        'project_id': project_id,
        'code_project_id': code_project_id,
        'snapshot_id': snapshot.id,
        'path': cf.path,
        'language': cf.language,
        'size': cf.size,
        'content': content[:max_chars],
        'truncated': truncated,
        'content_stored': cf.content_stored,
    }


def code_grep_code(request_user, arguments):
    """在代码项目最新快照中按正则检索文件内容。"""
    project_id = int(arguments.get('project_id') or 0)
    code_project_id = int(arguments.get('code_project_id') or 0)
    pattern = str(arguments.get('pattern') or '')
    path_prefix = str(arguments.get('path_prefix') or '')
    try:
        max_results = int(arguments.get('max_results') or MAX_GREP_RESULTS)
    except (TypeError, ValueError):
        max_results = MAX_GREP_RESULTS
    max_results = max(1, min(max_results, 200))

    if not pattern:
        raise ValueError('pattern 不能为空')

    _require_project_member(request_user, project_id)
    code_project = _get_code_project(project_id, code_project_id)
    snapshot = _latest_snapshot(code_project)
    if snapshot is None:
        return {'project_id': project_id, 'code_project_id': code_project_id, 'snapshot_id': None, 'total': 0, 'matches': []}

    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ValueError(f'无效的正则表达式: {e}')

    qs = snapshot.files.filter(is_deleted=False, content_stored=True)
    if path_prefix:
        qs = qs.filter(path__startswith=path_prefix)

    matches = []
    for cf in qs.iterator(chunk_size=200):
        if not cf.content:
            continue
        for line_no, line in enumerate(cf.content.splitlines(), start=1):
            if rx.search(line):
                matches.append({
                    'path': cf.path,
                    'line_no': line_no,
                    'line': line[:500],
                })
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    return {
        'project_id': project_id,
        'code_project_id': code_project_id,
        'snapshot_id': snapshot.id,
        'pattern': pattern,
        'total': len(matches),
        'matches': matches,
    }


def code_get_changed_files(request_user, arguments):
    """返回代码项目最新快照相对上一快照的变更文件列表。"""
    from .linkage import compare_snapshots

    project_id = int(arguments.get('project_id') or 0)
    code_project_id = int(arguments.get('code_project_id') or 0)

    _require_project_member(request_user, project_id)
    code_project = _get_code_project(project_id, code_project_id)
    latest = _latest_snapshot(code_project)
    if latest is None:
        return {'project_id': project_id, 'code_project_id': code_project_id, 'total': 0, 'changes': []}
    prev = code_project.snapshots.exclude(id=latest.id).order_by('-version_no').first()
    if prev is None:
        return {
            'project_id': project_id, 'code_project_id': code_project_id,
            'snapshot_id': latest.id, 'prev_snapshot_id': None, 'total': 0, 'changes': [],
        }

    changes = [
        {
            'path': path,
            'diff_status': diff_status,
            'old_sha256': old_sha,
            'new_sha256': new_sha,
            'size_delta': size_delta,
        }
        for diff_status, path, old_sha, new_sha, size_delta in compare_snapshots(prev, latest)
    ]
    return {
        'project_id': project_id,
        'code_project_id': code_project_id,
        'snapshot_id': latest.id,
        'prev_snapshot_id': prev.id,
        'total': len(changes),
        'changes': changes,
    }


def get_code_analysis_tools():
    """返回 code_analysis 注册到 agent 的工具映射。"""
    return {
        'code_list_files': code_list_files,
        'code_read_file': code_read_file,
        'code_grep_code': code_grep_code,
        'code_get_changed_files': code_get_changed_files,
    }
