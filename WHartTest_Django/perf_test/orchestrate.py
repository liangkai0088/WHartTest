"""性能测试 AI 编排：LLM 理解业务链路，生成结构化压测场景并落库。"""

import json
import logging
import re

from .diagnose import _get_llm

logger = logging.getLogger(__name__)

_METHODS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'}


def build_orchestration_prompt(requirement, interface_options=None):
    """根据自然语言业务描述构造 AI 编排 Prompt。"""
    lines = [
        '你是资深性能测试工程师。请根据用户描述的业务链路，编排一个完整的压测场景。',
        '',
        f'业务需求描述：{requirement}',
        '',
    ]
    if interface_options:
        lines.append('可参考的接口定义（JSON 数组，含 name/method/url/params/body）：')
        lines.append(json.dumps(interface_options, ensure_ascii=False))
        lines.append('')
    lines += [
        '请识别业务链路中各步骤的执行顺序、请求方法、URL、参数，以及步骤间的数据依赖',
        '（如登录返回的 token、创建订单返回的 order_id 需要被后续步骤引用）。',
        '',
        '严格按以下 JSON 格式输出（不要输出任何其他内容）：',
        '{',
        '  "name": "场景名称",',
        '  "description": "场景描述",',
        '  "requests": [',
        '    {',
        '      "name": "步骤名称",',
        '      "method": "GET|POST|PUT|DELETE|PATCH",',
        '      "url": "完整 URL 或路径",',
        '      "headers": {"Content-Type": "application/json"},',
        '      "params": {},',
        '      "body": {},',
        '      "variables": [{"name": "token", "path": "data.token"}],',
        '      "validators": [{"type": "status_code", "expected": 200}],',
        '      "weight": 1',
        '    }',
        '  ],',
        '  "plan": {"users": 50, "spawn_rate": 5, "duration": 60, "think_time": 0.5}',
        '}',
        '',
        '规则：',
        '- variables 表示从当前请求的响应中提取变量，path 为响应 JSON 的点路径；',
        '  后续请求可用 {{变量名}} 引用（例如 headers 里 "Authorization": "Bearer {{token}}"）。',
        '- validators 支持 {"type": "status_code", "expected": 200} '
        '或 {"type": "json", "path": "code", "expected": 0}。',
        '- 只输出 JSON，不要输出解释性文字。',
    ]
    return '\n'.join(lines)


def parse_orchestration_json(raw):
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


def normalize_requests(requests):
    """归一化 LLM 生成的请求列表，补齐 order 与默认字段，过滤非法方法。"""
    result = []
    for index, item in enumerate(requests or []):
        if not isinstance(item, dict):
            continue
        method = (item.get('method') or 'GET').upper()
        if method not in _METHODS:
            method = 'GET'
        result.append({
            'name': item.get('name') or f'请求{index + 1}',
            'method': method,
            'url': item.get('url') or '',
            'headers': item.get('headers') if isinstance(item.get('headers'), dict) else {},
            'params': item.get('params') if isinstance(item.get('params'), dict) else {},
            'body': item.get('body') if isinstance(item.get('body'), (dict, list, str)) else {},
            'variables': item.get('variables') if isinstance(item.get('variables'), list) else [],
            'validators': item.get('validators') if isinstance(item.get('validators'), list) else [],
            'weight': max(1, int(item.get('weight') or 1)),
            'order': index,
        })
    return result


def orchestrate_scenario(project, user, requirement, interface_ids=None):
    """AI 编排完整流程：LLM 生成结构化场景并落库，返回 (scenario, result)。"""
    from .models import PerfTestScenario, PerfTestRequest, PerfTestPlan

    interface_options = _load_interface_options(interface_ids)
    prompt = build_orchestration_prompt(requirement, interface_options)

    from langchain_core.messages import HumanMessage

    response = _get_llm(temperature=0.2).invoke([HumanMessage(content=prompt)])
    result = parse_orchestration_json(response.content)

    scenario = PerfTestScenario.objects.create(
        name=result.get('name') or 'AI 编排场景',
        description=result.get('description') or '',
        source='ai',
        project=project,
        created_by=user,
    )
    requests = normalize_requests(result.get('requests'))
    PerfTestRequest.objects.bulk_create([
        PerfTestRequest(scenario=scenario, **req) for req in requests
    ])
    plan = result.get('plan') or {}
    PerfTestPlan.objects.create(
        scenario=scenario,
        users=int(plan.get('users') or 10),
        spawn_rate=int(plan.get('spawn_rate') or 1),
        duration=int(plan.get('duration') or 60),
        think_time=float(plan.get('think_time') or 0),
    )
    logger.info(f'AI 编排完成 scenario={scenario.id} requests={len(requests)}')
    return scenario, result


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
            'params': data.get('params'),
            'body': data.get('body'),
        })
    return options or None
