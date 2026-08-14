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
