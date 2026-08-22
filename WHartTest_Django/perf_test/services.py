"""性能测试核心服务：脚本来源解析、Locust 脚本渲染、结果聚合。"""

import csv
import io
import json
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Locust CSV 汇总中参与聚合的列名
_STATS_FIELDS = {
    'request_count': 'Request Count',
    'failure_count': 'Failure Count',
    'avg_response_time': 'Average Response Time',
    'min_response_time': 'Min Response Time',
    'max_response_time': 'Max Response Time',
    'requests_per_sec': 'Requests/s',
    'p50': '50%',
    'p95': '95%',
    'p99': '99%',
}

_HISTORY_FIELDS = {
    'timestamp': 'Timestamp',
    'user_count': 'User Count',
    'requests_per_sec': 'Requests/s',
}


def build_requests_from_interfaces(interface_ids):
    """从接口定义（ApiInterface）生成请求模板列表。

    仅取 HTTP 类型接口，SQL 类型接口无法压测，直接跳过。
    """
    from api_interfaces.models import ApiInterface

    interfaces = ApiInterface.objects.filter(
        id__in=interface_ids, type=ApiInterface.TYPE_HTTP
    ).order_by('id')
    requests = []
    for interface in interfaces:
        data = interface.get_interface_data()
        requests.append({
            'name': data.get('name') or '',
            'method': data.get('method') or 'GET',
            'url': data.get('url') or '',
            'headers': data.get('headers') or {},
            'params': data.get('params') or {},
            'body': data.get('body') or {},
            'variables': data.get('variables') or {},
            'validators': data.get('validators') or [],
            'weight': 1,
            'order': len(requests),
        })
    return requests


def _swagger_base_url(spec):
    """从 Swagger/OpenAPI 规范提取 base URL。"""
    if spec.get('servers'):
        return (spec['servers'][0].get('url') or '').rstrip('/')
    schemes = spec.get('schemes') or ['http']
    host = spec.get('host') or ''
    base_path = (spec.get('basePath') or '').rstrip('/')
    return f"{schemes[0]}://{host}{base_path}"


def import_swagger(spec):
    """解析 Swagger 2.0 / OpenAPI 3.0 规范，生成请求模板列表。

    spec 为已解析的 dict。
    """
    base_url = _swagger_base_url(spec)
    requests = []
    for path, methods in (spec.get('paths') or {}).items():
        for method, operation in methods.items():
            if method.lower() not in {
                'get', 'post', 'put', 'delete', 'patch', 'head', 'options'
            }:
                continue
            headers = {}
            params = {}
            body = {}
            for param in operation.get('parameters') or []:
                if param.get('in') == 'header':
                    headers[param.get('name')] = _schema_example(param.get('schema') or {})
                elif param.get('in') == 'query':
                    params[param.get('name')] = _schema_example(param.get('schema') or {})
                elif param.get('in') == 'body':
                    body = _schema_example(param.get('schema') or {})
            request_body = operation.get('requestBody')
            if request_body:
                content = (request_body.get('content') or {}).get('application/json') or {}
                body = _schema_example(content.get('schema') or {})
            requests.append({
                'name': operation.get('summary') or f"{method.upper()} {path}",
                'method': method.upper(),
                'url': f"{base_url}{path}",
                'headers': headers,
                'params': params,
                'body': body,
                'variables': {},
                'validators': [],
                'weight': 1,
                'order': len(requests),
            })
    return requests


def _schema_example(schema):
    """从 JSON Schema 生成一个示例值（用于压测默认参数）。"""
    if not schema:
        return {}
    if 'example' in schema:
        return schema['example']
    schema_type = schema.get('type')
    if schema_type == 'object':
        return {
            key: _schema_example(child)
            for key, child in (schema.get('properties') or {}).items()
        }
    if schema_type == 'array':
        return []
    if schema_type == 'integer':
        return 0
    if schema_type == 'number':
        return 0.0
    if schema_type == 'boolean':
        return False
    if schema_type == 'string':
        return ''
    return {}


