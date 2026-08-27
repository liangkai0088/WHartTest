"""覆盖率报告解析器，支持 Cobertura XML 与 LCOV 格式"""

import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _percent(covered: int, total: int) -> float:
    """计算覆盖率百分比，保留两位小数"""
    if not total:
        return 0.0
    return round(covered / total * 100, 2)


def parse_cobertura_xml(content: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """解析 Cobertura XML（coverage.py `coverage xml` / Jacoco 兼容）

    兼容两种行级格式：
    - coverage.py: <line number="1" hits="10"/>
    - Jacoco: <line nr="1" mi="0" ci="2" mb="0" cb="0"/>
    """
    root = ET.fromstring(content)
    files: List[Dict[str, Any]] = []
    lines_total = 0
    lines_covered = 0
    branches_total = 0
    branches_covered = 0

    for cls in root.iter("class"):
        filename = cls.get("filename") or cls.get("name") or ""
        if not filename:
            continue

        lines_detail: Dict[str, int] = {}
        f_lines_total = 0
        f_lines_covered = 0
        f_branches_total = 0
        f_branches_covered = 0

        for line in cls.findall("./lines/line"):
            number = line.get("number") or line.get("nr")
            if number is None:
                continue
            hits_raw = line.get("hits")
            if hits_raw is not None:
                hits = int(hits_raw)
                covered = hits > 0
            else:
                ci = int(line.get("ci") or 0)
                covered = ci > 0
                hits = 1 if covered else 0

            lines_detail[number] = hits
            f_lines_total += 1
            if covered:
                f_lines_covered += 1

            mb = int(line.get("mb") or 0)
            cb = int(line.get("cb") or 0)
            f_branches_total += mb + cb
            f_branches_covered += cb

        files.append(
            {
                "file_path": filename,
                "line_coverage": _percent(f_lines_covered, f_lines_total),
                "branch_coverage": (
                    _percent(f_branches_covered, f_branches_total)
                    if f_branches_total
                    else None
                ),
                "lines_total": f_lines_total,
                "lines_covered": f_lines_covered,
                "lines_detail": lines_detail,
            }
        )
        lines_total += f_lines_total
        lines_covered += f_lines_covered
        branches_total += f_branches_total
        branches_covered += f_branches_covered

    summary = {
        "lines_total": lines_total,
        "lines_covered": lines_covered,
        "line_coverage": _percent(lines_covered, lines_total),
        "branches_total": branches_total,
        "branches_covered": branches_covered,
        "branch_coverage": (
            _percent(branches_covered, branches_total) if branches_total else 0.0
        ),
        "files_total": len(files),
    }
    return summary, files


def parse_lcov(content: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """解析 LCOV 格式（Istanbul/nyc 产物）"""
    files: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("SF:"):
            current = {
                "file_path": line[3:],
                "lines_detail": {},
                "lines_total": 0,
                "lines_covered": 0,
            }
            files.append(current)
        elif line.startswith("DA:"):
            if current is None:
                continue
            parts = line[3:].split(",")
            if len(parts) >= 2:
                line_no = parts[0]
                hits = int(parts[1])
                current["lines_detail"][line_no] = hits
                current["lines_total"] += 1
                if hits > 0:
                    current["lines_covered"] += 1
        elif line == "end_of_record":
            current = None

    for f in files:
        f["line_coverage"] = _percent(f["lines_covered"], f["lines_total"])
        f["branch_coverage"] = None

    lines_total = sum(f["lines_total"] for f in files)
    lines_covered = sum(f["lines_covered"] for f in files)
    summary = {
        "lines_total": lines_total,
        "lines_covered": lines_covered,
        "line_coverage": _percent(lines_covered, lines_total),
        "branches_total": 0,
        "branches_covered": 0,
        "branch_coverage": 0.0,
        "files_total": len(files),
    }
    return summary, files


def parse_coverage_report(
    content: str, fmt: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """统一入口：按格式解析覆盖率报告"""
    if fmt == "cobertura":
        return parse_cobertura_xml(content)
    if fmt == "lcov":
        return parse_lcov(content)
    raise ValueError(f"不支持的覆盖率报告格式: {fmt}")


def _file_to_line_map(files: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """将文件级明细列表转为 {file_path: {行号字符串: hits}} 索引，便于增量对比。"""
    result: Dict[str, Dict[str, int]] = {}
    for f in files or []:
        path = f.get("file_path")
        if not path:
            continue
        detail = f.get("lines_detail")
        if not isinstance(detail, dict):
            detail = {}
        result[path] = {str(k): int(v) for k, v in detail.items()}
    return result


def compute_coverage_delta(
    base_files: List[Dict[str, Any]],
    current_files: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """对比基线文件明细与当前文件明细，计算增量覆盖率。

    增量口径：新增可执行行 = 当前有而基线无的行，或基线未覆盖(hits==0)而当前已覆盖的行；
    增量覆盖率 = 新增行中被覆盖的行 / 新增行总数。

    返回 (summary, files)。
    """
    base_map = _file_to_line_map(base_files)
    current_map = _file_to_line_map(current_files)

    files_result: List[Dict[str, Any]] = []
    new_lines_total = 0
    covered_new_lines_total = 0
    files_added = 0
    files_modified = 0
    files_unchanged = 0
    files_removed = 0

    current_paths = set(current_map.keys())
    base_paths = set(base_map.keys())

    for path in sorted(base_paths - current_paths):
        files_result.append({
            "file_path": path,
            "status": "removed",
            "new_lines": 0,
            "covered_new_lines": 0,
            "delta_coverage": 0.0,
            "removed_lines": len(base_map[path]),
        })
        files_removed += 1

    for path in sorted(current_paths):
        current_lines = current_map[path]
        base_lines = base_map.get(path)

        if base_lines is None:
            status = "added"
            files_added += 1
            new_lines = len(current_lines)
            covered_new_lines = sum(1 for h in current_lines.values() if h > 0)
            removed_lines = 0
        else:
            new_lines = 0
            covered_new_lines = 0
            for line_no, hits in current_lines.items():
                base_hits = base_lines.get(line_no)
                # 新增可执行行 = 当前有而基线无的行，或基线未覆盖(0)且当前已覆盖(>0)的改善行；
                # 基线未覆盖且当前仍未覆盖(0->0)不算新增。
                if base_hits is None or (base_hits == 0 and hits > 0):
                    new_lines += 1
                    if hits > 0:
                        covered_new_lines += 1
            removed_lines = len(set(base_lines) - set(current_lines))
            if new_lines == 0 and removed_lines == 0:
                status = "unchanged"
                files_unchanged += 1
            else:
                status = "modified"
                files_modified += 1

        delta_coverage = _percent(covered_new_lines, new_lines) if new_lines else 0.0
        new_lines_total += new_lines
        covered_new_lines_total += covered_new_lines

        files_result.append({
            "file_path": path,
            "status": status,
            "new_lines": new_lines,
            "covered_new_lines": covered_new_lines,
            "delta_coverage": delta_coverage,
            "removed_lines": removed_lines,
        })

    summary = {
        "new_lines_total": new_lines_total,
        "covered_new_lines": covered_new_lines_total,
        "delta_coverage": _percent(covered_new_lines_total, new_lines_total),
        "files_added": files_added,
        "files_modified": files_modified,
        "files_unchanged": files_unchanged,
        "files_removed": files_removed,
    }
    return summary, files_result


def build_delta_for_reports(base_report, current_report):
    """从两个 CoverageReport 对象计算增量覆盖率，返回 (summary, files)。

    入参为 model 实例，避免 services 层依赖 ORM 之外的结构，便于复用。
    """
    base_files = list(
        base_report.files.values("file_path", "lines_detail")
    )
    current_files = list(
        current_report.files.values("file_path", "lines_detail")
    )
    return compute_coverage_delta(base_files, current_files)
