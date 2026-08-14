# -*- coding: utf-8 -*-
# @Author : 西红柿炒蛋
# @邮箱   : duanduanxc@qq.com
# @时间   : 2025/4/28 14:46

# 加载 .env 文件（本地开发时使用）
from dotenv import load_dotenv
from pathlib import Path

# 获取当前文件所在目录（WHartTest_MCP/）
current_dir = Path(__file__).parent
# 加载同目录下的 .env 文件
load_dotenv(current_dir / ".env")

from fastmcp import FastMCP
import json
import requests
from typing import Any, Dict, List, Optional
import json
import ast  # ast 模块用于安全地解析 Python 字符串文字，因为您的输入使用了单引号而不是标准的 JSON 双引号
import doctest
import time
from pydantic import Field
from pydantic.v1.networks import host_regex
import os

# mcp 初始化
mcp = FastMCP(name="WHartTest_tools")

# 从环境变量读取后端地址
# 默认使用 Docker 网络中的 backend 服务名称
base_url = os.getenv("WHARTTEST_BACKEND_URL", "http://backend:8000")

# 从环境变量读取 API Key
# 请在 .env 文件或环境变量中设置 WHARTTEST_API_KEY
api_key = os.getenv("WHARTTEST_API_KEY", "wharttest-default-mcp-key-2025")

headers = {"accept": "application/json, text/plain,*/*", "X-API-Key": api_key}


def generate_custom_id():
    """
    生成一个基于毫秒级时间戳自增 + 静态 '00000' 的 ID。

    逻辑：
    1. 获取当前毫秒时间戳 current_ms。
    2. 如果 current_ms <= 上一次的 last_ts，则 last_ts += 1；否则 last_ts = current_ms。
    3. 返回 str(last_ts) + '00000'。

    Returns:
        str: 生成的 ID，例如 '171188304512300000000'.
    """
    # 第一次调用时初始化 last_ts
    if not hasattr(generate_custom_id, "last_ts"):
        generate_custom_id.last_ts = 0

    # 获取当前毫秒级时间戳
    current_ms = int(time.time() * 1000)

    # 自增逻辑：如果时间没走或者回退，就在上次基础上 +1
    if current_ms <= generate_custom_id.last_ts:
        generate_custom_id.last_ts += 1
    else:
        generate_custom_id.last_ts = current_ms

    # 拼接固定的 '00000'
    return str(generate_custom_id.last_ts) + "00000"


@mcp.tool(description="获取WHartTest平台项目的名称和对应id")
def get_project_name_and_id() -> str:
    """获取WHartTest平台项目的名称和对应id"""
    url = base_url + "/api/projects/"

    try:
        response = requests.get(url, headers=headers)

        # 检查 HTTP 状态码
        if response.status_code != 200:
            error_info = {
                "error": f"API 请求失败",
                "status_code": response.status_code,
                "url": url,
                "response_text": response.text[:500],
            }
            return json.dumps(error_info, indent=4, ensure_ascii=False)

        # 尝试解析 JSON
        data_dict = response.json()

    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "url": url,
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except requests.exceptions.JSONDecodeError:
        error_info = {
            "error": "API 返回的不是有效的 JSON 格式",
            "status_code": response.status_code,
            "url": url,
            "response_text": response.text[:500],
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}", "url": url}
        return json.dumps(error_info, indent=4, ensure_ascii=False)

    # 用于存储提取出的 id 和 name 的列表
    extracted_data = []

    # 定义一个递归函数来处理嵌套的 children 列表
    def extract_info(nodes_list):
        if not isinstance(nodes_list, list):
            # 如果输入的不是列表，则停止或报错，取决于期望
            # 在您的结构中，data 和 children 应该是列表
            print("警告: 期望输入列表，但收到了非列表类型。")
            return

        for node in nodes_list:
            # 确保当前元素是字典
            if not isinstance(node, dict):
                print("警告: 期望列表元素是字典，但收到了非字典类型。")
                continue

            # 提取当前节点的 id 和 name
            # 使用 .get() 是安全的，即使键不存在也不会报错
            node_info = {"project_id": node.get("id"), "project_name": node.get("name")}
            extracted_data.append(node_info)

            # 如果当前节点有 children 且 children 是一个列表，则递归处理 children
            children = node.get("children")
            if isinstance(children, list):
                extract_info(children)  # 递归调用

    # 获取顶层 data 列表
    # 使用 .get('data') 是安全的，如果 'data' 键不存在，返回 None
    initial_nodes = data_dict.get("data")

    # 如果 initial_nodes 存在且是一个列表，则开始处理
    if isinstance(initial_nodes, list):
        extract_info(initial_nodes)
    else:
        print("获取到的数据结构不符合预期，未找到 'data' 列表。")

    # 将提取出的列表转换为 JSON 字符串
    # indent 参数用于格式化输出，ensure_ascii=False 保留中文字符和特殊字符
    output_json_string = json.dumps(extracted_data, indent=4, ensure_ascii=False)

    return output_json_string


