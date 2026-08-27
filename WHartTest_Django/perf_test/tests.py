from django.test import SimpleTestCase

from .diagnose import build_diagnosis_prompt, parse_diagnosis_json
from .orchestrate import (
    build_orchestration_prompt,
    normalize_requests,
    parse_orchestration_json,
)
from .services import (
    build_requests_from_interfaces,
    calc_peak_rps,
    import_har,
    import_swagger,
    infer_host,
    parse_locust_history_csv,
    parse_locust_stats_csv,
    render_locustfile,
)
from .templates import get_template, list_templates


STATS_CSV = (
    '"Type","Name","Request Count","Failure Count","Median Response Time",'
    '"Average Response Time","Min Response Time","Max Response Time",'
    '"Average Content Size","Requests/s","Failures/s","50%","66%","75%","80%",'
    '"90%","95%","98%","99%","99.9%","99.99%","100%"\n'
    '"GET","/api/users",1000,50,100,150,50,300,100,20.0,1.0,'
    '100,120,130,140,160,200,240,280,300,300,300\n'
    '"","Aggregated",1000,50,100,150,50,300,100,20.0,1.0,'
    '100,120,130,140,160,200,240,280,300,300,300\n'
)

HISTORY_CSV = (
    '"Timestamp","User Count","Type","Name","Requests/s","Failures/s",'
    '"Total Request Count","Total Failure Count"\n'
    '"2026-08-14T10:00:00Z",10,"","Aggregated",20.0,1.0,20,1\n'
    '"2026-08-14T10:00:01Z",10,"","Aggregated",25.0,0.0,45,1\n'
    '"2026-08-14T10:00:02Z",10,"","Aggregated",18.0,0.0,63,1\n'
)


class RenderLocustfileTests(SimpleTestCase):
    def test_render_basic_get(self):
        requests = [{
            'name': 'list users', 'method': 'GET', 'url': 'https://api.test/users',
            'headers': {}, 'params': {'page': 1}, 'body': {},
            'variables': {}, 'validators': [], 'weight': 1, 'order': 0,
        }]
        output = render_locustfile(requests, think_time=0)

        self.assertIn('class PerfTestUser(HttpUser):', output)
        self.assertIn('wait_time = constant(0)', output)
        self.assertIn('@task(1)', output)
        self.assertIn('def request_0(self):', output)
        self.assertIn('"GET"', output)
        self.assertIn('"https://api.test/users"', output)

    def test_render_post_json_body(self):
        requests = [{
            'name': 'login', 'method': 'POST', 'url': '/api/login',
            'headers': {'Content-Type': 'application/json'},
            'params': {}, 'body': {'username': 'admin'},
            'variables': {}, 'validators': [], 'weight': 3, 'order': 0,
        }]
        output = render_locustfile(requests)

        self.assertIn('@task(3)', output)
        self.assertIn('json=body', output)
        self.assertIn('"username": "admin"', output)

    def test_render_weight_clamped(self):
        requests = [{
            'name': 'x', 'method': 'GET', 'url': '/x', 'headers': {},
            'params': {}, 'body': {}, 'variables': {}, 'validators': [],
            'weight': 0, 'order': 0,
        }]
        output = render_locustfile(requests)
        self.assertIn('@task(1)', output)

    def test_render_with_target_qps_uses_pacing(self):
        requests = [{
            'name': 'x', 'method': 'GET', 'url': '/x', 'headers': {},
            'params': {}, 'body': {}, 'variables': {}, 'validators': [],
            'weight': 1, 'order': 0,
        }]
        output = render_locustfile(requests, target_qps=100, users=10)

        self.assertIn('constant_pacing', output)
        self.assertIn('wait_time = constant_pacing(0.1)', output)
        self.assertNotIn('constant(', output)

    def test_render_without_target_qps_uses_constant(self):
        requests = [{
            'name': 'x', 'method': 'GET', 'url': '/x', 'headers': {},
            'params': {}, 'body': {}, 'variables': {}, 'validators': [],
            'weight': 1, 'order': 0,
        }]
        output = render_locustfile(requests, think_time=1.5)

        self.assertIn('wait_time = constant(1.5)', output)
        self.assertNotIn('constant_pacing', output)


