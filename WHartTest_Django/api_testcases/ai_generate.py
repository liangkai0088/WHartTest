"""API 测试用例一键生成：LLM 根据业务需求/接口定义生成步骤、断言、变量提取并落库。"""

import json
import logging
import re

logger = logging.getLogger(__name__)

_METHODS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'}
_PRIORITIES = {'P0', 'P1', 'P2', 'P3'}

_DEFAULT_INTERFACE_DATA = {
    'setup_hooks': [],
    'teardown_hooks': [],
    'file_ids': [],
}


def _get_llm(temperature=0.2):
    """惰性加载激活的 LLM 配置并构造实例。"""
    from langgraph_integration.models import LLMConfig
    from langgraph_integration.views import create_llm_instance

    config = LLMConfig.objects.filter(is_active=True).first()
    if config is None:
        raise RuntimeError('未配置激活的 LLM，无法执行 AI 生成')
    return create_llm_instance(config, temperature=temperature)


def build_generation_prompt(requirement, interface_options=None):
    """根据自然语言需求与可选接口定义构造用例生成 Prompt。"""
    lines = [
        '你是资深接口自动化测试工程师。请根据用户需求，生成一个完整的接口测试用例。',
        '',
        f'需求描述：{requirement}',
        '',
    ]
    if interface_options:
        lines.append('可参考的接口定义（JSON 数组，含 name/method/url/headers/params/body）：')
        lines.append(json.dumps(interface_options, ensure_ascii=False))
        lines.append('')
    lines += [
        '请识别业务链路中各步骤的执行顺序、请求方法、URL、参数，以及步骤间的数据依赖',
        '（如登录返回的 token 需被后续步骤引用）。',
        '',
        '严格按以下 JSON 格式输出（不要输出任何其他内容）：',
        '{',
        '  "name": "用例名称",',
        '  "description": "用例描述",',
        '  "priority": "P0|P1|P2|P3",',
        '  "steps": [',
        '    {',
        '      "name": "步骤名称",',
        '      "method": "GET|POST|PUT|DELETE|PATCH",',
        '      "url": "完整 URL 或路径",',
        '      "headers": {"Content-Type": "application/json"},',
        '      "params": {},',
        '      "body": {},',
        '      "extract": {"token": "data.token"},',
        '      "variables": {},',
        '      "validators": [{"check": "status_code", "expect": 200, "assert": "eq"}]',
        '    }',
        '  ]',
        '}',
        '',
        '规则：',
        '- extract 表示从当前步骤响应中提取变量，键为变量名，值为响应 JSON 的 jmespath 点路径；',
        '  后续步骤可在 headers/params/body 中用 "$变量名" 引用（如 "$token"）。',
        '- validators 支持 {"check": "status_code", "expect": 200, "assert": "eq"} '
        '或 {"check": "body.code", "expect": 0, "assert": "eq"}。',
        '- body 为 JSON 对象时直接写对象，为原始字符串时写字符串。',
        '- 只输出 JSON，不要输出解释性文字。',
    ]
    return '\n'.join(lines)


def parse_generation_json(raw):
    """从 LLM 输出中提取 JSON 对象（容错 markdown 代码块包裹）。"""
    text = (raw or '').strip()
    fence = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f'LLM 输出中未找到 JSON: {raw[:200]}')
    return json.loads(text[start:end + 1])


def _as_dict(value, default=None):
    return value if isinstance(value, dict) else (default if default is not None else {})


def _normalize_validators(validators):
    """归一化断言列表，仅保留 prepare_validator_for_runtime 支持的格式。"""
    result = []
    for validator in validators or []:
        if not isinstance(validator, dict):
            continue
        if 'check' in validator and 'expect' in validator:
            item = {'check': validator.get('check'), 'expect': validator.get('expect')}
            if validator.get('assert'):
                item['assert'] = validator['assert']
            if validator.get('comparator'):
                item['comparator'] = validator['comparator']
            result.append(item)
            continue
        for comparator, compare_values in validator.items():
            if isinstance(compare_values, list) and len(compare_values) >= 2:
                result.append({comparator: compare_values[:3]})
    return result


def normalize_steps(steps):
    """归一化 LLM 生成的步骤列表为 (name, interface_data) 列表，过滤非法方法。"""
    result = []
    for index, item in enumerate(steps or []):
        if not isinstance(item, dict):
            continue
        method = (item.get('method') or 'GET').upper()
        if method not in _METHODS:
            method = 'GET'
        name = item.get('name') or f'步骤{index + 1}'
        interface_data = {
            'method': method,
            'url': item.get('url') or '',
            'headers': _as_dict(item.get('headers')),
            'params': _as_dict(item.get('params')),
            'body': item.get('body') if item.get('body') is not None else {},
            'extract': _as_dict(item.get('extract')),
            'variables': _as_dict(item.get('variables')),
            'validators': _normalize_validators(item.get('validators')),
            **_DEFAULT_INTERFACE_DATA,
        }
        result.append((name, interface_data))
    return result


def generate_testcase(project, user, requirement, interface_ids=None, group_id=None):
    """LLM 生成测试用例并落库，返回 testcase 对象。"""
    from .models import ApiTestCase, ApiTestCaseStep

    interface_options = _load_interface_options(interface_ids)
    prompt = build_generation_prompt(requirement, interface_options)

    from langchain_core.messages import HumanMessage

    response = _get_llm(temperature=0.2).invoke([HumanMessage(content=prompt)])
    result = parse_generation_json(response.content)

    priority = (result.get('priority') or 'P2').upper()
    if priority not in _PRIORITIES:
        priority = 'P2'

    steps = normalize_steps(result.get('steps'))
    if not steps:
        raise ValueError('LLM 未生成任何有效步骤')

    group = None
    if group_id:
        from .models import ApiTestCaseGroup

        try:
            group = ApiTestCaseGroup.objects.get(id=group_id, project=project)
        except ApiTestCaseGroup.DoesNotExist:
            group = None

    testcase = ApiTestCase.objects.create(
        name=result.get('name') or 'AI 生成用例',
        description=result.get('description') or '',
        priority=priority,
        project=project,
        group=group,
        created_by=user,
    )
    ApiTestCaseStep.objects.bulk_create([
        ApiTestCaseStep(
            testcase=testcase,
            order=index + 1,
            name=name,
            interface_data=interface_data,
        )
        for index, (name, interface_data) in enumerate(steps)
    ])
    logger.info(f'AI 生成用例完成 testcase={testcase.id} steps={len(steps)}')
    return testcase


def _load_interface_options(interface_ids):
    """加载可选接口定义作为 LLM 参考数据。"""
    if not interface_ids:
        return None
    from api_interfaces.models import ApiInterface

    interfaces = ApiInterface.objects.filter(id__in=interface_ids).order_by('id')
    options = []
    for interface in interfaces:
        data = interface.get_interface_data()
        options.append({
            'name': data.get('name'),
            'method': data.get('method'),
            'url': data.get('url'),
            'headers': data.get('headers'),
            'params': data.get('params'),
            'body': data.get('body'),
        })
    return options or None