def import_har(har_content):
    """解析 HAR 文件（JSON 字符串或 dict），生成请求模板列表。"""
    if isinstance(har_content, str):
        har = json.loads(har_content)
    else:
        har = har_content
    requests = []
    for entry in har.get('log', {}).get('entries', []):
        req = entry.get('request') or {}
        headers_list = req.get('headers') or []
        headers = {
            h.get('name'): h.get('value', '') for h in headers_list if h.get('name')
        }
        params = {}
        body = {}
        post_data = req.get('postData') or {}
        mime_type = post_data.get('mimeType') or ''
        if post_data.get('text'):
            try:
                body = json.loads(post_data['text'])
            except (ValueError, TypeError):
                body = post_data['text']
        requests.append({
            'name': f"{req.get('method', 'GET')} {req.get('url', '')}",
            'method': (req.get('method') or 'GET').upper(),
            'url': req.get('url') or '',
            'headers': headers,
            'params': params,
            'body': body,
            'variables': {},
            'validators': [],
            'weight': 1,
            'order': len(requests),
        })
    return requests


_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')


def _render_string(value):
    """将字符串渲染为 locustfile 表达式，含 {{var}} 占位符时拼接 self.<var>。"""
    if '{{' not in value:
        return json.dumps(value, ensure_ascii=False)
    parts = _PLACEHOLDER_RE.split(value)
    exprs = []
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 0:
            exprs.append(json.dumps(part, ensure_ascii=False))
        else:
            exprs.append(f'self.{part}')
    return ' + '.join(exprs) if exprs else '""'


def _render_value(value):
    """递归渲染请求字段值（支持 dict/list/str 中的 {{var}} 占位符）。"""
    if isinstance(value, str):
        return _render_string(value)
    if isinstance(value, dict):
        inner = ', '.join(
            f'{json.dumps(k, ensure_ascii=False)}: {_render_value(v)}'
            for k, v in value.items()
        )
        return '{' + inner + '}'
    if isinstance(value, list):
        return '[' + ', '.join(_render_value(v) for v in value) + ']'
    return json.dumps(value)


def _render_json_path(path):
    """将点路径 'data.token' 渲染为 ['data']['token'] 下标表达式。"""
    segments = [s for s in str(path).split('.') if s]
    parts = []
    for seg in segments:
        if seg.isdigit():
            parts.append(f'[{seg}]')
        else:
            parts.append(f'[{json.dumps(seg)}]')
    return ''.join(parts)


def _render_validator(validator):
    """渲染断言代码行，不支持的断言类型返回 None。"""
    vtype = validator.get('type')
    if vtype == 'status_code':
        return f'        assert resp.status_code == {int(validator.get("expected") or 200)}'
    if vtype == 'json' and validator.get('path'):
        expected = validator.get('expected')
        return f'        assert resp.json(){_render_json_path(validator["path"])} == {json.dumps(expected)}'
    return None


def _render_request_lines(index, request):
    """渲染单个请求模板为 locustfile task 代码行列表。"""
    method = (request.get('method') or 'GET').upper()
    url = _render_string(request.get('url') or '')
    headers = request.get('headers') or {}
    params = request.get('params') or {}
    body = request.get('body') or {}
    weight = max(1, int(request.get('weight') or 1))
    variables = request.get('variables') or []
    validators = request.get('validators') or []

    lines = [f"    @task({weight})", f"    def request_{index}(self):"]
    if headers:
        lines.append(f"        headers = {_render_value(headers)}")
    if params:
        lines.append(f"        params = {_render_value(params)}")

    kwargs = []
    if headers:
        kwargs.append("headers=headers")
    if params:
        kwargs.append("params=params")
    if body:
        if isinstance(body, dict):
            lines.append(f"        body = {_render_value(body)}")
            kwargs.append("json=body")
        else:
            lines.append(f"        body = {_render_value(body)}")
            kwargs.append("data=body")

    call_args = ", ".join([json.dumps(method), url] + kwargs)
    need_resp = bool(variables) or bool(validators)
    prefix = 'resp = ' if need_resp else ''
    lines.append(f"        {prefix}self.client.request({call_args})")

    for var in variables:
        name = (var.get('name') or '').strip()
        path = var.get('path')
        if not name or not path:
            continue
        lines.append(f"        self.{name} = resp.json(){_render_json_path(path)}")

    for validator in validators:
        line = _render_validator(validator)
        if line:
            lines.append(line)

    return lines


