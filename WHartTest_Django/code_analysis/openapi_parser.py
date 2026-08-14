"""OpenAPI 规范加载与操作归一化。

优先使用 prance 解析（支持 JSON/YAML 并解析 $ref），
prance 不可用或解析失败时回退到手动 json/yaml + 本地 $ref 解析。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

HTTP_METHODS = ('get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'trace')

JSON_LIKE_CONTENT = ('application/json', 'application/x-www-form-urlencoded', 'multipart/form-data')


def _deref(obj, root, _depth=0):
    """手动解析本地 #/... $ref 指针（防御性回退，prance 已解析时基本为原样返回）。"""
    if _depth > 50:
        return obj
    if isinstance(obj, dict):
        ref = obj.get('$ref')
        if isinstance(ref, str) and ref.startswith('#'):
            cur = root
            parts = [p.replace('~1', '/').replace('~0', '~') for p in ref[2:].split('/') if p]
            for part in parts:
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return obj
            return _deref(cur, root, _depth + 1)
        return {k: _deref(v, root, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deref(x, root, _depth + 1) for x in obj]
    return obj


def _schema_type(schema, root):
    """从 schema 中提取简洁类型名。"""
    schema = _deref(schema, root)
    if not isinstance(schema, dict):
        return None
    t = schema.get('type')
    if t in ('string', 'number', 'integer', 'boolean', 'array', 'object', 'file'):
        return t
    if schema.get('$ref'):
        return 'ref'
    if schema.get('properties') or schema.get('allOf'):
        return 'object'
    if schema.get('enum') is not None:
        return 'string'
    return None


def _extract_request_body_schema(operation, root):
    rb = operation.get('requestBody')
    if not isinstance(rb, dict):
        return None
    content = rb.get('content') or {}
    for mt, spec in content.items():
        if mt in JSON_LIKE_CONTENT and isinstance(spec, dict) and 'schema' in spec:
            return _deref(spec['schema'], root)
    for spec in content.values():
        if isinstance(spec, dict) and 'schema' in spec:
            return _deref(spec['schema'], root)
    return None


def _extract_response_schemas(operation, root):
    schemas = {}
    responses = operation.get('responses') or {}
    for code, resp in responses.items():
        if not isinstance(resp, dict):
            continue
        content = resp.get('content') or {}
        found = None
        for mt, spec in content.items():
            if mt == 'application/json' and isinstance(spec, dict) and 'schema' in spec:
                found = _deref(spec['schema'], root)
                break
        if found is None:
            for spec in content.values():
                if isinstance(spec, dict) and 'schema' in spec:
                    found = _deref(spec['schema'], root)
                    break
        if found is not None:
            schemas[str(code)] = found
    return schemas


def _extract_params(container, root):
    params = []
    for p in container.get('parameters') or []:
        if not isinstance(p, dict) or not p.get('name'):
            continue
        schema = p.get('schema') or {}
        params.append({
            'name': str(p['name']),
            'in': p.get('in', 'query'),
            'required': bool(p.get('required', False)),
            'type': _schema_type(schema, root) or p.get('type'),
        })
    return params


def normalize_operations(spec):
    """从解析后的 OpenAPI 文档提取操作列表。"""
    if not isinstance(spec, dict):
        raise ValueError('OpenAPI 文档格式无效')
    operations = []
    paths = spec.get('paths') or {}
    if not isinstance(paths, dict):
        raise ValueError('OpenAPI 文档缺少 paths')

    global_security = spec.get('security')

    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue

            merged_params = {}
            for p in _extract_params(item, spec):
                merged_params[f"{p['in']}:{p['name']}"] = p
            for p in _extract_params(op, spec):
                merged_params[f"{p['in']}:{p['name']}"] = p

            security = op.get('security') if 'security' in op else global_security

            operations.append({
                'method': method.upper(),
                'path': path,
                'operation_id': op.get('operationId') or '',
                'summary': op.get('summary') or '',
                'params': list(merged_params.values()),
                'request_body_schema': _extract_request_body_schema(op, spec),
                'response_schemas': _extract_response_schemas(op, spec),
                'tags': list(op.get('tags') or []),
                'security': bool(security),
            })
    return operations


def _prance_parse(spec_path):
    """尝试用 prance 解析并解析 $ref；校验后端缺失时逐后端尝试。"""
    from prance import ResolvingParser

    try:
        parser = ResolvingParser(str(spec_path))
        return parser.specification
    except Exception:
        pass
    for backend in ('openapi-spec-validator', 'swagger-spec-validator', 'flex'):
        try:
            parser = ResolvingParser(str(spec_path), backend=backend)
            return parser.specification
        except Exception:
            continue
    return None


def load_spec(spec_path) -> dict:
    """加载并解析 OpenAPI 文档（JSON/YAML），返回解析后（含 $ref 解析）的 dict。"""
    raw = Path(spec_path).read_bytes()

    # 优先 prance
    try:
        import prance  # noqa: F401

        spec = _prance_parse(spec_path)
        if isinstance(spec, dict):
            return spec
        logger.warning('prance 解析失败，回退手动解析')
    except ImportError:
        logger.info('prance 未安装，使用手动 OpenAPI 解析')
    except Exception as e:
        logger.warning('prance 解析失败，回退手动解析: %s', e)

    # 手动解析 JSON / YAML
    try:
        spec = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        try:
            import yaml
            spec = yaml.safe_load(raw)
        except Exception as e:
            raise ValueError(f'OpenAPI 文档解析失败: {e}')

    if not isinstance(spec, dict):
        raise ValueError('OpenAPI 文档格式无效')
    return spec
