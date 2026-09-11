"""评审报告 PDF 导出。

将 ReviewReport 及其专项分析结果渲染为自包含 HTML，再通过
Playwright Chromium 打印为 PDF（A4）。仅使用标准库与已在环境中
安装的 playwright，不引入新的 pip 依赖。
"""

import html

from playwright.sync_api import sync_playwright

from .serializers import ReviewReportSerializer


# 专项分析维度：(specialized_analyses key, 中文名称, scores key)
_DIMENSIONS = [
    ("completeness_analysis", "完整性分析", "completeness"),
    ("consistency_analysis", "一致性分析", "consistency"),
    ("testability_analysis", "可测性分析", "testability"),
    ("feasibility_analysis", "可行性分析", "feasibility"),
    ("clarity_analysis", "清晰度分析", "clarity"),
    ("logic_analysis", "逻辑分析", "logic"),
]

_REVIEW_TYPE_LABELS = {
    "comprehensive": "全面评审",
    "direct": "直接评审",
}

_PRIORITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

_PRIORITY_CLASSES = {
    "high": "priority-high",
    "medium": "priority-medium",
    "low": "priority-low",
}

_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 12mm 4mm;
  background: #F5F6F8;
  color: #1F2329;
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei",
    "Noto Sans CJK SC", "Source Han Sans SC", sans-serif;
  font-size: 13px;
  line-height: 1.6;
}
.card {
  background: #FFFFFF;
  border: 1px solid #E5E6EB;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(31, 35, 41, 0.05);
  padding: 16px 18px;
  margin-bottom: 14px;
}
/* ---------- Header ---------- */
.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.doc-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #1F2329;
  line-height: 1.35;
}
.rating-chip {
  flex: 0 0 auto;
  display: inline-block;
  padding: 3px 12px;
  border-radius: 999px;
  background: #FDECEC;
  color: #E05252;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.meta {
  margin-top: 8px;
  color: #8A9099;
  font-size: 12px;
}
.meta span + span { margin-left: 14px; }
/* ---------- Hero ---------- */
.hero {
  display: flex;
  align-items: stretch;
  gap: 22px;
  padding: 20px 22px;
  border-radius: 10px;
  background: linear-gradient(135deg, #2F7BE8 0%, #3D8BF5 100%);
  color: #FFFFFF;
  margin-bottom: 16px;
  box-shadow: 0 2px 8px rgba(47, 123, 232, 0.25);
}
.hero-left { flex: 0 0 auto; display: flex; align-items: center; }
.score-circle {
  width: 80px;
  height: 80px;
  border: 2px solid rgba(255, 255, 255, 0.85);
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.12);
}
.score-circle .num { font-size: 28px; font-weight: 700; line-height: 1; }
.score-circle .lbl { font-size: 11px; margin-top: 3px; opacity: 0.9; }
.hero-right { flex: 1 1 auto; min-width: 0; }
.hero-rating {
  display: inline-block;
  padding: 2px 12px;
  border-radius: 999px;
  background: #FFFFFF;
  color: #2F7BE8;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 8px;
}
.pills { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.pill {
  display: inline-block;
  padding: 2px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.2);
  color: #FFFFFF;
  font-size: 12px;
  font-weight: 600;
}
.hero-summary {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.92);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
/* ---------- Dimension section ---------- */
.section { margin-bottom: 22px; }
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #E8F2FE;
  border-left: 3px solid #2F7BE8;
  border-radius: 6px;
  padding: 9px 14px;
  margin-bottom: 12px;
}
.section-name { font-size: 15px; font-weight: 700; color: #1F2329; }
.score-pill {
  background: #FFFFFF;
  color: #2F7BE8;
  border: 1px solid #A8CDF6;
  border-radius: 999px;
  padding: 2px 12px;
  font-size: 12px;
  font-weight: 700;
}
.score-summary-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}
.score-badge {
  flex: 0 0 auto;
  width: 56px;
  height: 56px;
  border: 2px solid #2F7BE8;
  border-radius: 50%;
  display: flex;
  align-items: baseline;
  justify-content: center;
  color: #2F7BE8;
  background: #FFFFFF;
}
.score-badge .num { font-size: 20px; font-weight: 700; line-height: 56px; }
.score-badge .unit { font-size: 10px; margin-left: 1px; }
.summary-label {
  font-size: 12px;
  font-weight: 700;
  color: #8A9099;
  margin-bottom: 2px;
}
.summary-text {
  margin: 0;
  color: #4E5969;
  font-size: 13px;
  line-height: 1.7;
}
/* ---------- Info cards ---------- */
.info-card {
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.strength-card { background: #F1FBEC; border: 1px solid #B7E8A0; }
.recommend-card { background: #E8F2FE; border: 1px solid #A8CDF6; }
.info-title { font-size: 14px; font-weight: 700; margin-bottom: 6px; }
.info-title.green { color: #52C41A; }
.info-title.blue { color: #2F7BE8; }
.info-card ul { margin: 0; padding: 0; list-style: none; }
.info-card li {
  position: relative;
  padding-left: 14px;
  margin-bottom: 4px;
  color: #4E5969;
  font-size: 12.5px;
  line-height: 1.65;
}
.info-card li:before {
  content: "";
  position: absolute;
  left: 0;
  top: 7px;
  width: 6px;
  height: 6px;
  border-radius: 1px;
}
.strength-card li:before { background: #52C41A; }
.recommend-card li:before { background: #2F7BE8; }
/* ---------- Issues ---------- */
.issues-title {
  font-size: 14px;
  font-weight: 700;
  color: #1F2329;
  margin: 14px 0 10px;
}
.issue-card {
  background: #FFFFFF;
  border: 1px solid #E5E6EB;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
  page-break-inside: avoid;
  break-inside: avoid;
}
.chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.chip {
  display: inline-block;
  padding: 1px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.priority-high { background: #FDECEC; color: #E05252; }
.priority-medium { background: #FFF8E6; color: #D98E04; }
.priority-low { background: #E8F2FE; color: #2F7BE8; }
.chip-resolved { background: #F1FBEC; color: #52C41A; }
.chip-unresolved { background: #F2F3F5; color: #8A9099; }
.chip-category { background: #F2F3F5; color: #4E5969; }
.issue-location {
  margin-left: auto;
  color: #8A9099;
  font-size: 12px;
  white-space: nowrap;
}
.issue-title {
  font-size: 13px;
  font-weight: 700;
  color: #1F2329;
  margin-bottom: 4px;
}
.issue-desc {
  margin: 0 0 6px;
  color: #4E5969;
  font-size: 12.5px;
  line-height: 1.65;
}
.suggestion {
  background: #F7FAFD;
  border-left: 3px solid #2F7BE8;
  border-radius: 0 4px 4px 0;
  padding: 6px 10px;
  color: #4E5969;
  font-size: 12.5px;
  line-height: 1.65;
}
.suggestion b { color: #2F7BE8; }
.resolution {
  margin-top: 6px;
  color: #52C41A;
  font-size: 12px;
}
/* ---------- Footer ---------- */
.footer {
  text-align: center;
  color: #8A9099;
  font-size: 11px;
  margin-top: 18px;
  padding-top: 10px;
  border-top: 1px solid #E5E6EB;
}
"""


def _esc(value):
    """转义动态文本，None 视为空串。"""
    if value is None:
        return ""
    return html.escape(str(value))


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return value
    return []


def _build_resolution_map(report):
    """构建 {issue_id(str): {is_resolved, resolution_note}} 映射。"""
    resolution_map = {}
    try:
        issues = report.issues.all()
    except Exception:
        return resolution_map
    for issue in issues:
        resolution_map[str(issue.id)] = {
            "is_resolved": bool(issue.is_resolved),
            "resolution_note": issue.resolution_note or "",
        }
    return resolution_map


def _normalize_priority(issue):
    raw = issue.get("priority") or issue.get("severity")
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in _PRIORITY_LABELS:
            return key
    return "medium"


def _resolve_state(issue, resolution_map):
    """返回 (is_resolved, note)，优先使用 ReviewIssue 记录中的状态。"""
    overlay = resolution_map.get(str(issue.get("id")))
    if overlay is None and "is_resolved" in issue:
        overlay = {
            "is_resolved": bool(issue.get("is_resolved")),
            "resolution_note": issue.get("resolution_note") or "",
        }
    if overlay is None:
        return False, ""
    return bool(overlay.get("is_resolved")), overlay.get("resolution_note") or ""


def _render_meta_line(document, report):
    review_date = report.review_date
    review_date_text = review_date.strftime("%Y-%m-%d %H:%M") if review_date else "未知"
    version = getattr(document, "version", "") or "—"
    reviewer = report.reviewer or "—"
    return (
        f'<div class="meta">'
        f"<span>评审时间：{_esc(review_date_text)}</span>"
        f"<span>评审人：{_esc(reviewer)}</span>"
        f"<span>文档版本：{_esc(version)}</span>"
        f"</div>"
    )


def _render_hero(data, report):
    score = _as_int(data.get("completion_score", report.completion_score))
    rating = (
        data.get("overall_rating_display")
        or report.overall_rating
        or "未评定"
    )
    high = _as_int(data.get("high_priority_issues", report.high_priority_issues))
    medium = _as_int(data.get("medium_priority_issues", report.medium_priority_issues))
    low = _as_int(data.get("low_priority_issues", report.low_priority_issues))
    summary = data.get("summary") or report.summary or ""

    summary_html = ""
    if str(summary).strip():
        summary_html = f'<p class="hero-summary">{_esc(summary)}</p>'

    return f"""
    <div class="hero">
      <div class="hero-left">
        <div class="score-circle">
          <div class="num">{score}</div>
          <div class="lbl">总分</div>
        </div>
      </div>
      <div class="hero-right">
        <div class="hero-rating">{_esc(rating)}</div>
        <div class="pills">
          <span class="pill">高 {high}</span>
          <span class="pill">中 {medium}</span>
          <span class="pill">低 {low}</span>
        </div>
        {summary_html}
      </div>
    </div>
    """


def _render_info_card(title, css_class, items):
    if not items:
        return ""
    list_items = "".join(f"<li>{_esc(item)}</li>" for item in items if str(item).strip())
    if not list_items:
        return ""
    return (
        f'<div class="info-card {css_class}">'
        f'<div class="info-title">{_esc(title)}</div>'
        f"<ul>{list_items}</ul>"
        f"</div>"
    )


def _render_issue(issue, resolution_map):
    if not isinstance(issue, dict):
        return ""
    priority = _normalize_priority(issue)
    priority_label = _PRIORITY_LABELS[priority]
    priority_class = _PRIORITY_CLASSES[priority]

    title = str(issue.get("title") or "").strip()
    description = str(issue.get("description") or "").strip()
    if not title:
        title = description

    is_resolved, resolution_note = _resolve_state(issue, resolution_map)
    if is_resolved:
        state_chip = '<span class="chip chip-resolved">已解决</span>'
    else:
        state_chip = '<span class="chip chip-unresolved">未解决</span>'

    category = str(issue.get("category") or "").strip()
    category_chip = (
        f'<span class="chip chip-category">{_esc(category)}</span>' if category else ""
    )

    location = str(issue.get("location") or "").strip()
    location_html = (
        f'<span class="issue-location">位置：{_esc(location)}</span>'
        if location
        else ""
    )

    parts = [
        '<div class="issue-card">',
        '<div class="chips">',
        f'<span class="chip {priority_class}">{_esc(priority_label)}</span>',
        state_chip,
        category_chip,
        location_html,
        "</div>",
        f'<div class="issue-title">{_esc(title)}</div>',
    ]

    if description and description != title:
        parts.append(f'<p class="issue-desc">{_esc(description)}</p>')

    suggestion = str(issue.get("suggestion") or "").strip()
    if suggestion:
        parts.append(
            f'<div class="suggestion"><b>建议：</b>{_esc(suggestion)}</div>'
        )

    if is_resolved and resolution_note.strip():
        parts.append(
            f'<div class="resolution">处理说明：{_esc(resolution_note)}</div>'
        )

    parts.append("</div>")
    return "".join(parts)


def _render_dimension(analysis_key, dimension_name, score_key, analyses, scores, resolution_map):
    dimension = analyses.get(analysis_key)
    if not isinstance(dimension, dict):
        dimension = {}

    raw_score = scores.get(score_key)
    if raw_score is None:
        raw_score = dimension.get("overall_score", 0)
    score = _as_int(raw_score)

    summary = str(dimension.get("summary") or "").strip()

    strengths_card = _render_info_card(
        "优势", "strength-card", _as_list(dimension.get("strengths"))
    )
    recommendations_card = _render_info_card(
        "改进建议", "recommend-card", _as_list(dimension.get("recommendations"))
    )

    issues = [i for i in _as_list(dimension.get("issues")) if isinstance(i, dict)]
    issues_html = "".join(_render_issue(issue, resolution_map) for issue in issues)

    issues_section = ""
    if issues:
        issues_section = (
            f'<div class="issues-title">发现的问题（{len(issues)}个）</div>'
            f"{issues_html}"
        )

    summary_html = (
        f'<p class="summary-text">{_esc(summary)}</p>'
        if summary
        else '<p class="summary-text">暂无数据</p>'
    )

    return f"""
    <div class="section">
      <div class="section-header">
        <span class="section-name">{_esc(dimension_name)}</span>
        <span class="score-pill">{score} / 100</span>
      </div>
      <div class="score-summary-row">
        <div class="score-badge"><span class="num">{score}</span><span class="unit">分</span></div>
        <div class="summary-block">
          <div class="summary-label">分析总结</div>
          {summary_html}
        </div>
      </div>
      {strengths_card}
      {recommendations_card}
      {issues_section}
    </div>
    """


def build_report_html(document, report) -> str:
    """构建评审报告的自包含 HTML（仅内联 CSS）。"""
    data = ReviewReportSerializer(report).data
    analyses = data.get("specialized_analyses") or {}
    if not isinstance(analyses, dict):
        analyses = {}
    scores = data.get("scores") or {}
    if not isinstance(scores, dict):
        scores = {}
    resolution_map = _build_resolution_map(report)

    document_title = data.get("document_title") or getattr(document, "title", "")
    rating = (
        data.get("overall_rating_display")
        or report.overall_rating
        or "未评定"
    )

    header = f"""
    <div class="card">
      <div class="header-top">
        <h1 class="doc-title">{_esc(document_title)} 评审报告</h1>
        <span class="rating-chip">{_esc(rating)}</span>
      </div>
      {_render_meta_line(document, report)}
    </div>
    """

    hero = _render_hero(data, report)

    dimensions_html = "".join(
        _render_dimension(key, name, score_key, analyses, scores, resolution_map)
        for key, name, score_key in _DIMENSIONS
    )

    generated_at = _generated_datetime()

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>{_esc(document_title)} 评审报告</title>
<style>{_CSS}</style>
</head>
<body>
{header}
{hero}
{dimensions_html}
<div class="footer">
  <div>本报告由 AgentQA 智能需求评审自动生成</div>
  <div>生成时间：{_esc(generated_at)}</div>
</div>
</body>
</html>"""


def _generated_datetime():
    from django.utils import timezone

    try:
        return timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_review_report_pdf(document, report) -> bytes:
    """生成评审报告 PDF，返回文件字节。"""
    html_content = build_report_html(document, report)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            page = browser.new_page()
            page.set_content(html_content, wait_until="load", timeout=30000)
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=False,
                margin={
                    "top": "10mm",
                    "bottom": "10mm",
                    "left": "8mm",
                    "right": "8mm",
                },
            )
            return pdf_bytes
        finally:
            browser.close()
