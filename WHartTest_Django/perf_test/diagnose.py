"""性能测试 AI 诊断：将压测报告指标交给 LLM 做瓶颈定位与优化建议。"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def _get_llm(temperature=0.2):
    """惰性加载激活的 LLM 配置并构造实例（复用统一构造逻辑）。"""
    from langgraph_integration.models import LLMConfig
    from langgraph_integration.views import create_llm_instance

    config = LLMConfig.objects.filter(is_active=True).first()
    if config is None:
        raise RuntimeError('未配置激活的 LLM，无法执行 AI 诊断')
    return create_llm_instance(config, temperature=temperature)


def build_diagnosis_prompt(metrics):
    """根据报告指标构造诊断 Prompt。"""
    return (
        "你是资深性能测试专家。请根据以下压测报告指标，定位性能瓶颈并给出优化建议。\n\n"
        f"- 总请求数: {metrics.get('total_requests', 0)}\n"
        f"- 失败请求数: {metrics.get('total_failures', 0)} "
        f"(错误率 {metrics.get('error_rate', 0)}%)\n"
        f"- 平均响应时间: {metrics.get('avg_response_time', 0)} ms\n"
        f"- 最小/最大响应时间: {metrics.get('min_response_time', 0)} / "
        f"{metrics.get('max_response_time', 0)} ms\n"
        f"- P50/P95/P99: {metrics.get('p50', 0)} / {metrics.get('p95', 0)} / "
        f"{metrics.get('p99', 0)} ms\n"
        f"- 平均 RPS: {metrics.get('total_rps', 0)}，峰值 RPS: {metrics.get('peak_rps', 0)}\n\n"
        "请严格按以下 JSON 格式输出（不要输出任何其他内容）：\n"
        '{"summary": "总体结论一句话", '
        '"bottlenecks": [{"name": "瓶颈名称", "severity": "high|medium|low", '
        '"detail": "分析说明"}], '
        '"suggestions": ["优化建议1", "优化建议2"]}'
    )


def parse_diagnosis_json(raw):
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


def diagnose_report(report_id):
    """对指定报告执行 AI 诊断，并将结果写入 bottleneck_summary。"""
    from .models import PerfTestReport

    report = PerfTestReport.objects.get(id=report_id)
    metrics = {
        'total_requests': report.total_requests,
        'total_failures': report.total_failures,
        'error_rate': report.error_rate,
        'avg_response_time': report.avg_response_time,
        'min_response_time': report.min_response_time,
        'max_response_time': report.max_response_time,
        'p50': report.p50,
        'p95': report.p95,
        'p99': report.p99,
        'total_rps': report.total_rps,
        'peak_rps': report.peak_rps,
    }

    prompt = build_diagnosis_prompt(metrics)
    from langchain_core.messages import HumanMessage

    response = _get_llm(temperature=0.2).invoke([HumanMessage(content=prompt)])
    summary = parse_diagnosis_json(response.content)

    report.bottleneck_summary = summary
    report.save(update_fields=['bottleneck_summary'])
    logger.info(f"压测报告 AI 诊断完成 report={report_id}")
    return summary
