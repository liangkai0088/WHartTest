from datetime import timedelta
from contextlib import ExitStack, asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from projects.models import Project
from testcases.models import TestCase as FunctionalCase, TestCaseModule
from ui_automation.models import (
    UiCaseStepsDetailed, UiExecutionRecord, UiModule, UiPage,
    UiPageSteps, UiPageStepsDetailed, UiTestCase,
)
from .ui_automation_completion import (
    ExecutionAgentState, UIAutomationIncomplete, build_ui_execution_contract, inspect_ui_completion,
    stream_with_ui_completion,
)


class CompletionEvidenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='ui-completion')
        self.project = Project.objects.create(name='UI completion')
        module = TestCaseModule.objects.create(project=self.project, name='Functional')
        self.case = FunctionalCase.objects.create(project=self.project, module=module, name='Create suite')
        self.module = UiModule.objects.create(project=self.project, name='UI')
        self.started = timezone.now()
        self.contract = {
            'test_case_id': self.case.id, 'project_id': self.project.id,
            'user_id': self.user.id, 'started_at': self.started.isoformat(),
        }

    def make_ui_case(self, *, name=None, steps=True):
        case = UiTestCase.objects.create(
            project=self.project, module=self.module,
            name=name or f'功能用例ID: {self.case.id}', creator=self.user,
        )
        if steps:
            page = UiPage.objects.create(project=self.project, module=self.module, name='Suites', url='/suites')
            page_step = UiPageSteps.objects.create(project=self.project, module=self.module, page=page, name='Create suite')
            UiPageStepsDetailed.objects.create(page_step=page_step, ope_key='click')
            UiCaseStepsDetailed.objects.create(test_case=case, page_step=page_step)
        return case

    def make_record(self, case, **overrides):
        values = dict(test_case=case, executor=self.user, status=2, start_time=timezone.now(), end_time=timezone.now())
        values.update(overrides)
        return UiExecutionRecord.objects.create(**values)

    def test_missing_case_does_not_count_browser_walkthrough(self):
        self.assertEqual(inspect_ui_completion(self.contract)['status'], 'missing_case')

    def test_recent_unrelated_case_and_id_prefix_do_not_match(self):
        for name in ('Create suite', f'功能用例ID: {self.case.id}0', f'UI用例{self.case.id}'):
            self.make_record(self.make_ui_case(name=name))
        self.assertEqual(inspect_ui_completion(self.contract)['status'], 'missing_case')

    def test_description_marker_and_different_ui_primary_key(self):
        self.make_ui_case(name='Unrelated')
        case = self.make_ui_case(name='Create suite')
        case.description = f'功能用例ID: {self.case.id}'
        case.save()
        record = self.make_record(case)
        report = inspect_ui_completion(self.contract)
        self.assertTrue(report['completed'])
        self.assertEqual(report['ui_test_case_id'], case.id)
        self.assertEqual(report['execution_record_id'], record.id)

    def test_empty_case_is_not_completed(self):
        self.make_record(self.make_ui_case(steps=False))
        self.assertEqual(inspect_ui_completion(self.contract)['status'], 'missing_steps')

    def test_saved_case_still_requires_execution(self):
        self.make_ui_case()
        self.assertEqual(inspect_ui_completion(self.contract)['status'], 'missing_execution')

    def test_old_or_other_user_execution_is_not_current_evidence(self):
        case = self.make_ui_case()
        self.make_record(case, start_time=self.started - timedelta(seconds=10))
        self.make_record(case, executor=None)
        self.assertEqual(inspect_ui_completion(self.contract)['status'], 'missing_execution')

    def test_running_cancelled_or_missing_end_time_are_not_complete(self):
        case = self.make_ui_case()
        for status, end in ((0, None), (1, None), (4, timezone.now()), (2, None)):
            with self.subTest(status=status):
                self.make_record(case, status=status, end_time=end)
                self.assertFalse(inspect_ui_completion(self.contract)['completed'])

    def test_real_failed_execution_is_reported_as_failed(self):
        self.make_record(self.make_ui_case(), status=3)
        report = inspect_ui_completion(self.contract)
        self.assertTrue(report['completed'])
        self.assertEqual(report['status'], 'failed')

    def test_latest_running_record_does_not_reuse_previous_success(self):
        case = self.make_ui_case()
        self.make_record(case)
        self.make_record(case, status=1, end_time=None)
        self.assertEqual(inspect_ui_completion(self.contract)['status'], 'unfinished_execution')

    def test_matching_case_is_not_lost_after_200_newer_cases(self):
        case = self.make_ui_case()
        UiTestCase.objects.bulk_create([
            UiTestCase(project=self.project, module=self.module, name=f'Unrelated {i}') for i in range(201)
        ])
        self.make_record(case)
        self.assertTrue(inspect_ui_completion(self.contract)['completed'])

    def test_other_project_is_rejected(self):
        other = Project.objects.create(name='Other')
        self.contract['project_id'] = other.id
        self.assertEqual(inspect_ui_completion(self.contract)['status'], 'invalid_context')

    @override_settings(WHARTTEST_API_KEY='completion-test-service-key')
    def test_skill_service_identity_is_used_for_record_verification(self):
        from api_keys.models import APIKey
        service_user = get_user_model().objects.create_user(username='skill-service')
        APIKey.objects.create(name='completion-test-key', key='completion-test-service-key', user=service_user)
        contract = build_ui_execution_contract(
            test_case_id=self.case.id, project_id=self.project.id,
            user_id=self.user.id, started_at=self.started,
        )
        self.make_record(self.make_ui_case(), executor=service_user)
        self.assertEqual(contract['user_id'], self.user.id)
        self.assertEqual(contract['executor_id'], service_user.id)
        self.assertTrue(inspect_ui_completion(contract)['completed'])