def render_locustfile(requests, think_time: float = 0, target_qps=None, users=None):
    """将请求模板列表渲染为 locustfile 字符串。

    提供 target_qps 与 users 时，使用 constant_pacing 近似限流
    （每用户按 users/target_qps 秒节奏发请求），否则使用固定思考时间。
    """
    if target_qps and users:
        pacing = round(float(users) / float(target_qps), 4)
        import_line = "from locust import HttpUser, task, constant_pacing"
        wait_line = f"    wait_time = constant_pacing({pacing})"
    else:
        import_line = "from locust import HttpUser, task, constant"
        wait_line = f"    wait_time = constant({think_time})"

    lines = [
        import_line,
        "",
        "",
        "class PerfTestUser(HttpUser):",
        wait_line,
        "",
    ]
    for index, request in enumerate(requests):
        lines.extend(_render_request_lines(index, request))
        lines.append("")
    return "\n".join(lines)


def infer_host(requests):
    """从请求模板列表推断目标主机（取首个绝对 URL 的 scheme+netloc）。"""
    for request in requests:
        url = request.get('url') or ''
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return ''


def _parse_csv(content):
    """将 CSV 文本解析为 dict 列表。"""
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]


def parse_locust_stats_csv(content):
    """解析 locust --csv 的 stats.csv，返回聚合指标 dict。

    取 Type=Aggregated 行；无结果时返回空指标。
    """
    rows = _parse_csv(content)
    for row in rows:
        if row.get('Name') == 'Aggregated':
            return _extract_stats(row)
    return {}


def _extract_stats(row):
    """从 Aggregated 行提取关键指标。"""
    def num(key):
        try:
            return float(row.get(_STATS_FIELDS[key]) or 0)
        except (ValueError, TypeError):
            return 0.0

    request_count = int(num('request_count'))
    failure_count = int(num('failure_count'))
    error_rate = round(failure_count / request_count * 100, 2) if request_count else 0.0
    return {
        'total_requests': request_count,
        'total_failures': failure_count,
        'error_rate': error_rate,
        'avg_response_time': round(num('avg_response_time'), 2),
        'min_response_time': round(num('min_response_time'), 2),
        'max_response_time': round(num('max_response_time'), 2),
        'p50': round(num('p50'), 2),
        'p95': round(num('p95'), 2),
        'p99': round(num('p99'), 2),
        'total_rps': round(num('requests_per_sec'), 2),
    }


def parse_locust_history_csv(content):
    """解析 locust --csv-full-history 的 stats_history.csv，返回 RPS 时序列表。

    每个元素为 {t, rps, users}，t 为相对秒数（从 0 起）。
    """
    rows = _parse_csv(content)
    series = []
    first_timestamp = None
    for row in rows:
        if row.get('Name') != 'Aggregated':
            continue
        timestamp = row.get(_HISTORY_FIELDS['timestamp'])
        if not timestamp:
            continue
        if first_timestamp is None:
            first_timestamp = timestamp
        try:
            rps = float(row.get(_HISTORY_FIELDS['requests_per_sec']) or 0)
            users = int(float(row.get(_HISTORY_FIELDS['user_count']) or 0))
        except (ValueError, TypeError):
            continue
        series.append({'t': timestamp, 'rps': rps, 'users': users})
    return series


def calc_peak_rps(series):
    """从 RPS 时序计算峰值。"""
    if not series:
        return 0.0
    return round(max(item.get('rps', 0) for item in series), 2)