@mcp.tool(description="根据WHartTest平台项目id去获取模块及id")
def module_to_which_it_belongs(project_id: int) -> str:
    """根据WHartTest平台项目id去获取模块及id"""
    url = base_url + f"/api/projects/{project_id}/testcase-modules/"

    data_dict = requests.get(url, headers=headers).json()

    # 用于存储提取出的 id 和 name 的列表
    extracted_data = []

    # 定义一个递归函数来处理嵌套的 children 列表
    def extract_info(nodes_list):
        if not isinstance(nodes_list, list):
            # 如果输入的不是列表，则停止或报错，取决于期望
            # 在您的结构中，data 和 children 应该是列表
            print("警告: 期望输入列表，但收到了非列表类型。")
            return

        for node in nodes_list:
            # 确保当前元素是字典
            if not isinstance(node, dict):
                print("警告: 期望列表元素是字典，但收到了非字典类型。")
                continue


            # 提取当前节点的 id 和 name
            # 使用 .get() 是安全的，即使键不存在也不会报错
            node_info = {"module_id": node.get("id"), "module_name": node.get("name")}
            extracted_data.append(node_info)

            # 如果当前节点有 children 且 children 是一个列表，则递归处理 children
            children = node.get("children")
            if isinstance(children, list):
                extract_info(children)  # 递归调用

    # 获取顶层 data 列表
    # 使用 .get('data') 是安全的，如果 'data' 键不存在，返回 None
    initial_nodes = data_dict.get("data")

    # 如果 initial_nodes 存在且是一个列表，则开始处理
    if isinstance(initial_nodes, list):
        extract_info(initial_nodes)
    else:
        print("获取到的数据结构不符合预期，未找到 'data' 列表。")

    # 将提取出的列表转换为 JSON 字符串
    # indent 参数用于格式化输出，ensure_ascii=False 保留中文字符和特殊字符
    output_json_string = json.dumps(extracted_data, indent=4, ensure_ascii=False)

    return output_json_string


@mcp.tool(description="获取WHartTest平台用例等级")
def obtain_use_case_level() -> list:
    """
    获取WHartTest平台用例等级
    """
    return ["P0", "P1", "P2", "P3"]


@mcp.tool(description="获取WHartTest平台测试类型")
def obtain_test_type() -> list:
    """
    获取WHartTest平台测试类型
    返回测试类型的标识和中文名称
    """
    return [
        {"value": "smoke", "label": "冒烟测试"},
        {"value": "functional", "label": "功能测试"},
        {"value": "boundary", "label": "边界测试"},
        {"value": "exception", "label": "异常测试"},
        {"value": "permission", "label": "权限测试"},
        {"value": "security", "label": "安全测试"},
        {"value": "compatibility", "label": "兼容性测试"},
    ]


@mcp.tool(description="获取WHartTest平台用例名称和对应id")
def get_the_list_of_use_cases(
    project_id: int = Field(description="项目id"),
    module_id: int = Field(description="模块id"),
):
    """获取WHartTest平台用例"""
    url = (
        base_url
        + f"/api/projects/{project_id}/testcases/?page=1&page_size=1000&search=&module_id={module_id}"
    )

    data_dict = requests.get(url, headers=headers).json()

    # 用于存储提取出的 id 和 name 的列表
    extracted_data = []

    for i in data_dict.get("data"):
        extracted_data.append({"case_id": i.get("id"), "case_name": i.get("name")})
    return json.dumps(extracted_data, indent=4, ensure_ascii=False)


@mcp.tool(description="获取WHartTest平台用例详情")
def get_case_details(
    project_id: int = Field(description="项目id"),
    case_id: int = Field(description="用例id"),
):
    """获取WHartTest平台用例详情"""
    url = base_url + f"/api/projects/{project_id}/testcases/{case_id}/"

    data_dict = requests.get(url, headers=headers).json()

    # 用于存储提取出的 id 和 name 的列表
    extracted_data = data_dict.get("data")
    return json.dumps(extracted_data, indent=4, ensure_ascii=False)