class SwaggerImportTests(SimpleTestCase):
    def test_import_swagger_v3(self):
        spec = {
            'servers': [{'url': 'https://api.test/v1'}],
            'paths': {
                '/users': {
                    'get': {
                        'summary': 'list users',
                        'parameters': [
                            {'in': 'query', 'name': 'page', 'schema': {'type': 'integer'}},
                        ],
                    },
                },
            },
        }
        requests = import_swagger(spec)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['method'], 'GET')
        self.assertEqual(requests[0]['url'], 'https://api.test/v1/users')
        self.assertEqual(requests[0]['params'], {'page': 0})


class HarImportTests(SimpleTestCase):
    def test_import_har_entries(self):
        har = {
            'log': {
                'entries': [
                    {
                        'request': {
                            'method': 'POST',
                            'url': 'https://api.test/login',
                            'headers': [{'name': 'Content-Type', 'value': 'application/json'}],
                            'postData': {
                                'mimeType': 'application/json',
                                'text': '{"user": "a"}',
                            },
                        },
                    },
                ],
            },
        }
        requests = import_har(har)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['method'], 'POST')
        self.assertEqual(requests[0]['body'], {'user': 'a'})
        self.assertEqual(
            requests[0]['headers'], {'Content-Type': 'application/json'}
        )


class InferHostTests(SimpleTestCase):
    def test_infer_host(self):
        requests = [
            {'url': 'https://api.test/v1/users'},
            {'url': '/health'},
        ]
        self.assertEqual(infer_host(requests), 'https://api.test')

    def test_infer_host_empty(self):
        self.assertEqual(infer_host([]), '')
        self.assertEqual(infer_host([{'url': '/relative'}]), '')


class ParseStatsCsvTests(SimpleTestCase):
    def test_parse_aggregated(self):
        metrics = parse_locust_stats_csv(STATS_CSV)

        self.assertEqual(metrics['total_requests'], 1000)
        self.assertEqual(metrics['total_failures'], 50)
        self.assertEqual(metrics['error_rate'], 5.0)
        self.assertEqual(metrics['avg_response_time'], 150.0)
        self.assertEqual(metrics['p95'], 200.0)
        self.assertEqual(metrics['p99'], 280.0)
        self.assertEqual(metrics['total_rps'], 20.0)


class ParseHistoryCsvTests(SimpleTestCase):
    def test_parse_series(self):
        series = parse_locust_history_csv(HISTORY_CSV)

        self.assertEqual(len(series), 3)
        self.assertEqual(series[1]['rps'], 25.0)
        self.assertEqual(series[0]['users'], 10)

    def test_calc_peak_rps(self):
        series = [
            {'t': 'a', 'rps': 20.0, 'users': 10},
            {'t': 'b', 'rps': 25.0, 'users': 10},
            {'t': 'c', 'rps': 18.0, 'users': 10},
        ]
        self.assertEqual(calc_peak_rps(series), 25.0)


class BuildRequestsFromInterfacesTests(SimpleTestCase):
    def test_build_from_interfaces(self):
        class FakeInterface:
            def __init__(self):
                self.data = {
                    'name': 'login', 'type': 'http', 'method': 'POST',
                    'url': '/api/login', 'headers': {}, 'params': {},
                    'body': {'u': 'x'}, 'variables': {}, 'validators': [],
                }

            def get_interface_data(self):
                return self.data

        from unittest.mock import patch

        fake_qs = [FakeInterface()]
        with patch('api_interfaces.models.ApiInterface') as mock_model:
            mock_model.TYPE_HTTP = 'http'
            mock_model.objects.filter.return_value.order_by.return_value = fake_qs
            requests = build_requests_from_interfaces([1, 2])

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['method'], 'POST')
        self.assertEqual(requests[0]['body'], {'u': 'x'})


