import os
import uuid
from pathlib import Path, PurePosixPath


TRUE_VALUES = {'1', 'true', 'yes', 'on'}
FALSE_VALUES = {'0', 'false', 'no', 'off'}


def parse_bool_env(value: str | None) -> bool | None:
    """解析环境变量中的布尔值。"""
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def is_running_in_container() -> bool:
    """检测当前是否运行在容器环境中。"""
    explicit = parse_bool_env(os.environ.get('WHARTTEST_ACTUATOR_DOCKER'))
    if explicit is not None:
        return explicit

    return (
        Path('/.dockerenv').exists()
        or os.environ.get('container') == 'docker'
        or bool(os.environ.get('KUBERNETES_SERVICE_HOST'))
    )


def has_display_server() -> bool:
    """检测是否存在可用的图形显示环境。"""
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def should_force_headless() -> bool:
    """在容器内且无显示服务时，应强制使用无头模式。"""
    return is_running_in_container() and not has_display_server()


def _normalize_posix_path(value: str) -> str:
    return value.replace('\\', '/')


def _is_relative_to(path: PurePosixPath, parent: PurePosixPath) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_runtime_file_path(file_path: str) -> str:
    """将后端下发的文件路径转换为当前执行器可访问的路径。

    后端本地运行、执行器容器运行时，FileField.path 会是宿主机/WSL
    绝对路径，例如 /home/.../wharttest/data/media/xxx；容器内同一目录
    通过 compose 挂载在 /app/data。这里仅在容器模式下做路径映射。
    """
    if not file_path or not is_running_in_container():
        return file_path

    if os.path.exists(file_path):
        return file_path

    container_data_dir = os.environ.get('WHARTTEST_ACTUATOR_CONTAINER_DATA_DIR', '/app/data')
    host_data_dir = os.environ.get('WHARTTEST_ACTUATOR_HOST_DATA_DIR', '')

    normalized = _normalize_posix_path(file_path)
    source = PurePosixPath(normalized)
    target_root = PurePosixPath(_normalize_posix_path(container_data_dir))

    if host_data_dir:
        host_root = PurePosixPath(_normalize_posix_path(host_data_dir))
        if _is_relative_to(source, host_root):
            return str(target_root / source.relative_to(host_root))

    parts = source.parts
    if 'data' in parts:
        data_index = parts.index('data')
        suffix_parts = parts[data_index + 1:]
        if not suffix_parts:
            return str(target_root)
        return str(target_root / PurePosixPath(*suffix_parts))

    return file_path


# 通用上传文件搜索根目录（用于 resolve_upload_file 的兜底查找，
# 环境变量 WHARTTEST_ACTUATOR_UPLOAD_ROOTS 可追加自定义目录）
def _default_upload_roots() -> list[Path]:
    """默认上传文件搜索根目录。

    覆盖本机与容器两种运行形态，顺序即优先级：
    1. 工作目录（执行器启动目录）
    2. 执行器数据目录（./data, ./data/uploads）
    3. 仓库根下 data 目录及其 media 子目录（本机开发形态）
    4. 容器数据目录 /app/data（容器内开发/生产形态）
    """
    roots: list[Path] = []
    cwd = Path.cwd()

    def add(p: Path) -> None:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key not in {str(_resolve_safe(r)) for r in roots}:
            roots.append(p)

    add(cwd)
    add(cwd / 'data')
    add(cwd / 'data' / 'uploads')
    add(cwd / 'data' / 'runtime_uploads')
    add(cwd.parent / 'data' if cwd.parent != cwd else Path('..') / 'data')
    add(cwd.parent / 'data' / 'media' if cwd.parent != cwd else Path('..') / 'data' / 'media')
    add(Path('/app/data'))
    add(Path('/app/data/media'))
    return roots