@mcp.tool(description="WHartTest平台保存操作截图到对应用例中")
def save_operation_screenshots_to_the_application_case(
    project_id: int = Field(description="项目id"),
    case_id: int = Field(description="用例id"),
    file_path: str = Field(description="文件路径"),
    title: str = Field(description="截图标题"),
    description: str = Field(description="截图描述"),
    step_number: int = Field(description="步骤编号"),
    page_url: str = Field(description="截图页面URL"),
):
    """
    WHartTest平台保存操作截图到对应用例中
    """
    try:
        # 参数验证
        if not project_id:
            return "项目id不能为空"
        if not case_id:
            return "用例id不能为空"
        if not file_path:
            return "文件路径不能为空"
        if not title:
            return "截图标题不能为空"

        # 检查文件是否存在
        import os

        if not os.path.exists(file_path):
            return f"文件不存在: {file_path}"

        url = (
            base_url
            + f"/api/projects/{project_id}/testcases/{case_id}/upload-screenshots/"
        )

        # 根据文件扩展名确定 MIME 类型
        file_ext = os.path.splitext(file_path)[1].lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
        }
        content_type = mime_types.get(file_ext, "image/png")  # 默认为 png

        # 准备文件和表单数据
        with open(file_path, "rb") as file:
            files = {"screenshots": (os.path.basename(file_path), file, content_type)}

            # 只添加有值的字段
            data = {"title": title}  # title 是必填的

            if description and description.strip():
                data["description"] = description
            if step_number is not None:
                data["step_number"] = str(step_number)
            if page_url and page_url.strip():
                data["page_url"] = page_url

            # 发起请求 - 注意这里不使用json参数，而是用data参数
            response = requests.post(url, headers=headers, files=files, data=data)

            # 检查响应状态
            response.raise_for_status()

            # 处理响应
            if response.status_code in [200, 201]:
                return f"截图 '{title}' 上传成功"
            else:
                return (
                    f"上传失败，状态码: {response.status_code}, 响应: {response.text}"
                )

    except FileNotFoundError:
        return f"文件未找到: {file_path}"
    except requests.exceptions.HTTPError as e:
        return f"HTTP错误: {e}, 响应内容: {response.text if 'response' in locals() else '无响应内容'}"
    except Exception as e:
        return f"上传截图时发生错误: {str(e)}"




@mcp.tool(description="保存WHartTest平台功能测试用例")
def add_functional_case(
    project_id: int = Field(description="项目id"),
    name: str = Field(description="用例名称"),
    precondition: str = Field(description="前置条件"),
    level: str = Field(description="用例等级，可选值：P0、P1、P2、P3"),
    module_id: int = Field(description="模块id"),
    steps: list = Field(
        description='用例步骤,示例：,[{"step_number": 1,"description": "步骤描述1","expected_result": "预期结果1"},{"step_number": 2,"description": "步骤描述2","expected_result": "预期结果2"}]'
    ),
    notes: str = Field(description="备注"),
    review_status: str = Field(
        default="pending_review",
        description="审核状态: pending_review(待审核), approved(通过), needs_optimization(优化), optimization_pending_review(优化待审核), unavailable(不可用)",
    ),
    test_type: str = Field(
        default="functional",
        description="测试类型: smoke(冒烟测试), functional(功能测试), boundary(边界测试), exception(异常测试), permission(权限测试), security(安全测试), compatibility(兼容性测试)",
    ),
):
    """
    保WHartTest平台存WHartTest平台功能测试用例
    """
    try:
        if not project_id:
            return "项目id不能为空"
        if not name:
            return "用例名称不能为空"
        if not precondition:
            return "前置条件不能为空"
        if not level:
            return "用例等级不能为空"

        # 验证用例等级是否为合法值
        valid_levels = ["P0", "P1", "P2", "P3"]
        if level not in valid_levels:
            return f"用例等级必须是以下值之一：{', '.join(valid_levels)}，当前值为：{level}"

        # 验证测试类型是否为合法值
        valid_test_types = [
            "smoke",
            "functional",
            "boundary",
            "exception",
            "permission",
            "security",
            "compatibility",
        ]
        if test_type and test_type not in valid_test_types:
            return f"测试类型必须是以下值之一：{', '.join(valid_test_types)}，当前值为：{test_type}"

        if not module_id:
            return "模块id不能为空"
        if not steps:
            return "用例步骤不能为空"

        url = base_url + f"/api/projects/{project_id}/testcases/"
        data = {
            "name": name,
            "precondition": precondition,
            "level": level,
            "module_id": module_id,
            "steps": steps,
            "notes": notes,
            "review_status": review_status,
            "test_type": test_type,
        }

        # 发起请求
        response = requests.post(url, headers=headers, json=data)
        print("status =", response.status_code)
        print("content-type =", response.headers.get("Content-Type"))
        print("body-preview =", response.text[:200])
        # 如有非 2xx 状态码直接抛异常
        response.raise_for_status()

        response_payload = {}
        try:
            response_payload = response.json()
        except ValueError:
            pass

        created_case = {}
        if isinstance(response_payload, dict):
            created_case = response_payload.get("data") or response_payload

        # 返回详细的用例信息,而不是简单的"保存成功"
        testcase_snapshot = {
            "id": created_case.get("id"),
            "name": created_case.get("name", name),
            "module_id": created_case.get("module_id") or module_id,
            "level": created_case.get("level") or level,
            "precondition": created_case.get("precondition") or precondition,
            "notes": created_case.get("notes") or notes,
            "steps": created_case.get("steps") or steps,
            "project_id": created_case.get("project") or project_id,
        }

        # 201，代表成功保存
        if response.json().get("code") == 201:
            return {
                "message": "保存成功",
                "testcase": {
                    "id": created_case.get("id"),
                    "name": created_case.get("name", name),
                },
            }
        else:
            return {"message": "保存失败，请重试", "response": response_payload}
    except requests.exceptions.HTTPError as e:
        print("HTTPError =", e)
        return e