class FakeAgent:
    def __init__(self, rounds):
        self.rounds = iter(rounds)
        self.inputs = []

    async def astream(self, agent_input, **kwargs):
        self.inputs.append(agent_input)
        for event in next(self.rounds):
            yield event


class CompletionLoopTests(SimpleTestCase):
    contract = {'test_case_id': 131, 'project_id': 37, 'user_id': 1, 'started_at': '2026-09-10T00:00:00+00:00'}
    missing = {'completed': False, 'status': 'missing_case', 'message': '缺少用例', 'ui_test_case_id': None, 'execution_record_id': None}
    saved = {**missing, 'status': 'missing_execution', 'message': '缺少执行', 'ui_test_case_id': 55}
    done = {**saved, 'completed': True, 'status': 'passed', 'execution_record_id': 152}

    async def collect(self, agent, **kwargs):
        return [event async for event in stream_with_ui_completion(
            agent, kwargs.pop('agent_input', {'messages': []}), config={},
            stream_mode=['updates', 'messages'], contract=kwargs.pop('contract', self.contract),
            session_id='completion-test', **kwargs,
        )]

    @patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=False)
    async def test_walkthrough_only_is_continued_until_creation_and_execution(self, stop):
        agent = FakeAgent([[], [], []])
        with patch('orchestrator_integration.ui_automation_completion.inspect_ui_completion', side_effect=[self.missing, self.saved, self.done]):
            events = await self.collect(agent)
        self.assertEqual(len(agent.inputs), 3)
        self.assertTrue(events[-1][1]['completed'])
        self.assertIn('不要再次询问', agent.inputs[1]['messages'][0].content)
        self.assertIn('UI 用例 ID：55', agent.inputs[2]['messages'][0].content)

    @patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=False)
    async def test_exhausted_repairs_raise_incomplete(self, stop):
        agent = FakeAgent([[], [], []])
        with patch('orchestrator_integration.ui_automation_completion.inspect_ui_completion', return_value=self.missing):
            with self.assertRaises(UIAutomationIncomplete):
                await self.collect(agent)
        self.assertEqual(len(agent.inputs), 3)

    @override_settings(UI_AUTOMATION_COMPLETION_MAX_REPAIRS=0)
    @patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=False)
    async def test_repair_limit_is_configurable_without_disabling_verification(self, stop):
        agent = FakeAgent([[]])
        with patch('orchestrator_integration.ui_automation_completion.inspect_ui_completion', return_value=self.missing):
            with self.assertRaises(UIAutomationIncomplete):
                await self.collect(agent)
        self.assertEqual(len(agent.inputs), 1)

    @patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=False)
    async def test_hitl_interrupt_never_triggers_repairs(self, stop):
        event = ('updates', {'__interrupt__': ['approval']})
        agent = FakeAgent([[event]])
        with patch('orchestrator_integration.ui_automation_completion.inspect_ui_completion') as inspect:
            self.assertEqual(await self.collect(agent), [event])
            inspect.assert_not_called()

    @patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=False)
    async def test_resume_command_uses_same_completion_gate(self, stop):
        command = Command(resume={'decisions': [{'type': 'approve'}]})
        agent = FakeAgent([[], []])
        with patch('orchestrator_integration.ui_automation_completion.inspect_ui_completion', side_effect=[self.saved, self.done]):
            await self.collect(agent, agent_input=command)
        self.assertIs(agent.inputs[0], command)
        self.assertEqual(len(agent.inputs), 2)

    @patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=True)
    async def test_user_stop_does_not_execute_or_repair(self, stop):
        agent = FakeAgent([])
        self.assertEqual((await self.collect(agent))[0][1]['status'], 'stopped')
        self.assertFalse(agent.inputs)

    @patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=False)
    async def test_non_execution_chat_is_unchanged(self, stop):
        agent = FakeAgent([[('messages', AIMessage(content='hello'))]])
        with patch('orchestrator_integration.ui_automation_completion.inspect_ui_completion') as inspect:
            self.assertEqual(len(await self.collect(agent, contract=None)), 1)
            inspect.assert_not_called()

    async def test_execution_contract_survives_checkpoint_and_new_agent(self):
        saver = InMemorySaver()
        config = {'configurable': {'thread_id': 'completion-state'}}
        model = FakeMessagesListChatModel(responses=[AIMessage(content='done')])
        agent = create_agent(model, state_schema=ExecutionAgentState, checkpointer=saver)
        await agent.ainvoke({'messages': [HumanMessage(content='execute')], 'ui_execution_contract': self.contract}, config)
        checkpoint = await saver.aget_tuple(config)
        self.assertEqual(checkpoint.checkpoint['channel_values']['ui_execution_contract'], self.contract)
        resumed = create_agent(model, state_schema=ExecutionAgentState, checkpointer=saver)
        state = await resumed.aget_state(config)
        self.assertEqual(state.values['ui_execution_contract'], self.contract)
        await resumed.ainvoke({'messages': [HumanMessage(content='chat')], 'ui_execution_contract': None}, config)
        self.assertIsNone((await resumed.aget_state(config)).values['ui_execution_contract'])


