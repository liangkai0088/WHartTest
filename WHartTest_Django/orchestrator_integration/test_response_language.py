from django.test import SimpleTestCase
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from .middleware_config import ChineseSummarizationMiddleware, get_summarization_middleware
from .response_language import (
    CHINESE_RESPONSE_INSTRUCTION,
    CHINESE_SUMMARY_PROMPT,
    is_user_visible_model_chunk,
    with_chinese_response_instruction,
)


class ResponseLanguageTests(SimpleTestCase):
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
