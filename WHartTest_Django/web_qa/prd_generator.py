"""PRD → Midscene YAML 生成器。

PRD 文本（RequirementDocument 提取或原始文本）→ LLM → Midscene YAML。
系统提示词包含 midscene yaml schema + 定位约定 + 登录示例；
严格 fenced yaml 输出；yaml_loader 校验；1 次带错误反馈的重试。
"""

from __future__ import annotations

import json
import logging
import re

import yaml

from .llm import LlmError, chat_completions

logger = logging.getLogger('web_qa')

SYSTEM_PROMPT = """你是资深 Web UI 自动化测试工程师。根据 PRD 需求文档，生成一份 Midscene.js 的 YAML 自动化测试脚本。

## Midscene YAML 规范（严格遵循）
```yaml
target:
  url: https://被测系统地址
  viewportWidth: 1440
  viewportHeight: 900
tasks:
  - name: 用例名称
    flow:
      - ai: "自然语言操作描述"
      - aiAssert: "自然语言断言描述"
      - aiQuery: "提取数据的自然语言描述"
      - sleep: 1000
```

规则：
1. `target.url` 必须填写被测系统 baseUrl。
2. 每个 `task` 的 `name` 描述测试场景；`flow` 为步骤数组。
3. `ai:` 表示执行操作；`aiAssert:` 表示断言页面状态；`aiQuery:` 表示提取数据（返回 JSON）；`sleep` 单位为毫秒。
4. 步骤用简洁清晰的自然语言，必须指明元素（如"点击登录按钮"、"在账号输入框输入 admin"）。
5. 至少覆盖：正常流程、关键断言、边界/异常（如校验错误提示）。
6. 只输出 YAML，使用 ```yaml ... ``` 代码块包裹，不要输出任何解释文字。

## 登录示例
```yaml
target:
  url: http://211.90.198.39:8880
  viewportWidth: 1440
  viewportHeight: 900
tasks:
  - name: 登录成功
    flow:
      - ai: "打开登录页"
      - ai: "在账号输入框输入用户名 admin"
      - ai: "在密码输入框输入密码 Admin@123"
      - ai: "点击登录按钮"
      - aiAssert: "页面跳转到首页，且显示欢迎信息"
      - ai: "点击退出登录按钮"
  - name: 密码错误提示
    flow:
      - ai: "输入错误密码后点击登录按钮"
      - aiAssert: "页面出现密码错误的提示信息"
```
"""


def build_prompt(prd_text: str, base_url: str = '') -> str:
    return (
        f'被测系统 baseUrl: {base_url or "（未指定，请从 PRD 中推断或使用 http://localhost）"}\n\n'
        '## PRD 需求文档\n'
        f'{prd_text[:12000]}\n\n'
        '请根据上述 PRD 生成 Midscene YAML 测试脚本。'
    )


def extract_prd_text(requirement_document_id=None, text: str = '', project=None) -> str:
    """提取 PRD 文本：原始 text 优先，其次 RequirementDocument.content。"""
    if text and text.strip():
        return text.strip()

    if requirement_document_id:
        from requirements.models import RequirementDocument

        doc = RequirementDocument.objects.filter(id=requirement_document_id).first()
        if doc is None:
            raise ValueError('需求文档不存在')
        if doc.content and doc.content.strip():
            return doc.content.strip()
        # 从文件提取（复用 requirements.services.DocumentProcessor）
        from requirements.services import DocumentProcessor

        try:
            content = DocumentProcessor().extract_content(doc)
        except Exception as e:  # noqa: BLE001
            logger.warning('[web_qa] PRD 文档内容提取失败: %s', e)
            content = doc.content or ''
        if not content.strip():
            raise ValueError('需求文档无可用内容')
        return content.strip()

    raise ValueError('请提供 text 或 requirement_document_id')


