from django.test import SimpleTestCase
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from .middleware_config import ChineseSummarizationMiddleware, get_summarization_middleware
from .response_language import (
    CHINESE_RESPONSE_INSTRUCTION,
    CHINESE_SUMMARY_PROMPT,
    is_user_visible_model_chunk,
    with_chinese_response_instruction,
    ChineseResponseMiddleware,
    has_english_prose,
    stream_with_chinese_responses,
)


class ResponseLanguageTests(SimpleTestCase):
    def test_english_progress_and_mixed_headings_are_detected(self):
        for text in (
            "I'll start by checking available knowledge base and platform tools.",
            "Let me check the knowledge base availability and the target module.",
            "Step 3：验证筛选条件", "## Phase 1：知识库检索", "Done.",
        ):
            with self.subTest(text=text):
                self.assertTrue(has_english_prose(text))

    def test_technical_literals_are_preserved(self):
        self.assertFalse(has_english_prose(
            "使用 Playwright 执行 UI 用例，`get_testcase --testcase_id 202`。\n"
            "```python\nprint('hello world')\n```\n访问 http://localhost:8913/"
        ))

    def test_translation_preserves_tool_calls_and_metadata(self):
        call = {"name": "execute_skill_script", "args": {"command": "python run.py"}, "id": "call-1", "type": "tool_call"}
        message = AIMessage(content="Let me check `get_testcase`.", tool_calls=[call], id="reply-1")
        response = SimpleNamespace(result=[message])
        model = Mock()
        model.invoke.return_value = AIMessage(content="我先检查 `get_testcase`。")
        actual = ChineseResponseMiddleware().wrap_model_call(SimpleNamespace(model=model), Mock(return_value=response))
        self.assertEqual(actual.result[0].content, "我先检查 `get_testcase`。")
        self.assertEqual(actual.result[0].tool_calls, [call])
        self.assertEqual(actual.result[0].id, "reply-1")

    async def test_async_translation_rejects_changed_technical_values(self):
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="我先检查 `delete_testcase`。")))
        response = SimpleNamespace(result=[AIMessage(content="Let me check `get_testcase`.")])
        with self.assertRaisesRegex(ValueError, "中文校验"):
            await ChineseResponseMiddleware().awrap_model_call(SimpleNamespace(model=model), AsyncMock(return_value=response))
        self.assertEqual(model.ainvoke.await_count, 2)

    async def test_chinese_graph_stream_and_history_never_contain_raw_english(self):
        from langgraph.checkpoint.memory import InMemorySaver
        saver = InMemorySaver()
        agent = create_agent(
            FakeListChatModel(responses=["Let me check the target module.", "我先检查目标模块。"]),
            middleware=[ChineseResponseMiddleware()], checkpointer=saver,
        )
        config = {"configurable": {"thread_id": "chinese-replies"}}
        events = [event async for event in stream_with_chinese_responses(
            agent, {"messages": [HumanMessage(content="生成用例")]}, config=config,
            stream_mode=["updates", "messages"],
        )]
        visible = "".join(chunk[0].content for mode, chunk in events if mode == "messages")
        self.assertEqual(visible, "我先检查目标模块。")
        state = await agent.aget_state(config)
        self.assertEqual(state.values["messages"][-1].content, visible)

    def test_functional_case_prompt_uses_shared_language_rule(self):
        from .agent_loop_view import _build_test_execution_system_prompt

        prompt = _build_test_execution_system_prompt("基础提示词", test_case_id=105)
        self.assertTrue(prompt.endswith(CHINESE_RESPONSE_INSTRUCTION))

    def test_language_rule_does_not_require_case_id_or_base_prompt(self):
        for prompt in (None, "", "继续执行"):
            with self.subTest(prompt=prompt):
                result = with_chinese_response_instruction(prompt)
                self.assertTrue(result.endswith(CHINESE_RESPONSE_INSTRUCTION))
                self.assertIn("工具调用前后的进度说明", result)
                self.assertIn("不得使用英文叙述或中英混合叙述", result)

    def test_normal_reply_is_visible(self):
        for message in (AIMessage(content="执行中"), AIMessageChunk(content="执行中")):
            self.assertTrue(is_user_visible_model_chunk((message, {"langgraph_node": "model"})))
            self.assertTrue(is_user_visible_model_chunk(message))

    def test_summary_stream_is_not_a_reply(self):
        token = AIMessageChunk(content="Context Extraction")
        for node in ("SummarizationMiddleware.before_model", "SummarizationMiddleware.abefore_model"):
            self.assertFalse(is_user_visible_model_chunk((token, {"langgraph_node": node})))
        self.assertFalse(is_user_visible_model_chunk((token, {"tags": ["langsmith:nostream"]})))

    def test_summary_wrapper_and_tools_are_not_replies(self):
        for message in (HumanMessage(content="上下文摘要"), ToolMessage(content="raw output", tool_call_id="1")):
            self.assertFalse(is_user_visible_model_chunk((message, {})))
        self.assertFalse(is_user_visible_model_chunk(()))

    def test_summary_factory_uses_chinese_prompt_and_wrapper(self):
        middleware = get_summarization_middleware(model=FakeListChatModel(responses=["摘要"]))
        self.assertIsInstance(middleware, ChineseSummarizationMiddleware)
        self.assertEqual(middleware.summary_prompt, CHINESE_SUMMARY_PROMPT)
        self.assertIn("待总结的对话：\n原始消息", middleware.summary_prompt.format(messages="原始消息"))
        self.assertEqual(middleware.name, "SummarizationMiddleware")
        self.assertEqual(middleware._build_new_messages("摘要")[0].content, "以下是此前对话的上下文摘要：\n\n摘要")

    def test_actual_graph_stream_hides_compaction_but_keeps_reply(self):
        middleware = ChineseSummarizationMiddleware(
            model=FakeListChatModel(responses=["内部上下文摘要"]),
            summary_prompt=CHINESE_SUMMARY_PROMPT,
            trigger=("messages", 4),
            keep=("messages", 1),
        )
        agent = create_agent(
            FakeListChatModel(responses=["正在继续执行"]),
            system_prompt=with_chinese_response_instruction(None),
            middleware=[middleware],
        )
        chunks = list(agent.stream({"messages": [
            HumanMessage(content="执行用例"), AIMessage(content="已执行第一步"),
            HumanMessage(content="继续"), AIMessage(content="已执行第二步"),
            HumanMessage(content="继续"),
        ]}, stream_mode="messages"))
        visible = "".join(chunk[0].content for chunk in chunks if is_user_visible_model_chunk(chunk))
        self.assertEqual(visible, "正在继续执行")
        self.assertTrue(any("SummarizationMiddleware" in str(chunk[1].get("langgraph_node")) for chunk in chunks))

    async def test_actual_async_stream_hides_compaction_but_keeps_reply(self):
        middleware = ChineseSummarizationMiddleware(
            model=FakeListChatModel(responses=["内部上下文摘要"]),
            summary_prompt=CHINESE_SUMMARY_PROMPT,
            trigger=("messages", 4),
            keep=("messages", 1),
        )
        agent = create_agent(
            FakeListChatModel(responses=["正在继续执行"]),
            system_prompt=with_chinese_response_instruction(None),
            middleware=[middleware],
        )
        chunks = [chunk async for chunk in agent.astream({"messages": [
            HumanMessage(content="执行用例"), AIMessage(content="已执行第一步"),
            HumanMessage(content="继续"), AIMessage(content="已执行第二步"),
            HumanMessage(content="继续"),
        ]}, stream_mode="messages")]
        visible = "".join(chunk[0].content for chunk in chunks if is_user_visible_model_chunk(chunk))
        self.assertEqual(visible, "正在继续执行")
        self.assertTrue(any("SummarizationMiddleware" in str(chunk[1].get("langgraph_node")) for chunk in chunks))
