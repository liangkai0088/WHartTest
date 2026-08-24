"""agent-browser 快照解析器（web-qa-bot src/utils/snapshot.ts 的 Python 移植）。

支持 3 种行格式：
1. 旧格式一：@e42 button "Submit" disabled checked
2. 旧格式二：textbox "账号" [ref=e1] enabled
3. agent-browser 0.34 格式：- heading "Example Domain" [level=1, ref=e1]

refs 双索引：@eN 与 role:name（小写）。状态解析 disabled/checked/selected/expanded/pressed；
value 解析兼容多种 value= / value: 片段格式。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ElementRef:
    """页面元素引用。"""

    id: str
    role: str
    name: str
    text: Optional[str] = None
    value: Optional[str] = None
    state: Dict[str, bool] = field(default_factory=dict)


@dataclass
class Snapshot:
    """页面快照。"""

    tree: str
    refs: Dict[str, ElementRef]
    url: str
    title: str
    console_events: List[dict] = field(default_factory=list)
    timestamp: float = 0.0


# 兼容 web-qa-bot 两种旧格式（含 ref 前缀 `- ` 时也可用 search 语义命中）
_REF_PATTERN = re.compile(
    r'(@e\d+)\s+(\w+)\s+"([^"]*)"(?:\s+(.+))?'
    r'|(\w+)\s+"([^"]+)"(?:\s+\[ref=(\w+)\])?(?:\s+(.+))?'
)

# agent-browser 0.34: - heading "Example Domain" [level=1, ref=e1]
_AB_PATTERN = re.compile(
    r'^\s*[-*]\s+([A-Za-z][\w-]*)(?:\s+"([^"]*)")?(?:\s+\[([^\]]*)\])?(?:\s+(.+))?$'
)

# 新式树形格式：@e9 [checkbox] checked / @e1 [a] "Home"
_AB_TREE_PATTERN = re.compile(
    r'^\s*(@e\d+)\s+\[([^\]]+)\](?:\s+"([^"]*)")?(?:\s+(.*))?$'
)

_STATE_FLAGS = ('disabled', 'checked', 'selected', 'expanded', 'pressed')


def parse_state(state_str: str) -> Dict[str, bool]:
    state: Dict[str, bool] = {}
    if state_str:
        for flag in _STATE_FLAGS:
            if flag in state_str:
                state[flag] = True
    return state


def parse_value(state_str: str) -> Optional[str]:
    patterns = [
        r'\bvalue\s*=\s*"([^"]*)"',
        r"\bvalue\s*=\s*'([^']*)'",
        r'\bvalue\s*:\s*"([^"]*)"',
        r"\bvalue\s*:\s*'([^']*)'",
        r'\bvalue\s*=\s*([^\]\s]+)',
        r'\bvalue\s*:\s*([^\]\s]+)',
    ]
    if not state_str:
        return None
    for pattern in patterns:
        m = re.search(pattern, state_str)
        if m:
            return m.group(1) or ''
    return None


def _extract_ref_from_attrs(attrs: str) -> Optional[str]:
    if not attrs:
        return None
    m = re.search(r'\bref\s*=\s*(\w+)', attrs)
    return m.group(1) if m else None


def parse_snapshot(output: str, url: str) -> Snapshot:
    """从 agent-browser 输出解析 Snapshot。"""
    refs: Dict[str, ElementRef] = {}
    lines = output.split('\n')

    for line in lines:
        if not line.strip():
            continue

        ref = None
        state_str = None

        # 格式 1/2：@e42 button "Submit" disabled | textbox "账号" [ref=e1] enabled
        m = _REF_PATTERN.search(line)
        if m and m.group(1):
            ref = ElementRef(
                id=m.group(1),
                role=m.group(2) or '',
                name=m.group(3) or '',
            )
            state_str = m.group(4)
        elif m and m.group(5) and m.group(7):
            ref = ElementRef(
                id=f'@{m.group(7)}',
                role=m.group(5) or '',
                name=m.group(6) or '',
            )
            state_str = m.group(8)

        if ref is None:
            # 格式 3：- heading "Example Domain" [level=1, ref=e1]
            m3 = _AB_PATTERN.match(line)
            if m3:
                rid = _extract_ref_from_attrs(m3.group(3) or '')
                if rid:
                    ref = ElementRef(
                        id=f'@{rid}',
                        role=m3.group(1) or '',
                        name=m3.group(2) or '',
                    )
                    state_str = m3.group(4) or (m3.group(3) or '')

        if ref is None:
            # 格式 4：@e9 [checkbox] checked
            m4 = _AB_TREE_PATTERN.match(line)
            if m4:
                ref = ElementRef(
                    id=m4.group(1),
                    role=m4.group(2) or '',
                    name=m4.group(3) or '',
                )
                state_str = m4.group(4) or (m4.group(2) or '')

        if ref is None:
            continue
        if state_str:
            ref.state = parse_state(state_str)
            ref.value = parse_value(state_str)

        if not ref.id or not ref.role or not ref.name:
            continue

        refs[ref.id] = ref
        name = ref.name.strip()
        if name:
            refs[f'{ref.role.lower()}:{name.lower()}'] = ref

    title = ''
    title_match = re.search(r'document\s+"([^"]+)"', output)
    if title_match:
        title = title_match.group(1) or ''

    return Snapshot(
        tree=output,
        refs=refs,
        url=url,
        title=title,
        timestamp=time.time(),
    )


def find_by_role(snapshot: Snapshot, role: str, name: Optional[str] = None) -> Optional[ElementRef]:
    for _, ref in snapshot.refs.items():
        if ref.role.lower() == role.lower():
            if not name or name.lower() in ref.name.lower():
                return ref
    return None


def find_all_by_role(snapshot: Snapshot, role: str) -> List[ElementRef]:
    results = []
    for key, ref in snapshot.refs.items():
        if key.startswith('@') and ref.role.lower() == role.lower():
            results.append(ref)
    return results


def find_by_text(snapshot: Snapshot, text: str, exact: bool = False) -> Optional[ElementRef]:
    search = text.lower()
    for key, ref in snapshot.refs.items():
        if not key.startswith('@'):
            continue
        ref_text = ref.name.lower()
        if (ref_text == search) if exact else (search in ref_text):
            return ref
    return None


def element_exists(snapshot: Snapshot, ref_or_selector: str) -> bool:
    if ref_or_selector.startswith('@'):
        return ref_or_selector in snapshot.refs
    if ':' in ref_or_selector:
        return ref_or_selector.lower() in snapshot.refs
    return find_by_text(snapshot, ref_or_selector) is not None


def resolve_ref(snapshot: Snapshot, selector: str) -> Optional[str]:
    if selector.startswith('@'):
        return selector if selector in snapshot.refs else None
    if ':' in selector:
        ref = snapshot.refs.get(selector.lower())
        return ref.id if ref else None
    found = find_by_text(snapshot, selector)
    return found.id if found else None


def snapshot_has_selector(snapshot: Snapshot, selector: str) -> bool:
    """waitFor 使用的宽松匹配：elementExists 或 name 子串匹配。"""
    if element_exists(snapshot, selector):
        return True
    needle = selector.lower()
    for key, ref in snapshot.refs.items():
        if key.startswith('@') and needle in ref.name.lower():
            return True
    return False


def detect_modals(snapshot: Snapshot) -> List[ElementRef]:
    modals = []
    for key, ref in snapshot.refs.items():
        if not key.startswith('@'):
            continue
        if (
            ref.role in ('dialog', 'alertdialog')
            or 'modal' in ref.name.lower()
            or 'popup' in ref.name.lower()
        ):
            modals.append(ref)
    return modals