@mcp.tool(description="编辑WHartTest平台功能测试用例")
def edit_functional_case(
    project_id: int = Field(description="项目id"),
    case_id: int = Field(description="用例id"),
    name: str = Field(description="用例名称"),
    precondition: str = Field(description="前置条件"),
    level: str = Field(description="用例等级，可选值：P0、P1、P2、P3"),
    module_id: int = Field(description="模块id"),
    steps: list = Field(
        description='用例步骤,示例：,[{"step_number": 1,"description": "步骤描述1","expected_result": "预期结果1"},{"step_number": 2,"description": "步骤描述2","expected_result": "预期结果2"}]'
    ),
    notes: str = Field(description="备注"),
    review_status: str = Field(
        default=None,
        description="审核状态(可选): pending_review(待审核), approved(通过), needs_optimization(优化), optimization_pending_review(优化待审核), unavailable(不可用)",
    ),
    is_optimization: bool = Field(
        default=False,
        description="是否为优化操作，True时自动设为optimization_pending_review",
    ),
    test_type: str = Field(
        default=None,
        description="测试类型(可选): smoke(冒烟测试), functional(功能测试), boundary(边界测试), exception(异常测试), permission(权限测试), security(安全测试), compatibility(兼容性测试)",
    ),
):
    """
    编辑WHartTest平台功能测试用例
    """
    try:
        if not project_id:
            return "项目id不能为空"
        if not case_id:
            return "用例id不能为空"


        url = base_url + f"/api/projects/{project_id}/testcases/{case_id}/"
        data = {
            "name": name,
            "precondition": precondition,
            "level": level,
            "module_id": module_id,
            "steps": steps,
            "notes": notes,
        }

        # 验证用例等级是否为合法值
        valid_levels = ["P0", "P1", "P2", "P3"]
        if level not in valid_levels:
            return f"用例等级必须是以下值之一：{', '.join(valid_levels)}，当前值为：{level}"

        # 验证测试类型是否为合法值
        valid_test_types = [
            "smoke",
            "functional",
            "boundary",
            "exception",
            "permission",
            "security",
            "compatibility",
        ]
        if test_type:
            if test_type not in valid_test_types:
                return f"测试类型必须是以下值之一：{', '.join(valid_test_types)}，当前值为：{test_type}"
            data["test_type"] = test_type

        # 处理优化工作流
        if is_optimization:
            data["review_status"] = "optimization_pending_review"
        elif review_status:
            data["review_status"] = review_status

        # 发起请求
        response = requests.patch(url, headers=headers, json=data)
        print("status =", response.status_code)
        print("content-type =", response.headers.get("Content-Type"))
        print("body-preview =", response.text[:200])
        # 如有非 2xx 状态码直接抛异常
        response.raise_for_status()
        # 200，代表成功编辑
        if response.json().get("code") == 200:
            return f"用例：{name}编辑成功"
        else:
            return "编辑失败，请重试"
    except requests.exceptions.HTTPError as e:
        print("HTTPError =", e)
        return e


# ============ 图表生成工具 ============




@mcp.tool(
    description="创建新的drawio图表。当用户要求创建新图表或从头开始绘制时使用此工具。如果用户要求在新页面创建图表，请设置page_name参数。"
)
def display_diagram(
    xml: str = Field(description="完整的drawio XML内容，必须是有效的mxGraphModel格式"),
    page_name: str = Field(
        default="",
        description="可选的页面名称。如果指定，将创建新页面而不是替换现有图表。例如：'小狗图表'、'流程图2'",
    ),
) -> str:
    """
    创建新的drawio图表

    Args:
        xml: 完整的drawio XML内容
        page_name: 可选，指定页面名称时会添加为新页面

    Returns:
        成功或失败信息
    """
    # 验证XML基本结构
    if not xml or not xml.strip():
        return json.dumps(
            {"success": False, "error": "XML内容不能为空"}, ensure_ascii=False
        )

    # 检查是否包含必要的drawio结构
    if "<mxGraphModel" not in xml or "<root>" not in xml:
        return json.dumps(
            {
                "success": False,
                "error": "无效的drawio XML格式，必须包含mxGraphModel和root元素",
            },
            ensure_ascii=False,
        )

    # 返回成功，包含XML内容供前端渲染
    result = {
        "success": True,
        "action": "display",
        "xml": xml,
        "message": "图表创建成功",
    }

    # 如果指定了页面名称，添加到结果中
    if page_name and page_name.strip():
        result["page_name"] = page_name.strip()
        result["message"] = f"图表页面 '{page_name}' 创建成功"

    return json.dumps(result, ensure_ascii=False)


