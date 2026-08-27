"""UI 自动化自愈服务：定位失效的诊断、安全回写与重跑验证。"""

import json
import logging
import re

logger = logging.getLogger(__name__)

LOCATOR_FAILURE_KEYWORDS = (
    '定位器', '定位元素', '元素定位', '元素不存在', 'Element not found',
)


def is_locator_failure(step):
    """判断步骤结果是否为定位失效。"""
    if step.get('status') != 'failed':
        return False
    message = step.get('message') or ''
    return any(keyword in message for keyword in LOCATOR_FAILURE_KEYWORDS)


def trigger_from_execution_record(record_id):
    """执行失败后：识别定位失效步骤，创建自愈记录并投递诊断任务。"""
    from django.conf import settings
    from .models import UiExecutionRecord, UiSelfHealingRecord

    record = UiExecutionRecord.objects.get(id=record_id)
    if record.status != 3:
        return None

    steps = record.step_results or []
    failed_step = next((s for s in steps if is_locator_failure(s)), None)
    if failed_step is None:
        return None

    max_retry = int(getattr(settings, 'UI_SELF_HEALING_MAX_RETRY', 1) or 0)
    healing = UiSelfHealingRecord.objects.create(
        execution_record=record,
        test_case_id=record.test_case_id,
        step_id=failed_step.get('step_id'),
        failure_message=(failed_step.get('message') or '')[:2000],
        status='pending',
        max_retry=max_retry,
    )

    from .tasks import diagnose_ui_failure

    diagnose_ui_failure.delay(healing.id)
    logger.info(f"已创建自愈记录 healing={healing.id} 并投递诊断任务")
    return healing.id


def diagnose_failure(healing_id):
    """核心自愈流程：解析元素 → LLM 诊断 → 回写 → 重跑。"""
    from .models import UiSelfHealingRecord

    healing = UiSelfHealingRecord.objects.get(id=healing_id)
    healing.status = 'diagnosing'
    healing.save(update_fields=['status'])

    try:
        element, page_url = _resolve_element(healing)
        if element is None:
            healing.status = 'ignored'
            healing.fix_summary = {'reason': '无法定位到失败步骤对应的元素'}
            healing.save(update_fields=['status', 'fix_summary'])
            return {'status': 'ignored'}

        fix = _diagnose(element, page_url, healing.failure_message)
        healing.diagnosis = fix
        healing.save(update_fields=['diagnosis'])

        _apply_fix(element, fix)
        healing.fix_summary = {
            'element_id': element.id,
            'old': {
                'locator_type': element.locator_type,
                'locator_value': element.locator_value,
            },
            'new': {
                'locator_type': fix.get('new_locator_type'),
                'locator_value': fix.get('new_locator_value'),
            },
        }
        _trigger_rerun(healing)
        healing.status = 'healed'
        healing.save(update_fields=['status', 'fix_summary', 'rerun_batch_id'])
        return {'status': 'healed', 'element_id': element.id}
    except Exception as exc:
        logger.exception(f"UI 自愈诊断失败 healing={healing_id}")
        healing.status = 'failed'
        healing.fix_summary = {'error': str(exc)}
        healing.save(update_fields=['status', 'fix_summary'])
        return {'status': 'failed', 'error': str(exc)}


def _resolve_element(healing):
    """通过失败步骤 ID 反查目标元素与页面 URL。"""
    from .models import UiPageStepsDetailed

    if not healing.step_id:
        return None, ''
    try:
        detail = UiPageStepsDetailed.objects.select_related(
            'element', 'page_step__page'
        ).get(id=healing.step_id)
    except UiPageStepsDetailed.DoesNotExist:
        return None, ''
    page = detail.page_step.page
    return detail.element, (page.url or '')


def _build_prompt(element, page_url, failure_message):
    return (
        "你是 UI 自动化测试专家。一个页面元素定位失效，请根据元素信息、当前定位器和失败信息，"
        "推荐一个更稳定的定位表达式。\n\n"
        f"- 元素名称: {element.name}\n"
        f"- 元素描述: {element.description or ''}\n"
        f"- 当前主定位: [{element.locator_type}] {element.locator_value}\n"
        f"- 备用定位1: [{element.locator_type_2 or '-'}] {element.locator_value_2 or ''}\n"
        f"- 备用定位2: [{element.locator_type_3 or '-'}] {element.locator_value_3 or ''}\n"
        f"- 页面 URL: {page_url or ''}\n"
        f"- 失败信息: {failure_message}\n\n"
        "请严格按以下 JSON 格式输出（不要输出其他内容）：\n"
        '{"new_locator_type": "css|xpath|text|role|label|placeholder|test_id|id|name", '
        '"new_locator_value": "新的定位表达式", "reason": "推荐理由"}'
    )


