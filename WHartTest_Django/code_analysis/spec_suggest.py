"""OpenAPI -> 测试用例建议生成引擎。

确定性规则引擎永远可用；use_llm=True 且有可用 LLMConfig 时，
额外使用 LLM 增强场景描述，失败仅记录 warning，不影响任务结果。
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

DEFAULT_GROUP_NAME = 'AI源码分析'

PRIORITY_MAP = {
    'high': 'high',
    'medium': 'medium',
    'low': 'low',
}


def _sample_value(schema, name=None):
    if not isinstance(schema, dict):
        return None
    if schema.get('example') is not None:
        return schema['example']
    if schema.get('default') is not None:
        return schema['default']
    if schema.get('enum'):
        return schema['enum'][0]
    if schema.get('const') is not None:
        return schema['const']
    t = schema.get('type')
    fmt = schema.get('format')
    if t == 'string':
        if fmt == 'email':
            return 'test@example.com'
        if fmt == 'date':
            return '2026-01-01'
        if fmt == 'date-time':
            return '2026-01-01T00:00:00Z'
        if fmt == 'password':
            return 'Test@123456'
        low = (name or '').lower()
        if low in ('username', 'user', 'account', 'name'):
            return 'testuser'
        if low in ('password', 'pwd', 'secret'):
            return 'Test@123456'
        return 'test'
    if t == 'integer':
        return 1
    if t == 'number':
        return 1.0
    if t == 'boolean':
        return True
    if t == 'array':
        items = schema.get('items') or {}
        return [_sample_value(items, name)]
    if t == 'object' or schema.get('properties'):
        props = schema.get('properties') or {}
        return {k: _sample_value(v, k) for k, v in list(props.items())[:12]}
    return None


def _sample_body(schema):
    if not isinstance(schema, dict):
        return {}
    if schema.get('type') == 'object' or schema.get('properties'):
        return _sample_value(schema)
    return {'value': _sample_value(schema)}


def _sample_param(p):
    t = p.get('type')
    if t == 'integer':
        return 1
    if t == 'number':
        return 1.0
    if t == 'boolean':
        return True
    return 'test'


def _build_param_payload(op, *, exclude_required=False):
    """构造请求参数 payload：{in: {name: value}}。"""
    payload = {}
    for p in op.get('params') or []:
        if exclude_required and p.get('required'):
            continue
        payload.setdefault(p.get('in', 'query'), {})[p['name']] = _sample_param(p)
    return payload


def _send_step(op, body=None, exclude_required=False, note=''):
    return {
        'action': 'send_request',
        'detail': {
            'name': f"{op['method']} {op['path']}",
            'method': op['method'],
            'path': op['path'],
            'params': _build_param_payload(op, exclude_required=exclude_required),
            'body': body or {},
            'headers': {},
            'note': note,
        },
    }


def _assert_step(expression, expected):
    return {
        'action': 'assert',
        'detail': {
            'expression': expression,
            'expected': expected,
        },
    }


def _payload_for(op, *, name, priority, description, steps, target_module=None):
    return {
        'name': name,
        'method': op['method'],
        'path': op['path'],
        'operation_id': op.get('operation_id') or '',
        'priority': priority,
        'description': description,
        'steps': steps,
        'target_module': target_module,
    }


def _scenarios_for_operation(op):
    """为单个 path+method 生成确定性测试场景。"""
    method = op['method']
    path = op['path']
    scenarios = []
    tags = op.get('tags') or []
    target_module = tags[0] if tags else None

    has_body = op.get('request_body_schema') is not None
    required_params = [p for p in op.get('params') or [] if p.get('required')]

    # 1) 正常请求（happy path）
    happy_steps = [_send_step(op, body=_sample_body(op.get('request_body_schema')) if has_body else {})]
    happy_steps.append(_assert_step('status_code >= 200 and status_code < 300', '2xx'))
    scenarios.append(_payload_for(
        op,
        name=f'{method} {path} 正常请求',
        priority='high',
        description=f'按规范构造 {method} {path} 的正常请求，验证接口返回成功（2xx）。',
        steps=happy_steps,
        target_module=target_module,
    ))

    # 2) 缺少必填参数
    if required_params:
        missing = [p['name'] for p in required_params]
        steps = [_send_step(op, body=_sample_body(op.get('request_body_schema')) if has_body else {}, exclude_required=True)]
        steps.append(_assert_step('status_code >= 400 and status_code < 500', '4xx'))
        scenarios.append(_payload_for(
            op,
            name=f'{method} {path} 缺少必填参数',
            priority='medium',
            description=f'不传必填参数（{", ".join(missing)}），验证接口返回参数校验错误（4xx）。',
            steps=steps,
            target_module=target_module,
        ))

    # 3) 非法请求体（仅存在 requestBody 的接口）
    if has_body and method.lower() in ('post', 'put', 'patch', 'delete'):
        steps = [_send_step(
            op,
            body={'__invalid__': None},
            note='构造非法/类型不匹配的请求体',
        )]
        steps.append(_assert_step('status_code >= 400 and status_code < 500', '400/422'))
        scenarios.append(_payload_for(
            op,
            name=f'{method} {path} 非法请求体',
            priority='high',
            description='构造非法请求体（类型不匹配/缺字段），验证接口返回 400/422 校验错误。',
            steps=steps,
            target_module=target_module,
        ))

    # 4) 无认证访问
    if op.get('security'):
        steps = [_send_step(op, body=_sample_body(op.get('request_body_schema')) if has_body else {}, note='不携带认证信息')]
        steps.append(_assert_step('status_code in (401, 403)', '401/403'))
        scenarios.append(_payload_for(
            op,
            name=f'{method} {path} 无认证访问',
            priority='medium',
            description='不带任何认证信息请求受保护接口，验证返回 401/403。',
            steps=steps,
            target_module=target_module,
        ))

    return scenarios


def generate_suggestions(operations, use_llm=False, warnings=None):
    """
    生成所有测试用例建议 payload 列表。

    use_llm=True 时尝试用默认 LLMConfig 增强描述；任何 LLM 相关异常仅写入
    warnings，绝不让整个任务失败。
    """
    if warnings is None:
        warnings = []

    payloads = []
    for op in operations:
        try:
            payloads.extend(_scenarios_for_operation(op))
        except Exception as e:
            warnings.append(f'生成 {op.get("method")} {op.get("path")} 建议失败: {e}')

    if use_llm and payloads:
        payloads = _enrich_descriptions(payloads, warnings)

    return payloads


def _extract_json_array(text):
    text = (text or '').strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            return None
    return None


def _enrich_descriptions(payloads, warnings):
    """使用默认 LLMConfig 增强前 30 个建议的描述。"""
    try:
        from langgraph_integration.models import LLMConfig
        from langgraph_integration.views import create_llm_instance

        config = (
            LLMConfig.objects.filter(is_active=True).first()
            or LLMConfig.objects.filter(is_active=False).order_by('-created_at').first()
        )
        if config is None:
            warnings.append('未找到可用的 LLMConfig，跳过 LLM 描述增强（确定性引擎结果仍有效）')
            return payloads

        llm = create_llm_instance(config, temperature=0.2)
    except Exception as e:
        warnings.append(f'LLM 初始化失败，跳过描述增强: {e}')
        return payloads

    selected = payloads[:30]
    lines = [
        f'{i}. [{p["method"]} {p["path"]}] 场景={p["name"]} 优先级={p["priority"]} 描述={p["description"]}'
        for i, p in enumerate(selected)
    ]
    prompt = (
        '你是资深测试工程师。以下是为各接口生成的测试场景，请为每个场景补充 1-2 句简洁的中文测试说明'
        '（说明测试目的与关键校验点，不要编造接口细节）。'
        '严格输出 JSON 数组，元素顺序与输入一致，每项仅包含 {"index": N, "description": "..."}：\n'
        + '\n'.join(lines)
    )

    try:
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, 'content') else str(resp)
        data = _extract_json_array(text)
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                idx = item.get('index')
                desc = item.get('description')
                if isinstance(idx, int) and 0 <= idx < len(selected) and isinstance(desc, str) and desc.strip():
                    selected[idx]['description'] = desc.strip()
    except Exception as e:
        warnings.append(f'LLM 描述增强失败: {e}')

    return payloads