@mcp.tool(
    description="""编辑现有的drawio图表。支持以下操作类型：
- replace_page: 替换指定页面的完整内容（推荐，最可靠）
- add: 在指定页面添加新元素
- delete: 删除指定ID的元素
- update: 更新元素的属性

优先使用 replace_page 操作，因为它最可靠。"""
)
def edit_diagram(
    operations: str = Field(
        description="""JSON格式的操作列表。每个操作是一个对象，包含：
- action: 操作类型，可选 "replace_page" | "add" | "delete" | "update"
- page_index: 目标页面索引（从0开始，默认0）

replace_page 操作（推荐）：
- page_xml: 完整的页面 mxGraphModel XML
- page_name: 可选，页面名称

add 操作：
- element: 要添加的 mxCell XML

delete 操作：
- element_id: 要删除的元素ID

update 操作：
- element_id: 要更新的元素ID
- properties: 要更新的属性对象，如 {"value": "新文本", "style": "新样式"}

示例：
[{"action": "replace_page", "page_index": 1, "page_name": "小猫", "page_xml": "<mxGraphModel>...</mxGraphModel>"}]
"""
    ),
) -> str:
    """
    编辑现有的drawio图表（企业级 DOM 操作）

    Args:
        operations: JSON字符串，包含操作列表

    Returns:
        成功或失败信息，包含操作供前端执行
    """
    # 解析操作
    try:
        if isinstance(operations, str):
            op_list = json.loads(operations)
        else:
            op_list = operations
    except json.JSONDecodeError as e:
        return json.dumps(
            {"success": False, "error": f"无法解析操作JSON: {str(e)}"},
            ensure_ascii=False,
        )

    # 验证操作格式
    if not isinstance(op_list, list):
        return json.dumps(
            {"success": False, "error": "operations必须是一个数组"}, ensure_ascii=False
        )

    valid_actions = ["replace_page", "add", "delete", "update"]
    validated_ops = []

    for i, op in enumerate(op_list):
        if not isinstance(op, dict):
            return json.dumps(
                {"success": False, "error": f"第{i + 1}个操作必须是对象"},
                ensure_ascii=False,
            )

        action = op.get("action")
        if action not in valid_actions:
            return json.dumps(
                {
                    "success": False,
                    "error": f"第{i + 1}个操作的action无效，必须是: {', '.join(valid_actions)}",
                },
                ensure_ascii=False,
            )

        validated_op = {"action": action, "pageIndex": op.get("page_index", 0)}

        # 验证各操作类型的必需字段
        if action == "replace_page":
            if "page_xml" not in op:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"第{i + 1}个操作(replace_page)缺少page_xml字段",
                    },
                    ensure_ascii=False,
                )
            validated_op["pageXml"] = op["page_xml"]
            if "page_name" in op:
                validated_op["pageName"] = op["page_name"]

        elif action == "add":
            if "element" not in op:
                return json.dumps(
                    {"success": False, "error": f"第{i + 1}个操作(add)缺少element字段"},
                    ensure_ascii=False,
                )
            validated_op["element"] = op["element"]

        elif action == "delete":
            if "element_id" not in op:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"第{i + 1}个操作(delete)缺少element_id字段",
                    },
                    ensure_ascii=False,
                )
            validated_op["elementId"] = op["element_id"]

        elif action == "update":
            if "element_id" not in op or "properties" not in op:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"第{i + 1}个操作(update)缺少element_id或properties字段",
                    },
                    ensure_ascii=False,
                )
            validated_op["elementId"] = op["element_id"]
            validated_op["properties"] = op["properties"]

        validated_ops.append(validated_op)

    if not validated_ops:
        return json.dumps(
            {"success": False, "error": "至少需要一个操作"}, ensure_ascii=False
        )

    # 返回成功，包含操作供前端执行
    return json.dumps(
        {
            "success": True,
            "action": "edit",
            "operations": validated_ops,
            "message": f"已准备{len(validated_ops)}个编辑操作",
        },
        ensure_ascii=False,
    )


# ============ 代码分析工具（code_analysis 后端） ============


def _code_analysis_error(action, url, response):
    """
    构造后端非 2xx 响应的结构化错误信息

    Args:
        action: 操作描述
        url: 请求地址
        response: requests 响应对象

    Returns:
        str: 格式化后的错误 JSON 字符串
    """
    error_info = {
        "error": f"API 请求失败: {action}",
        "status_code": response.status_code,
        "url": url,
        "response_text": response.text[:500],
    }
    return json.dumps(error_info, indent=4, ensure_ascii=False)