def extract_yaml_block(content: str) -> str:
    """从 LLM 响应提取 ```yaml 代码块。"""
    m = re.search(r'```(?:ya?ml)?\s*\n?([\s\S]*?)```', content)
    if m:
        return m.group(1).strip()
    # 无代码块时：从首个 top-level 键（target:/tasks: 行）开始截取
    lines = content.split('\n')
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('target:') or stripped.startswith('tasks:'):
            start = i
            break
    if start is not None:
        body = '\n'.join(lines[start:]).strip()
        # 容忍尾部非 yaml 文本：解析失败时逐行裁剪重试
        body_lines = body.split('\n')
        for _ in range(min(len(body_lines), 8)):
            try:
                yaml.safe_load('\n'.join(body_lines))
                return '\n'.join(body_lines).strip()
            except yaml.YAMLError:
                if not body_lines:
                    break
                body_lines = body_lines[:-1]
        return '\n'.join(body_lines).strip()
    return content.strip()


def validate_midscene_yaml(content: str) -> None:
    """用 yaml_loader 兼容方式校验（target + tasks）。"""
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        raise ValueError(f'YAML 语法错误: {e}')
    if not isinstance(data, dict):
        raise ValueError('YAML 顶层必须是对象')
    if 'target' not in data and 'web' not in data and 'page' not in data and 'browser' not in data:
        raise ValueError('缺少 target.url 配置')
    if not isinstance(data.get('tasks'), list) or not data['tasks']:
        raise ValueError('缺少 tasks（必须为数组）')
    for i, task in enumerate(data['tasks']):
        if not isinstance(task, dict) or not task.get('name'):
            raise ValueError(f'tasks[{i}]: 缺少 name')
        if not isinstance(task.get('flow'), list) or not task['flow']:
            raise ValueError(f'tasks[{i}] "{task.get("name")}": flow 必须为数组')


def generate_midscene_yaml(prd_text: str, base_url: str, llm_config) -> str:
    """调用 LLM 生成 Midscene YAML；1 次带错误反馈的重试。"""
    prompt = build_prompt(prd_text, base_url)
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}]

    last_error = ''
    for attempt in range(2):
        try:
            content = chat_completions(llm_config, messages, temperature=0.2)
            yaml_text = extract_yaml_block(content)
            validate_midscene_yaml(yaml_text)
            return yaml_text
        except LlmError as e:
            last_error = str(e)
            if attempt == 0:
                messages.append({'role': 'assistant', 'content': content})
                messages.append({
                    'role': 'user',
                    'content': f'上一个响应无法解析为合法 YAML，请重新生成。错误: {last_error}',
                })
            continue
        except ValueError as e:
            last_error = str(e)
            if attempt == 0:
                messages.append({'role': 'assistant', 'content': content})
                messages.append({
                    'role': 'user',
                    'content': f'生成的 YAML 校验失败，请修正后重新生成。错误: {last_error}',
                })
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning('[web_qa] PRD 生成异常: %s', e)
            last_error = str(e)
            continue

    raise ValueError(f'PRD 生成 YAML 失败: {last_error or "未知错误"}')


def generate_suite_from_prd(suite_id: int) -> dict:
    """由 celery 调用：为 suite 生成 yaml_content。绝不抛出。"""
    from .models import QaSuite
    from .runner import update_test_count

    try:
        suite = QaSuite.objects.select_related('project', 'llm_config').get(id=suite_id)
    except QaSuite.DoesNotExist:
        return {'error': f'suite {suite_id} not found'}

    try:
        prd_text = suite.description or ''
        if not prd_text.strip():
            raise ValueError('套件未提供 PRD 文本（description 为空）')
        yaml_text = generate_midscene_yaml(prd_text, suite.base_url, suite.llm_config)
        suite.yaml_content = yaml_text
        suite.status = 'draft'
        suite.save(update_fields=['yaml_content', 'status', 'updated_at'])
        update_test_count(suite)
        logger.info('[web_qa] PRD 生成完成 suite=%s', suite_id)
        return {'suite_id': suite_id, 'status': 'draft', 'yaml_length': len(yaml_text)}
    except Exception as e:  # noqa: BLE001
        logger.exception('[web_qa] PRD 生成失败 suite=%s: %s', suite_id, e)
        suite.status = 'draft'
        suite.save(update_fields=['status', 'updated_at'])
        return {'suite_id': suite_id, 'status': 'draft', 'error': str(e)}
