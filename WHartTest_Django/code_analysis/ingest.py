"""zip 代码包安全解压 + 文件索引入库。"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError

MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50MB
MAX_FILES = 2000
MAX_TOTAL_SIZE = 50 * 1024 * 1024
MAX_CONTENT_SIZE = 200 * 1024  # 200KB，超过不存储正文

SKIP_DIRS = {
    'node_modules', '.git', 'dist', 'images', '__pycache__', '.idea', '.vscode',
    'venv', '.venv', 'target', 'build', 'coverage', '.next', 'Pods', '.svn',
}

# 大于 200KB 的锁文件整体跳过
LOCK_FILES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
    'Pipfile.lock', 'Cargo.lock', 'composer.lock', 'go.sum',
    'npm-shrinkwrap.json', 'Gemfile.lock', 'flake.lock', 'uv.lock',
}

LANGUAGE_BY_EXT = {
    '.py': 'python', '.js': 'javascript', '.jsx': 'javascript', '.ts': 'typescript',
    '.tsx': 'typescript', '.vue': 'vue', '.java': 'java', '.go': 'go', '.rs': 'rust',
    '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.hpp': 'cpp', '.cs': 'csharp',
    '.rb': 'ruby', '.php': 'php', '.swift': 'swift', '.kt': 'kotlin',
    '.kts': 'kotlin', '.scala': 'scala', '.sh': 'shell', '.bash': 'shell',
    '.zsh': 'shell', '.ps1': 'powershell', '.html': 'html', '.htm': 'html',
    '.css': 'css', '.scss': 'scss', '.less': 'less', '.sass': 'scss',
    '.json': 'json', '.json5': 'json', '.yaml': 'yaml', '.yml': 'yaml',
    '.xml': 'xml', '.toml': 'toml', '.md': 'markdown', '.rst': 'markdown',
    '.txt': 'text', '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini',
    '.sql': 'sql', '.proto': 'protobuf', '.gradle': 'groovy', '.groovy': 'groovy',
    '.properties': 'properties', '.env': 'dotenv', '.dockerfile': 'dockerfile',
    '.svg': 'svg', '.graphql': 'graphql', '.lock': 'text',
}


def infer_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == '.dockerfile':
        return 'dockerfile'
    if Path(path).name.lower() == 'dockerfile':
        return 'dockerfile'
    if Path(path).name == '.env':
        return 'dotenv'
    return LANGUAGE_BY_EXT.get(ext, '')


def _is_binary(path: str) -> bool:
    """通过探测前 8KB 是否包含 NUL 字节判断二进制文件。"""
    try:
        with open(path, 'rb') as fh:
            head = fh.read(8192)
        return b'\x00' in head
    except OSError:
        return True


def _safe_extract(zf: zipfile.ZipFile, dest_dir: str) -> None:
    """安全解压：拒绝绝对路径 / .. / 盘符 / 符号链接，防止 Zip Slip。"""
    dest_path = Path(dest_dir).resolve(strict=False)
    file_count = 0
    total_size = 0

    for info in zf.infolist():
        name = (info.filename or '').replace('\\', '/')
        if not name or name.endswith('/'):
            continue

        file_count += 1
        if file_count > MAX_FILES:
            raise ValidationError('zip 文件包含过多文件')
        total_size += int(getattr(info, 'file_size', 0) or 0)
        if total_size > MAX_TOTAL_SIZE:
            raise ValidationError('zip 解压后总大小超出限制')

        posix = PurePosixPath(name)
        if posix.is_absolute() or any(part == '..' for part in posix.parts):
            raise ValidationError('zip 文件包含非法路径')
        if posix.parts and ':' in posix.parts[0]:
            raise ValidationError('zip 文件包含非法路径')

        mode = (info.external_attr or 0) >> 16
        if stat.S_ISLNK(mode):
            raise ValidationError('zip 文件包含不支持的符号链接')

        target_path = (dest_path / Path(*posix.parts)).resolve(strict=False)
        try:
            if os.path.commonpath([str(dest_path), str(target_path)]) != str(dest_path):
                raise ValidationError('zip 文件包含非法路径')
        except ValueError:
            raise ValidationError('zip 文件包含非法路径')

        zf.extract(info, str(dest_path))


def ingest_zip(zip_file, code_project, creator):
    """
    解压 zip 并写入 CodeProjectSnapshot + CodeFile 索引。

    返回 (snapshot, file_count, skipped_count)。
    """
    from .models import CodeProjectSnapshot

    # 上传体积上限校验
    zip_file.seek(0, os.SEEK_END)
    file_size = zip_file.tell()
    zip_file.seek(0)
    if file_size > MAX_ZIP_SIZE:
        raise ValidationError('zip 文件超过 50MB 限制')

    version_no = (
        CodeProjectSnapshot.objects.filter(code_project=code_project).count() + 1
    )
    snapshot = CodeProjectSnapshot.objects.create(
        code_project=code_project,
        version_no=version_no,
        created_by=creator,
    )

    base_dir = (
        Path(settings.MEDIA_ROOT)
        / 'code_projects'
        / str(code_project.id)
        / str(snapshot.id)
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(zip_file, 'r') as zf:
                _safe_extract(zf, tmp)
        except zipfile.BadZipFile:
            snapshot.delete()
            raise ValidationError('无效的 zip 文件')

        file_count, skipped = ingest_directory(snapshot, tmp)

    return snapshot, file_count, skipped


def ingest_directory(snapshot, directory):
    """
    索引一个目录中的源码文件到 snapshot（zip 解压目录 / git 克隆目录共用）。

    返回 (file_count, skipped_count)，并更新 code_project.current_snapshot。
    """
    from .models import CodeFile

    code_files = []
    skipped = 0
    for root, dirs, fnames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in sorted(fnames):
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, directory).replace(os.sep, '/')

            if _is_binary(abs_path):
                skipped += 1
                continue

            size = os.path.getsize(abs_path)
            if size > MAX_CONTENT_SIZE and fname.lower() in LOCK_FILES:
                skipped += 1
                continue

            content = None
            content_stored = False
            if size <= MAX_CONTENT_SIZE:
                try:
                    with open(abs_path, 'r', encoding='utf-8', errors='replace') as fh:
                        content = fh.read()
                    content_stored = True
                except Exception:
                    content = None
                    content_stored = False

            sha = hashlib.sha256()
            with open(abs_path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    sha.update(chunk)

            code_files.append(CodeFile(
                snapshot=snapshot,
                path=rel_path,
                language=infer_language(rel_path),
                sha256=sha.hexdigest(),
                size=size,
                content=content,
                content_stored=content_stored,
            ))

    CodeFile.objects.bulk_create(code_files)

    code_project = snapshot.code_project
    code_project.current_snapshot = snapshot
    code_project.save(update_fields=['current_snapshot', 'updated_at'])

    return len(code_files), skipped


def copy_to_media(zip_file, dest_dir: str):
    """将上传文件落盘到目标目录（供其他逻辑使用）。"""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / zip_file.name
    with open(out, 'wb+') as fh:
        for chunk in zip_file.chunks():
            fh.write(chunk)
    return out
