"""
UI 自动化落库工具

为 AI Agent 提供将 UI 自动化用例落库到 WHartTest 的能力。
Agent 通过持久化 Playwright 会话执行完功能步骤后，调用 save_ui_automation_case
将观察到的页面、元素、步骤与断言保存为可复用的 UI 自动化用例。

数据模型层级：UiModule -> UiPage -> UiElement
              UiPageSteps -> UiPageStepsDetailed
              UiTestCase -> UiCaseStepsDetailed(引用 UiPageSteps)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool as langchain_tool

logger = logging.getLogger("orchestrator_integration")

_LOCATOR_TYPES = {
    "css", "xpath", "text", "role", "label",
    "placeholder", "test_id", "id", "name",
}

# step_type 常量（与 ui_automation.models.UiPageStepsDetailed.STEP_TYPE_CHOICES 对齐）
STEP_ELEMENT = 0
STEP_ASSERT = 1


def _resolve_locator_type(raw: Optional[str]) -> str:
    """归一化定位类型，非法值兜底为 css"""
    value = (raw or "css").lower()
    return value if value in _LOCATOR_TYPES else "css"


def _get_or_create_module(project, user, name: str):
    """获取或创建一级模块"""
    from ui_automation.models import UiModule

    module, _ = UiModule.objects.get_or_create(
        project=project,
        parent=None,
        name=name.strip() or "未命名模块",
        defaults={"creator": user, "level": 1},
    )
    return module


def _get_or_create_page(project, user, module, page_data: Dict[str, Any]):
    """获取或创建页面"""
    from ui_automation.models import UiPage

    page, _ = UiPage.objects.get_or_create(
        project=project,
        module=module,
        name=(page_data.get("name") or "未命名页面").strip(),
        defaults={
            "url": page_data.get("url"),
            "description": page_data.get("description"),
            "creator": user,
        },
    )
    return page


def _get_or_create_element(page, user, elem_data: Dict[str, Any]):
    """获取或创建页面元素"""
    from ui_automation.models import UiElement

    name = (elem_data.get("name") or "未命名元素").strip()
    defaults = {
        "locator_type": _resolve_locator_type(elem_data.get("locator_type")),
        "locator_value": elem_data.get("locator_value") or "",
        "locator_index": elem_data.get("locator_index"),
        "locator_type_2": elem_data.get("locator_type_2"),
        "locator_value_2": elem_data.get("locator_value_2"),
        "locator_type_3": elem_data.get("locator_type_3"),
        "locator_value_3": elem_data.get("locator_value_3"),
        "wait_time": elem_data.get("wait_time") or 0,
        "is_iframe": bool(elem_data.get("is_iframe")),
        "iframe_locator": elem_data.get("iframe_locator"),
        "description": elem_data.get("description"),
        "creator": user,
    }
    element, _ = UiElement.objects.get_or_create(
        page=page, name=name, defaults=defaults
    )
    return element


def _build_page_steps(
    project, user, pages, elem_map, steps: List[Dict[str, Any]]
) -> List:
    """构建页面步骤（UiPageSteps + UiPageStepsDetailed）"""
    from ui_automation.models import UiPage, UiPageSteps, UiPageStepsDetailed

    page_by_name = {p.name: p for p in pages}
    page_steps = []

    for step_data in steps:
        page_name = step_data.get("page_name") or ""
        page = page_by_name.get(page_name)
        if not page:
            # 兜底取第一个页面
            page = pages[0] if pages else None
        if not page:
            continue

        module = page.module

        page_step = UiPageSteps.objects.create(
            project=project,
            page=page,
            module=module,
            name=(step_data.get("name") or "步骤").strip(),
            description=step_data.get("description"),
            creator=user,
        )

        for idx, action in enumerate(step_data.get("actions", [])):
            element = None
            elem_name = action.get("element")
            if elem_name:
                element = elem_map.get((page.name, elem_name))

            UiPageStepsDetailed.objects.create(
                page_step=page_step,
                step_type=int(action.get("step_type", STEP_ELEMENT)),
                element=element,
                step_sort=idx,
                ope_key=action.get("ope_key") or "",
                ope_value=action.get("ope_value"),
                description=action.get("description"),
            )

        page_steps.append(page_step)

    return page_steps


def _save_ui_automation_case(project_id: int, user, data: Dict[str, Any]) -> Dict[str, Any]:
    """将用例 JSON 落库，返回结果摘要"""
    from django.db import transaction

    from projects.models import Project
    from ui_automation.models import UiTestCase, UiCaseStepsDetailed

    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return {"ok": False, "error": f"项目不存在: {project_id}"}

    module_name = data.get("module_name") or "未命名模块"
    pages_data = data.get("pages", [])
    steps_data = data.get("steps", [])

    with transaction.atomic():
        module = _get_or_create_module(project, user, module_name)

        pages = []
        elem_map: Dict[tuple, Any] = {}
        for page_data in pages_data:
            page = _get_or_create_page(project, user, module, page_data)
            pages.append(page)
            for elem_data in page_data.get("elements", []):
                element = _get_or_create_element(page, user, elem_data)
                elem_map[(page.name, element.name)] = element

        page_steps = _build_page_steps(project, user, pages, elem_map, steps_data)

        case = UiTestCase.objects.create(
            project=project,
            module=module,
            name=(data.get("case_name") or "AI 生成用例").strip(),
            description=data.get("case_description"),
            level=data.get("case_level") or "P2",
            creator=user,
        )

        for idx, page_step in enumerate(page_steps):
            UiCaseStepsDetailed.objects.create(
                test_case=case,
                page_step=page_step,
                case_sort=idx,
                switch_step_open_url=bool(
                    data.get("switch_step_open_url", False)
                ),
                error_retry=int(data.get("error_retry") or 0),
            )

    return {
        "ok": True,
        "case_id": case.id,
        "case_name": case.name,
        "page_count": len(pages),
        "element_count": len(elem_map),
        "step_count": len(page_steps),
    }


def get_ui_automation_tools(
    user_id: int,
    project_id: Optional[int] = None,
    test_case_id: Optional[int] = None,
    chat_session_id: Optional[str] = None,
) -> list:
    """获取 UI 自动化落库工具列表"""
    current_user_id = user_id
    current_project_id = project_id

    @langchain_tool
    def save_ui_automation_case(case_json: str) -> str:
        """
        保存 UI 自动化测试用例（ui-automation 落库工具）。

        当你在浏览器中执行完功能测试步骤后，调用此工具将观察到的页面、元素、
        操作步骤与断言保存为可复用的 UI 自动化用例。

        case_json 为 JSON 字符串，结构如下：
        {
            "module_name": "登录模块",
            "case_name": "用户登录成功",
            "case_level": "P1",
            "case_description": "验证用户输入正确账号密码后能成功登录",
            "pages": [
                {
                    "name": "登录页",
                    "url": "https://example.com/login",
                    "elements": [
                        {"name": "用户名输入框", "locator_type": "css", "locator_value": "input[name='username']"},
                        {"name": "登录按钮", "locator_type": "text", "locator_value": "登录"}
                    ]
                }
            ],
            "steps": [
                {
                    "name": "登录操作",
                    "page_name": "登录页",
                    "actions": [
                        {"step_type": 0, "element": "用户名输入框", "ope_key": "fill", "ope_value": {"text": "admin"}},
                        {"step_type": 0, "element": "登录按钮", "ope_key": "click", "ope_value": null},
                        {"step_type": 1, "element": null, "ope_key": "assert_url", "ope_value": {"url": "https://example.com/dashboard"}}
                    ]
                }
            ]
        }

        字段约定：
        - step_type：0 表示元素操作，1 表示断言操作。
        - element：元素名称，需与 pages[].elements[].name 对应；页面级操作（goto/wait）或无需元素的断言（assert_url/assert_title）可省略。
        - ope_key：操作类型。元素操作为 click/fill/type/clear/check/select/hover/press 等；
          断言为 assert_visible/assert_text/assert_value/assert_contain_text/assert_url/assert_title 等。
        - ope_value：操作参数，为对象或 null。fill/type 用 {"text": "值"}；assert_url 用 {"url": "实际URL"}；
          assert_text 用 {"text": "实际文本"}；click 等无参操作用 null。
        - locator_type 取值：css/xpath/text/role/label/placeholder/test_id/id/name。

        重要：断言中的 URL、标题、文本必须是你执行过程中实际观察到的值，禁止猜测或编造。

        Args:
            case_json: 用例 JSON 字符串，结构如上所述。

        Returns:
            保存结果的 JSON 字符串，包含 case_id 等摘要信息，或错误信息。
        """
        from django.contrib.auth.models import User

        try:
            data = json.loads(case_json)
        except json.JSONDecodeError as e:
            return f"错误: 无效的 JSON: {e}"

        if not current_project_id:
            return "错误: 未提供项目 ID"

        user = None
        try:
            user = User.objects.get(id=current_user_id)
        except User.DoesNotExist:
            pass

        try:
            result = _save_ui_automation_case(current_project_id, user, data)
        except Exception as e:
            logger.error(f"[save_ui_automation_case] 落库失败: {e}", exc_info=True)
            return f"错误: {e}"

        if not result.get("ok"):
            return f"错误: {result.get('error')}"

        return json.dumps(result, ensure_ascii=False)

    return [save_ui_automation_case]