class DiagnosisParseTests(SimpleTestCase):
    def test_parse_plain_json(self):
        raw = '{"summary": "整体表现良好", "bottlenecks": [], "suggestions": ["扩容"]}'
        result = parse_diagnosis_json(raw)
        self.assertEqual(result['summary'], '整体表现良好')
        self.assertEqual(result['suggestions'], ['扩容'])

    def test_parse_json_in_code_fence(self):
        raw = (
            '```json\n'
            '{"summary": "s", "bottlenecks": [{"name": "DB", "severity": "high", "detail": "d"}], "suggestions": []}\n'
            '```'
        )
        result = parse_diagnosis_json(raw)
        self.assertEqual(len(result['bottlenecks']), 1)
        self.assertEqual(result['bottlenecks'][0]['severity'], 'high')

    def test_parse_json_with_prefix(self):
        raw = '分析结果如下：\n{"summary": "s", "bottlenecks": [], "suggestions": []}'
        result = parse_diagnosis_json(raw)
        self.assertEqual(result['summary'], 's')

    def test_parse_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_diagnosis_json('没有 JSON 内容')

    def test_build_prompt_contains_metrics(self):
        prompt = build_diagnosis_prompt({'total_requests': 100, 'p99': 200})
        self.assertIn('100', prompt)
        self.assertIn('200', prompt)


class TemplateTests(SimpleTestCase):
    def test_list_templates(self):
        templates = list_templates()
        self.assertGreaterEqual(len(templates), 3)
        keys = {t['key'] for t in templates}
        self.assertIn('login', keys)

    def test_get_template(self):
        template = get_template('login')
        self.assertIsNotNone(template)
        self.assertGreaterEqual(len(template['requests']), 1)
        self.assertIn('users', template['plan'])

    def test_get_template_missing(self):
        self.assertIsNone(get_template('unknown'))


class OrchestrationParseTests(SimpleTestCase):
    def test_parse_plain_json(self):
        raw = '{"name": "登录链路", "requests": [], "plan": {"users": 10}}'
        result = parse_orchestration_json(raw)
        self.assertEqual(result['name'], '登录链路')

    def test_parse_in_code_fence(self):
        raw = '```json\n{"name": "x", "requests": [], "plan": {}}\n```'
        result = parse_orchestration_json(raw)
        self.assertEqual(result['name'], 'x')

    def test_parse_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_orchestration_json('没有 JSON 内容')

    def test_normalize_requests(self):
        requests = [
            {
                'name': '登录', 'method': 'post', 'url': '/login',
                'headers': {'X': '1'},
                'variables': [{'name': 'token', 'path': 'data.token'}],
                'weight': 0,
            },
            {'name': '查询', 'method': 'FOO', 'url': '/list'},
        ]
        result = normalize_requests(requests)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['method'], 'POST')
        self.assertEqual(result[0]['order'], 0)
        self.assertEqual(result[0]['weight'], 1)
        self.assertEqual(result[0]['variables'][0]['name'], 'token')
        self.assertEqual(result[1]['method'], 'GET')
        self.assertEqual(result[1]['order'], 1)

    def test_build_prompt_contains_requirement_and_interfaces(self):
        prompt = build_orchestration_prompt(
            '登录后下单', [{'name': 'login', 'method': 'GET'}]
        )
        self.assertIn('登录后下单', prompt)
        self.assertIn('login', prompt)