@mcp.tool(description="从本地zip压缩包创建代码项目并上传，返回代码项目id、快照id和文件数量")
def create_code_project_from_zip(
    project_id: int = Field(description="项目id"),
    project_name: str = Field(description="代码项目名称"),
    zip_path: str = Field(description="本地zip压缩包文件路径"),
) -> str:
    """
    从本地zip压缩包创建代码项目并上传快照

    Args:
        project_id: WHartTest平台项目id
        project_name: 代码项目名称
        zip_path: 本地zip文件路径

    Returns:
        代码项目id、快照id和文件数量
    """
    try:
        # 参数验证
        if not project_id:
            return "项目id不能为空"
        if not project_name:
            return "项目名称不能为空"
        if not zip_path:
            return "zip文件路径不能为空"

        # 检查文件是否存在
        if not os.path.exists(zip_path):
            return f"文件不存在: {zip_path}"

        # 第一步：创建代码项目
        create_url = base_url + f"/api/projects/{project_id}/code/projects/"
        create_response = requests.post(
            create_url,
            headers=headers,
            json={"name": project_name, "source_type": "zip_upload"},
        )
        if create_response.status_code not in [200, 201]:
            return _code_analysis_error("创建代码项目", create_url, create_response)

        create_data = create_response.json().get("data") or {}
        code_project_id = create_data.get("id")
        if not code_project_id:
            return json.dumps(
                {
                    "error": "创建代码项目成功但未返回项目id",
                    "response": create_data,
                },
                indent=4,
                ensure_ascii=False,
            )

        # 第二步：上传zip快照（multipart，字段名 file）
        upload_url = (
            base_url
            + f"/api/projects/{project_id}/code/projects/{code_project_id}/upload/"
        )
        with open(zip_path, "rb") as file:
            zip_bytes = file.read()

        file_ext = os.path.splitext(zip_path)[1].lower()
        mime_types = {".tar": "application/x-tar", ".gz": "application/gzip", ".tgz": "application/gzip"}
        content_type = mime_types.get(file_ext, "application/zip")  # 默认为 zip

        files = {"file": (os.path.basename(zip_path), zip_bytes, content_type)}
        upload_response = requests.post(upload_url, headers=headers, files=files)
        if upload_response.status_code not in [200, 201]:
            return _code_analysis_error("上传代码项目zip", upload_url, upload_response)

        snapshot_data = upload_response.json().get("data") or {}
        snapshot_id = snapshot_data.get("id") or snapshot_data.get("snapshot_id")

        # 文件数量：优先从快照响应中读取，缺失时通过文件列表接口统计
        file_count = snapshot_data.get("file_count")
        if file_count is None:
            file_count = snapshot_data.get("files_count")
        if file_count is None and isinstance(snapshot_data.get("files"), list):
            file_count = len(snapshot_data["files"])

        if file_count is None:
            try:
                files_url = (
                    base_url
                    + f"/api/projects/{project_id}/code/projects/{code_project_id}/files/"
                )
                files_params = {}
                if snapshot_id:
                    files_params["snapshot_id"] = snapshot_id
                files_response = requests.get(files_url, headers=headers, params=files_params)
                if files_response.status_code == 200:
                    files_data = files_response.json().get("data") or []
                    if isinstance(files_data, dict) and isinstance(files_data.get("results"), list):
                        files_data = files_data["results"]
                    if isinstance(files_data, list):
                        file_count = len(files_data)
            except Exception:
                pass

        return json.dumps(
            {
                "message": "代码项目创建并上传成功",
                "code_project_id": code_project_id,
                "snapshot_id": snapshot_id,
                "file_count": file_count,
                "project_name": create_data.get("name") or project_name,
            },
            indent=4,
            ensure_ascii=False,
        )

    except FileNotFoundError:
        return f"文件未找到: {zip_path}"
    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "url": create_url if "create_url" in locals() else base_url,
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}"}
        return json.dumps(error_info, indent=4, ensure_ascii=False)