def _resolve_safe(p: Path) -> str:
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def resolve_upload_file(value: str, extra_roots: list[str] | None = None) -> str | None:
    """通用上传文件路径解析。

    规则（对于 fill 文件上传框、upload 类操作传参都适用）：
    1. 绝对路径且文件存在 -> 直接返回
    2. 相对于执行器工作目录存在 -> 返回
    3. 裸文件名/相对名 -> 在各搜索根目录下按 basename 查找（含子目录）
    4. 找不到 -> 返回 None（不硬编码具体页面/项目路径）

    Args:
        value: 用户提供的文件路径（绝对路径/相对路径/文件名）
        extra_roots: 额外搜索根目录

    Returns:
        解析后的绝对路径，找不到时返回 None
    """
    if not value or not str(value).strip():
        return None

    candidate = str(value).strip()

    # 1. 绝对路径直接校验
    path = Path(candidate)
    if path.is_absolute():
        if path.is_file():
            return str(path)
        # 容器模式下后端下发的宿主机路径需要映射
        mapped = resolve_runtime_file_path(candidate)
        mapped_path = Path(mapped)
        if mapped_path.is_file():
            return str(mapped)
        # 显式指定的绝对路径不存在：不做 basename 搜索（避免同名文件误匹配），
        # 直接尝试占位夹具生成
        if is_auto_fixture_enabled():
            return generate_upload_fixture(candidate)
        return None

    # 2. 相对当前工作目录
    if path.is_file():
        return str(path)

    # 3. 在各搜索根目录下查找
    roots = _default_upload_roots()
    for extra in extra_roots or []:
        if extra and str(extra).strip():
            roots.append(Path(str(extra).strip()))

    env_roots = os.environ.get('WHARTTEST_ACTUATOR_UPLOAD_ROOTS', '')
    for part in env_roots.split(os.pathsep):
        if part.strip():
            roots.append(Path(part.strip()))

    # 精确相对路径匹配
    for root in roots:
        try:
            candidate_path = root / candidate
            if candidate_path.is_file():
                return str(candidate_path)
        except OSError:
            continue

    # basename 查找（含子目录，避免无限深搜）
    basename = os.path.basename(candidate)
    if not basename or basename in {'.', '..'}:
        return None

    for root in roots:
        try:
            if not root.is_dir():
                continue
            # 起步全局查找，找到即返回（优先顶层）
            matches = sorted(
                (p for p in root.rglob(basename) if p.is_file()),
                key=lambda p: len(p.relative_to(root).parts),
            )
            if matches:
                return str(matches[0])
        except OSError:
            continue

    # 4. 自动夹具兜底：文件不存在时生成占位文件（通用能力，默认开启）
    if is_auto_fixture_enabled():
        return generate_upload_fixture(candidate)

    return None


# ============================================================================
# 自动夹具（缺失上传文件时的占位生成与清理）
# ============================================================================

# 本进程内自动生成的占位夹具: 文件路径 -> 所属目录（供用例结束后清理）
_AUTO_FIXTURES: dict[str, str] = {}


def is_auto_fixture_enabled() -> bool:
    """缺失上传文件时是否自动生成占位夹具。

    默认开启；可通过环境变量 WHARTTEST_ACTUATOR_AUTO_FIXTURE=0/false 关闭。
    """
    value = parse_bool_env(os.environ.get('WHARTTEST_ACTUATOR_AUTO_FIXTURE'))
    return value is not False


def _generated_fixtures_dir() -> Path:
    configured = os.environ.get('WHARTTEST_ACTUATOR_GENERATED_DIR', '').strip()
    if configured:
        return Path(configured)
    return Path.cwd() / 'data' / 'runtime_uploads' / 'generated'


def generate_upload_fixture(value: str) -> str | None:
    """为缺失的上传文件生成占位夹具。

    保留原文件名的 basename（扩展名对格式校验类用例至关重要），
    写入独立临时子目录避免并发用例互相覆盖。

    Args:
        value: 用户引用的文件名（如 test_upload.exe）

    Returns:
        生成文件的绝对路径；失败时返回 None
    """
    name = os.path.basename(str(value).strip())
    if not name or name in {'.', '..'}:
        return None

    try:
        sub = _generated_fixtures_dir() / uuid.uuid4().hex[:12]
        sub.mkdir(parents=True, exist_ok=True)
        target = sub / name
        target.write_bytes(b'placeholder file auto-generated by actuator')
        _AUTO_FIXTURES[str(target)] = str(sub)
        return str(target)
    except OSError:
        return None


def auto_fixtures_snapshot() -> dict[str, str]:
    """返回当前自动夹具注册表快照，供用例执行时界定清理范围。"""
    return dict(_AUTO_FIXTURES)


def cleanup_generated_upload_files(since: dict[str, str] | None = None) -> None:
    """清理自动生成的占位夹具文件。

    Args:
        since: 快照（auto_fixtures_snapshot 返回值）。仅清理快照之后新增的
               文件，避免误删其他并发用例仍在使用中的夹具。
               为 None 时清理全部。
    """
    global _AUTO_FIXTURES
    if since is None:
        entries = dict(_AUTO_FIXTURES)
        _AUTO_FIXTURES.clear()
    else:
        entries = {p: d for p, d in _AUTO_FIXTURES.items() if p not in since}
        for p in entries:
            _AUTO_FIXTURES.pop(p, None)

    for path_str, subdir_str in entries.items():
        path = Path(path_str)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            sub = Path(subdir_str)
            if sub.exists() and sub.is_dir():
                sub.rmdir()
        except OSError:
            pass