class RenderVariableTests(SimpleTestCase):
    def test_render_variable_extraction(self):
        requests = [{
            'name': 'login', 'method': 'POST', 'url': '/api/login',
            'headers': {}, 'params': {}, 'body': {'u': 'x'},
            'variables': [{'name': 'token', 'path': 'data.token'}],
            'validators': [], 'weight': 1, 'order': 0,
        }]
        output = render_locustfile(requests)

        self.assertIn('resp = self.client.request(', output)
        self.assertIn('self.token = resp.json()["data"]["token"]', output)

    def test_render_placeholder_substitution(self):
        requests = [{
            'name': 'query', 'method': 'GET', 'url': '/api/order/{{order_id}}',
            'headers': {'Authorization': 'Bearer {{token}}'}, 'params': {}, 'body': {},
            'variables': [], 'validators': [], 'weight': 1, 'order': 0,
        }]
        output = render_locustfile(requests)

        self.assertIn('self.order_id', output)
        self.assertIn('self.token', output)
        self.assertIn('"Authorization": "Bearer " + self.token', output)

    def test_render_validators(self):
        requests = [{
            'name': 'x', 'method': 'GET', 'url': '/x',
            'headers': {}, 'params': {}, 'body': {},
            'variables': [],
            'validators': [
                {'type': 'status_code', 'expected': 200},
                {'type': 'json', 'path': 'code', 'expected': 0},
            ],
            'weight': 1, 'order': 0,
        }]
        output = render_locustfile(requests)

        self.assertIn('assert resp.status_code == 200', output)
        self.assertIn('assert resp.json()["code"] == 0', output)


from django.test import TestCase  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from projects.models import Project  # noqa: E402
from .models import (  # noqa: E402
    PerfTestScenario, PerfTestRequest, PerfTestPlan,
    PerfTestExecution, PerfTestNode,
)
from .distributed import (  # noqa: E402
    nodes_available, claim_task, apply_progress, apply_report, build_task_payload,
)


class DistributedSchedulingTest(TestCase):
    """分布式调度：认领、无任务、进度/结果落库、离线回退（需 DB，Docker 阶段运行）。"""

    def setUp(self):
        self.user = User.objects.create_user('dist', 'dist@t.com', 'pw')
        self.project = Project.objects.create(name='dist-proj', owner=self.user)
        self.scenario = PerfTestScenario.objects.create(
            name='s', project=self.project, created_by=self.user, source='interface'
        )
        PerfTestRequest.objects.create(
            scenario=self.scenario, name='r', method='GET', url='/x'
        )
        self.plan = PerfTestPlan.objects.create(
            scenario=self.scenario, users=5, spawn_rate=1, duration=10
        )
        self.node = PerfTestNode.objects.create(name='n1', host='h', status='online')

    def _pending_execution(self):
        return PerfTestExecution.objects.create(
            scenario=self.scenario, node=self.node, status='pending'
        )

    def test_nodes_available_only_online(self):
        self.assertTrue(nodes_available(self.node))
        self.node.status = 'offline'
        self.assertFalse(nodes_available(self.node))
        self.assertFalse(nodes_available(None))

    def test_claim_task_returns_payload_and_marks_running(self):
        execution = self._pending_execution()
        claimed, payload = claim_task(self.node.id)
        self.assertEqual(claimed.id, execution.id)
        self.assertIn('locustfile', payload)
        self.assertIn('execution_id', payload)
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'running')

    def test_claim_task_no_task_when_none_pending(self):
        claimed, payload = claim_task(self.node.id)
        self.assertIsNone(payload)

    def test_claim_task_skips_offline_node(self):
        self._pending_execution()
        self.node.status = 'offline'
        self.node.save()
        claimed, payload = claim_task(self.node.id)
        self.assertIsNone(payload)

    @staticmethod
    def _metrics():
        return {'total_requests': 10, 'total_failures': 0, 'error_rate': 0,
                'avg_response_time': 100, 'total_rps': 10}

    def test_apply_report_completes_execution(self):
        execution = self._pending_execution()
        execution.start()
        report_id = apply_report(execution.id, self._metrics(), [{'time': 1, 'rps': 5}])
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'completed')
        self.assertEqual(execution.progress, 100)
        self.assertIsNotNone(report_id)

    def test_apply_report_failure_marks_failed(self):
        execution = self._pending_execution()
        execution.start()
        apply_report(execution.id, {}, [], error='boom')
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'failed')
        self.assertEqual(execution.error_message, 'boom')

    def test_apply_progress_updates_running_only(self):
        execution = self._pending_execution()
        execution.start()
        apply_progress(execution.id, 42.0, 7, 5)
        execution.refresh_from_db()
        self.assertEqual(execution.progress, 42.0)