class CompletionSSETests(SimpleTestCase):
    async def run_stream(self, reports):
        from . import agent_loop_view as view

        agent = FakeAgent([[] for _ in reports])
        agent.aget_state = AsyncMock(return_value=SimpleNamespace(values={'messages': []}))

        @asynccontextmanager
        async def checkpointer():
            yield InMemorySaver()

        session = SimpleNamespace(title='UI test', created_at=timezone.now())
        config = SimpleNamespace(name='test-model', context_limit=128000, supports_vision=False)
        with ExitStack() as stack:
            for name, value in {
                'build_ui_execution_contract': CompletionLoopTests.contract,
                'validate_file_ids': [],
                'build_llm_attachment_context': '',
                'LLMConfig.objects.get': config,
                'RemoteMCPConfig.objects.filter': [],
                'ChatSession.objects.get_or_create': (session, False),
                'create_llm_instance': object(),
                'resolve_runtime_context_limit': 128000,
                'get_middleware_from_config': [],
                'create_agent': agent,
                'calculate_context_tokens': (0, 0, 0),
                'should_stop': False,
                'inspect_ui_completion': reports[-1],
            }.items():
                stack.enter_context(patch(f'orchestrator_integration.agent_loop_view.{name}', return_value=value))
            stack.enter_context(patch.object(view, 'get_async_checkpointer', checkpointer))
            stack.enter_context(patch.object(view, 'get_effective_system_prompt_async', AsyncMock(return_value=('', 'test'))))
            stack.enter_context(patch.object(view, '_sanitize_history_before_model_call', AsyncMock()))
            stack.enter_context(patch.object(view, '_prepare_agent_loop_human_message', AsyncMock(return_value=('execute', {}, 'execute'))))
            stack.enter_context(patch('orchestrator_integration.builtin_tools.get_builtin_tools', return_value=[]))
            stack.enter_context(patch('orchestrator_integration.ui_automation_completion.should_stop', return_value=False))
            stack.enter_context(patch('orchestrator_integration.ui_automation_completion.inspect_ui_completion', side_effect=reports))
            raw = [event async for event in view.AgentLoopStreamAPIView()._create_stream_generator(
                request=SimpleNamespace(user=SimpleNamespace(id=1)), user_message='execute',
                project_id='37', project=object(), session_id='sse-test', test_case_id=131,
            )]
        return [json.loads(event[6:]) for event in raw if event.startswith('data: ') and '[DONE]' not in event], agent

    async def test_completion_event_follows_verified_execution(self):
        events, agent = await self.run_stream([CompletionLoopTests.missing, CompletionLoopTests.done])
        self.assertFalse(any(event['type'] == 'error' for event in events), events)
        self.assertEqual(len(agent.inputs), 2)
        self.assertEqual(events[-1]['type'], 'complete')
        self.assertEqual(events[-1]['status'], 'completed')
        self.assertEqual(events[-1]['ui_automation']['execution_record_id'], 152)
        self.assertEqual(agent.inputs[0]['ui_execution_contract']['test_case_id'], 131)

    async def test_missing_artifacts_emit_error_and_failed_completion(self):
        events, agent = await self.run_stream([CompletionLoopTests.missing] * 3)
        self.assertEqual(len(agent.inputs), 3)
        self.assertTrue(any(event['type'] == 'error' and 'UI 自动化未完成' in event['message'] for event in events))
        self.assertEqual(events[-1]['type'], 'complete')
        self.assertEqual(events[-1]['status'], 'failed')
        self.assertFalse(events[-1]['ui_automation']['completed'])