@mcp.tool(description="分析OpenAPI/Swagger接口文档，生成接口测试用例建议")
def analyze_openapi_spec(
    project_id: int = Field(description="项目id"),
    code_project_id: int = Field(description="代码项目id"),
    spec_path_or_url: str = Field(description="OpenAPI规范的本地文件路径或http(s)在线地址"),
) -> str:
    """
    分析OpenAPI/Swagger接口文档，生成接口测试用例建议

    Args:
        project_id: WHartTest平台项目id
        code_project_id: 代码项目id
        spec_path_or_url: 支持 http(s) 在线地址或本地 json/yaml 文件路径

    Returns:
        任务id和状态
    """
    try:
        # 参数验证
        if not project_id:
            return "项目id不能为空"
        if not spec_path_or_url:
            return "spec_path_or_url不能为空"

        url = base_url + f"/api/projects/{project_id}/code/spec-analysis/"
        spec_path_or_url = spec_path_or_url.strip()

        if spec_path_or_url.lower().startswith("http://") or spec_path_or_url.lower().startswith(
            "https://"
        ):
            # 在线地址：JSON 请求体
            payload = {"spec_url": spec_path_or_url}
            if code_project_id:
                payload["code_project_id"] = code_project_id
            response = requests.post(url, headers=headers, json=payload)
        else:
            # 本地文件：multipart 上传（字段名 file）
            if not os.path.exists(spec_path_or_url):
                return f"文件不存在: {spec_path_or_url}"
            with open(spec_path_or_url, "rb") as file:
                spec_bytes = file.read()

            file_ext = os.path.splitext(spec_path_or_url)[1].lower()
            mime_types = {
                ".yaml": "application/x-yaml",
                ".yml": "application/x-yaml",
                ".txt": "text/plain",
            }
            content_type = mime_types.get(file_ext, "application/json")

            files = {
                "file": (os.path.basename(spec_path_or_url), spec_bytes, content_type)
            }
            data = {}
            if code_project_id:
                data["code_project_id"] = str(code_project_id)
            response = requests.post(url, headers=headers, files=files, data=data)

        if response.status_code not in [200, 201]:
            return _code_analysis_error("提交OpenAPI规范分析", url, response)

        task_data = response.json().get("data") or {}
        return json.dumps(
            {
                "message": "OpenAPI规范分析任务提交成功",
                "task_id": task_data.get("id") or task_data.get("task_id"),
                "status": task_data.get("status"),
            },
            indent=4,
            ensure_ascii=False,
        )

    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}"}
        return json.dumps(error_info, indent=4, ensure_ascii=False)


@mcp.tool(description="获取OpenAPI接口分析的建议列表")
def list_spec_suggestions(
    project_id: int = Field(description="项目id"),
    analysis_task_id: int = Field(description="接口分析任务id"),
    status: str = Field(
        default="pending",
        description="建议状态过滤: pending(待处理), approved(已通过), rejected(已拒绝)",
    ),
) -> str:
    """
    获取OpenAPI接口分析的建议列表

    Args:
        project_id: WHartTest平台项目id
        analysis_task_id: 接口分析任务id
        status: 建议状态过滤

    Returns:
        建议列表（id、name、method、path、priority、steps数量）
    """
    try:
        if not project_id:
            return "项目id不能为空"
        if not analysis_task_id:
            return "分析任务id不能为空"

        url = (
            base_url
            + f"/api/projects/{project_id}/code/spec-analysis/{analysis_task_id}/suggestions/"
        )
        response = requests.get(url, headers=headers, params={"status": status})

        if response.status_code != 200:
            return _code_analysis_error("获取接口分析建议", url, response)

        data = response.json().get("data") or []
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = data["results"]
        if not isinstance(data, list):
            data = [data] if data else []

        suggestions = []
        for item in data:
            steps = item.get("steps")
            suggestions.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "method": item.get("method"),
                    "path": item.get("path"),
                    "priority": item.get("priority"),
                    "steps_count": len(steps) if isinstance(steps, list) else None,
                }
            )

        return json.dumps({"suggestions": suggestions}, indent=4, ensure_ascii=False)

    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}"}
        return json.dumps(error_info, indent=4, ensure_ascii=False)


@mcp.tool(description="批量通过OpenAPI接口分析的建议")
def approve_spec_suggestions(
    project_id: int = Field(description="项目id"),
    analysis_task_id: int = Field(description="接口分析任务id"),
    suggestion_ids: list = Field(description="要建议通过的id列表, 示例: [1, 2, 3]"),
) -> str:
    """
    批量通过OpenAPI接口分析的建议

    Args:
        project_id: WHartTest平台项目id
        analysis_task_id: 接口分析任务id
        suggestion_ids: 建议id列表

    Returns:
        每个建议的处理结果
    """
    try:
        if not project_id:
            return "项目id不能为空"
        if not analysis_task_id:
            return "分析任务id不能为空"
        if not suggestion_ids:
            return "suggestion_ids不能为空"

        url = (
            base_url
            + f"/api/projects/{project_id}/code/spec-analysis/{analysis_task_id}/approve/"
        )
        response = requests.post(
            url, headers=headers, json={"suggestion_ids": suggestion_ids}
        )

        if response.status_code not in [200, 201]:
            return _code_analysis_error("通过接口分析建议", url, response)

        data = response.json().get("data") or {}
        return json.dumps(
            {"message": "接口分析建议通过成功", "results": data},
            indent=4,
            ensure_ascii=False,
        )

    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}"}
        return json.dumps(error_info, indent=4, ensure_ascii=False)