def parse_fix(raw):
    """从 LLM 输出中提取定位修复 JSON。"""
    text = (raw or '').strip()
    fence = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f'LLM 输出中未找到 JSON: {raw[:200]}')
    return json.loads(text[start:end + 1])


def _diagnose(element, page_url, failure_message):
    from langchain_core.messages import HumanMessage
    from langgraph_integration.models import LLMConfig
    from langgraph_integration.views import create_llm_instance

    config = LLMConfig.objects.filter(is_active=True).first()
    if config is None:
        raise RuntimeError('未配置激活的 LLM，无法执行自愈诊断')

    llm = create_llm_instance(config, temperature=0.1)
    raw = llm.invoke([HumanMessage(content=_build_prompt(
        element, page_url, failure_message
    ))]).content
    return parse_fix(raw)


def _apply_fix(element, fix):
    """将 LLM 推荐的定位器追加到空闲备用定位槽位（安全策略，不覆盖主定位）。"""
    locator_type = fix.get('new_locator_type')
    locator_value = fix.get('new_locator_value')
    if not locator_type or not locator_value:
        raise ValueError('LLM 未返回有效的定位表达式')

    if not element.locator_value_2:
        element.locator_type_2 = locator_type
        element.locator_value_2 = locator_value
    elif not element.locator_value_3:
        element.locator_type_3 = locator_type
        element.locator_value_3 = locator_value
    else:
        element.locator_type_3 = locator_type
        element.locator_value_3 = locator_value

    element.save(update_fields=[
        'locator_type_2', 'locator_value_2',
        'locator_type_3', 'locator_value_3',
    ])


def _trigger_rerun(healing):
    """通过内部 API 触发该用例重跑，并记录重跑批次 ID。"""
    import requests
    from django.conf import settings
    from rest_framework_simplejwt.tokens import RefreshToken

    test_case = healing.test_case
    user = healing.execution_record.executor if healing.execution_record else None
    if user is None:
        user = test_case.creator if test_case else None
    if user is None or test_case is None:
        return

    token = str(RefreshToken.for_user(user).access_token)
    resp = requests.post(
        f"{settings.BASE_URL}/api/ui-automation/trigger-batch/",
        json={
            'case_ids': [test_case.id],
            'batch_name': f"自愈重跑-{test_case.name}",
            'trigger_type': 'api',
        },
        headers={'Authorization': f'Bearer {token}'},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"触发重跑失败: {resp.text[:200]}")
    healing.rerun_batch_id = resp.json().get('data', {}).get('batch_id')


def should_retry_rerun(rerun_success, retry_count, max_retry):
    """重跑失败后是否继续触发下一轮自愈诊断。

    :param rerun_success: 重跑是否成功（None 表示尚未重跑，不触发）
    :param retry_count: 已触发的自愈重试次数
    :param max_retry: 允许的最大自愈重试次数（0 表示一次性，不循环）
    """
    if rerun_success is None:
        return False
    if rerun_success:
        return False
    return retry_count < max_retry


def schedule_retry_if_failed(healing_id):
    """重跑失败且未达上限时，再次投递诊断任务进入下一轮自愈循环。

    返回是否安排了下一轮；否则将记录标记为自愈失败。
    """
    from .models import UiSelfHealingRecord

    healing = UiSelfHealingRecord.objects.get(id=healing_id)

    if not should_retry_rerun(healing.rerun_success, healing.retry_count, healing.max_retry):
        if healing.status == 'diagnosing' and healing.rerun_success is False:
            healing.status = 'failed'
            healing.save(update_fields=['status'])
        return False

    healing.retry_count += 1
    healing.status = 'pending'
    healing.save(update_fields=['retry_count', 'status'])

    from .tasks import diagnose_ui_failure

    diagnose_ui_failure.delay(healing.id)
    logger.info(f"自愈进入下一轮重试 healing={healing.id} 第 {healing.retry_count} 次")
    return True
