"""Verify persisted UI artifacts before an execution conversation can finish."""

import os
import re

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils.dateparse import parse_datetime
from langchain.agents import AgentState
from langchain_core.messages import HumanMessage

from .stop_signal import should_stop
from .response_language import stream_with_chinese_responses


class ExecutionAgentState(AgentState, total=False):
    ui_execution_contract: dict | None


class UIAutomationIncomplete(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__(f"UI 自动化未完成：{report['message']}")


def is_execution_continuation(message):
    return bool(re.fullmatch(
        r"\s*(?:请)?(?:继续|接着|恢复)(?:执行|运行|测试|生成|上次(?:的)?(?:任务|内容)|未完成(?:的)?任务)?[吧。！!\s]*",
        message or "",
    ))


def extract_execution_case_id(message):
    if not re.search(r"执行|运行|重跑|回归|生成\s*UI", message or "", re.I):
        return None
    match = re.search(
        r"(?:执行\s*ID\s*为|(?:功能|测试)?用例\s*(?:ID)?\s*[：:#为]?|case[_-]?id\s*[：:=])\s*(\d+)"
        r"|(?:执行|运行|重跑|回归)\s*(\d+)\s*(?:号)?(?:的)?(?:测试)?用例",
        message, re.I,
    )
    return int(next(value for value in match.groups() if value)) if match else None


def recover_execution_context(values, *, message, user_id, project_id):
    """Only explicit continuation can inherit execution intent from this thread."""
    if not is_execution_continuation(message):
        return None, None
    contract = values.get('ui_execution_contract')
    if contract:
        if contract.get('user_id') != user_id or str(contract.get('project_id')) != str(project_id):
            raise ValueError('UI 自动化执行上下文与当前用户或项目不一致')
        return int(contract['test_case_id']), contract
    # Recover older sessions whose continuation requests had cleared the contract.
    for previous in reversed(values.get('messages', [])):
        if isinstance(previous, HumanMessage):
            content = previous.content
            if not isinstance(content, str) or not is_execution_continuation(content):
                return extract_execution_case_id(content) if isinstance(content, str) else None, None
    return None, None


def build_ui_execution_contract(*, test_case_id, project_id, user_id, started_at):
    from api_keys.models import APIKey
    from .builtin_tools.skill_tools import get_skill_api_key

    # Skills authenticate with the configured service key, which may belong to
    # a different user from the person who started the conversation.
    key = get_skill_api_key()
    executor_id = APIKey.objects.filter(key=key).values_list('user_id', flat=True).first()
    return {
        'test_case_id': int(test_case_id), 'project_id': int(project_id),
        'user_id': user_id, 'executor_id': executor_id or user_id,
        'started_at': started_at.isoformat(),
    }


def inspect_ui_completion(contract):
    from testcases.models import TestCase
    from ui_automation.models import UiExecutionRecord, UiTestCase

    case_id = int(contract['test_case_id'])
    project_id = int(contract['project_id'])
    started_at = parse_datetime(contract['started_at'])
    report = {
        'test_case_id': case_id,
        'ui_test_case_id': None,
        'execution_record_id': None,
        'completed': False,
        'status': 'missing_case',
        'message': '尚未生成关联的 UI 自动化用例。',
    }
    if not started_at or not TestCase.objects.filter(id=case_id, project_id=project_id).exists():
        return {**report, 'status': 'invalid_context', 'message': '功能用例或执行上下文无效。'}

    # Require an explicit functional ID, never a recent creation or name substring.
    marker = re.compile(rf'功能\s*用例\s*(?:ID\s*)?[：:]?\s*{case_id}(?!\d)', re.I)
    candidates = UiTestCase.objects.filter(project_id=project_id).only('id', 'name', 'description').order_by('-id')
    matched_ids = [case.id for case in candidates.iterator() if marker.search(f'{case.name}\n{case.description or ""}')]
    if not matched_ids:
        return report

    report['ui_test_case_id'] = matched_ids[0]
    usable_ids = list(UiTestCase.objects.filter(
        id__in=matched_ids, case_steps__page_step__step_details__isnull=False,
    ).values_list('id', flat=True).distinct())
    if not usable_ids:
        return {**report, 'status': 'missing_steps', 'message': 'UI 用例已保存，但尚未包含可执行的页面步骤。'}

    report['ui_test_case_id'] = next(case_id for case_id in matched_ids if case_id in usable_ids)
    record = UiExecutionRecord.objects.filter(
        test_case_id__in=usable_ids,
        executor_id=contract.get('executor_id', contract['user_id']),
        created_at__gte=started_at,
        start_time__gte=started_at,
    ).order_by('-created_at', '-id').first()
    if not record:
        return {**report, 'status': 'missing_execution', 'message': 'UI 用例已保存，但没有本次请求的执行记录。'}

    report.update(ui_test_case_id=record.test_case_id, execution_record_id=record.id)
    if record.status not in (2, 3) or not record.end_time:
        return {**report, 'status': 'unfinished_execution', 'message': '执行记录尚未完成或已取消，不能作为完成依据。'}
    return {
        **report,
        'completed': True,
        'status': 'passed' if record.status == 2 else 'failed',
        'message': f'UI 用例 {record.test_case_id}，执行记录 {record.id}，结果：{"通过" if record.status == 2 else "未通过"}。',
    }


def build_completion_prompt(contract, report):
    case_id = contract['test_case_id']
    return (
        '系统已核验平台数据库，本次 UI 自动化任务尚未完成。'
        f'项目 ID：{contract["project_id"]}；功能用例 ID：{case_id}。'
        f'核验结果：{report["message"]}'
        f'关联 UI 用例 ID：{report["ui_test_case_id"]}；执行记录 ID：{report["execution_record_id"]}。\n'
        '继续使用 read_skill_content 和 execute_skill_script 完成已授权任务，不要再次询问是否补做。'
        '读取 ui-automation Skill，查询并复用已有页面、元素、步骤和用例；不存在时根据本次真实浏览器观察创建，'
        f'在用例名称或描述中保存准确标记 `功能用例ID: {case_id}`。'
        '禁止创建空壳用例或编造定位器。已有用例时补齐页面步骤，不要重复创建。'
        '然后检查执行器，调用 execute_testcase --testcase_id <UI用例ID> --wait_result --exec_timeout 120，'
        '并用 get_execution_records 核对新记录及终态。若仍在执行，应等待查询，禁止重复提交。'
        '功能用例 ID 与 UI 用例 ID 属于不同表，禁止将功能用例 ID 直接用于 UI 执行查询。'
        '浏览器走查和截图不替代平台执行。若工具报错或执行器离线，如实说明具体阻塞，禁止宣称完成。'
        '功能走查未通过或测试数据缺失不免除保存 UI 用例和平台执行；保留原始断言，'
        '让执行记录如实反映失败原因，禁止把断言改为通过，也禁止伪造或擅自补充业务数据。'
    )


async def stream_with_ui_completion(agent, agent_input, *, config, stream_mode, contract, session_id, max_repairs=None):
    """Keep retries on the normal tool/HITL path and gate completion on database evidence."""
    if max_repairs is None:
        max_repairs = int(getattr(
            settings, 'UI_AUTOMATION_COMPLETION_MAX_REPAIRS',
            os.environ.get('UI_AUTOMATION_COMPLETION_MAX_REPAIRS', '2'),
        ))
    if max_repairs < 0:
        raise ValueError('UI_AUTOMATION_COMPLETION_MAX_REPAIRS 不能为负数')
    for attempt in range(max_repairs + 1):
        if should_stop(session_id):
            yield 'ui_automation', {'status': 'stopped', 'message': '已停止生成'}
            return
        interrupted = False
        async for mode, chunk in stream_with_chinese_responses(
            agent, agent_input, config=config, stream_mode=stream_mode,
        ):
            if mode == 'updates' and isinstance(chunk, dict) and '__interrupt__' in chunk:
                interrupted = True
            yield mode, chunk
        if interrupted or should_stop(session_id) or not contract:
            return
        report = await sync_to_async(inspect_ui_completion)(contract)
        yield 'ui_automation', report
        if report['completed']:
            return
        if attempt == max_repairs or report['status'] == 'invalid_context':
            raise UIAutomationIncomplete(report)
        agent_input = {'messages': [HumanMessage(content=build_completion_prompt(contract, report))]}