@mcp.tool(description="分析前端组件，生成组件测试用例建议")
def analyze_frontend_components(
    project_id: int = Field(description="项目id"),
    code_project_id: int = Field(description="代码项目id"),
    snapshot_id: int = Field(
        default=None, description="可选，指定要分析的代码快照id"
    ),
    file_filter: list = Field(
        default=None,
        description="可选，指定要分析的文件路径过滤列表, 示例: ['src/App.vue', 'src/components/']",
    ),
) -> str:
    """
    分析前端组件，生成组件测试用例建议

    Args:
        project_id: WHartTest平台项目id
        code_project_id: 代码项目id
        snapshot_id: 可选，代码快照id
        file_filter: 可选，文件路径过滤列表

    Returns:
        任务id和状态
    """
    try:
        if not project_id:
            return "项目id不能为空"
        if not code_project_id:
            return "代码项目id不能为空"

        url = base_url + f"/api/projects/{project_id}/code/component-analysis/"
        payload = {"code_project_id": code_project_id}
        if snapshot_id is not None:
            payload["snapshot_id"] = snapshot_id
        if file_filter is not None:
            payload["file_filter"] = file_filter

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code not in [200, 201]:
            return _code_analysis_error("提交前端组件分析", url, response)

        task_data = response.json().get("data") or {}
        return json.dumps(
            {
                "message": "前端组件分析任务提交成功",
                "task_id": task_data.get("id") or task_data.get("task_id"),
                "status": task_data.get("status"),
            },
            indent=4,
            ensure_ascii=False,
        )

    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}"}
        return json.dumps(error_info, indent=4, ensure_ascii=False)


@mcp.tool(description="获取前端组件分析的元素建议列表")
def list_element_suggestions(
    project_id: int = Field(description="项目id"),
    task_id: int = Field(description="前端组件分析任务id"),
    status: str = Field(
        default="pending",
        description="建议状态过滤: pending(待处理), approved(已通过), rejected(已拒绝)",
    ),
) -> str:
    """
    获取前端组件分析的元素建议列表

    Args:
        project_id: WHartTest平台项目id
        task_id: 前端组件分析任务id
        status: 建议状态过滤

    Returns:
        元素建议列表（id、page_name、file_path、element_name、locator槽位）
    """
    try:
        if not project_id:
            return "项目id不能为空"
        if not task_id:
            return "分析任务id不能为空"

        url = (
            base_url
            + f"/api/projects/{project_id}/code/component-analysis/{task_id}/element-suggestions/"
        )
        response = requests.get(url, headers=headers, params={"status": status})

        if response.status_code != 200:
            return _code_analysis_error("获取元素建议", url, response)

        data = response.json().get("data") or []
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = data["results"]
        if not isinstance(data, list):
            data = [data] if data else []

        suggestions = []
        for item in data:
            locator = item.get("locator")
            if isinstance(locator, dict):
                locator_slots = locator.get("slots")
            else:
                locator_slots = item.get("locator_slots")
            suggestions.append(
                {
                    "id": item.get("id"),
                    "page_name": item.get("page_name"),
                    "file_path": item.get("file_path"),
                    "element_name": item.get("element_name"),
                    "locator_slots": locator_slots,
                }
            )

        return json.dumps({"suggestions": suggestions}, indent=4, ensure_ascii=False)

    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}"}
        return json.dumps(error_info, indent=4, ensure_ascii=False)


@mcp.tool(description="批量通过前端组件分析的元素建议")
def approve_element_suggestions(
    project_id: int = Field(description="项目id"),
    task_id: int = Field(description="前端组件分析任务id"),
    suggestion_ids: list = Field(description="要建议通过的元素id列表, 示例: [1, 2, 3]"),
) -> str:
    """
    批量通过前端组件分析的元素建议

    Args:
        project_id: WHartTest平台项目id
        task_id: 前端组件分析任务id
        suggestion_ids: 元素建议id列表

    Returns:
        每个建议的处理结果
    """
    try:
        if not project_id:
            return "项目id不能为空"
        if not task_id:
            return "分析任务id不能为空"
        if not suggestion_ids:
            return "suggestion_ids不能为空"

        url = (
            base_url
            + f"/api/projects/{project_id}/code/component-analysis/{task_id}/approve/"
        )
        response = requests.post(
            url, headers=headers, json={"suggestion_ids": suggestion_ids}
        )

        if response.status_code not in [200, 201]:
            return _code_analysis_error("通过元素建议", url, response)

        data = response.json().get("data") or {}
        return json.dumps(
            {"message": "元素建议通过成功", "results": data},
            indent=4,
            ensure_ascii=False,
        )

    except requests.exceptions.ConnectionError:
        error_info = {
            "error": "无法连接到 API 服务器",
            "base_url": base_url,
            "suggestion": "请检查后端服务是否启动，或检查 WHARTTEST_BACKEND_URL 环境变量配置",
        }
        return json.dumps(error_info, indent=4, ensure_ascii=False)
    except Exception as e:
        error_info = {"error": f"未知错误: {str(e)}"}
        return json.dumps(error_info, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    # 使用 streamable-http 传输方式
    # host="0.0.0.0" 允许从其他容器访问
    # port=8006 指定端口
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8006)
