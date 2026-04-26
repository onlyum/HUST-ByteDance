"""
Agent 业务逻辑模块。

本 Demo 中实现一个最小可运行的“内容写作智能体”：
1. 从任务记录中提取主题；
2. 模拟调用大模型生成文案；
3. 返回生成结果，交给主流程写回飞书。

当前默认使用 Mock 流程，适合比赛演示和本地联调。
未来接入真实大模型时，只需要改本文件即可。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config import Settings


class ContentWriterAgent:
    """
    一个最小化的“内容写作 Agent”。

    在“多智能体虚拟组织”的语境下，你可以把它理解为一个虚拟员工：
    - 输入：一条待处理任务
    - 输出：一段生成后的文案
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self, task: dict[str, Any]) -> str:
        """
        执行一次任务处理。

        这里是 Agent 对外的统一入口，主程序只关心“给任务 -> 拿结果”。
        """
        topic = self._extract_topic(task)
        prompt = self._build_prompt(task)

        self.logger.info("ContentWriterAgent 开始处理任务，topic=%s", topic)

        # 统一通过 call_llm 进入模型层。
        # 这样以后从 Mock 切换到真实模型时，主流程完全不用改。
        result = self.call_llm(prompt=prompt, task=task)

        self.logger.info("ContentWriterAgent 处理完成，topic=%s", topic)
        return result

    def call_llm(self, prompt: str, task: dict[str, Any]) -> str:
        """
        统一的大模型调用入口。

        根据配置选择：
        - Mock 模式：返回一段模拟文案
        - 真实模式：通过 requests 调用外部大模型 HTTP API
        """
        if self.settings.use_mock_llm:
            return self._mock_llm_response(task=task, prompt=prompt)

        return self._call_real_llm_api(prompt=prompt)

    def _mock_llm_response(self, task: dict[str, Any], prompt: str) -> str:
        """
        Mock 一个大模型响应。

        这里故意 sleep 2 秒，用来模拟真实大模型推理耗时，
        这样在控制台里就能更直观地看到“处理中 -> 待审核”的状态流转。
        """
        topic = self._extract_topic(task)
        time.sleep(2)

        return (
            f"[AI 生成的内容] 基于主题：{topic}\n\n"
            f"这是一段用于演示飞书多维表格 Agent 流程的模拟文案。\n"
            f"它展示了外部 Python 系统如何从多维表格读取任务、"
            f"调用智能体处理，再把结果写回表格。\n\n"
            f"生成提示词摘要：{prompt}"
        )

    def _call_real_llm_api(self, prompt: str) -> str:
        """
        调用真实大模型 HTTP API。

        这是未来接入智谱 GLM、DeepSeek、Kimi、通义千问等模型时的扩展点。
        当前 Demo 已经把接口形态预留好了，只要替换 URL、Header、Payload 即可。
        """
        if not self.settings.llm_api_url:
            raise ValueError(
                "当前 USE_MOCK_LLM=false，但没有配置 LLM_API_URL，无法调用真实大模型。"
            )

        headers = {"Content-Type": "application/json"}

        # 如果模型服务需要 API Key，这里通过 Authorization 头传入。
        # 不同厂商的鉴权方式可能不同，未来接入时可按官方文档调整。
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        # 这里使用一个相对通用的 Chat Completion 风格 Payload。
        # 如果你接入的不是 OpenAI 兼容接口，只需要在这里改 JSON 结构即可。
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个负责生成中文营销文案的虚拟员工。",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }

        response = requests.post(
            url=self.settings.llm_api_url,
            headers=headers,
            json=payload,
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        return self._extract_content_from_response(data)

    @staticmethod
    def _extract_content_from_response(data: dict[str, Any]) -> str:
        """
        从真实模型接口返回值中提取文本。

        为了兼容常见的 OpenAI 风格返回结构，这里做了一个通用解析。
        如果接入的厂商返回结构不同，可以修改这里。
        """
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        # 如果不是标准结构，则直接把整个 JSON 转成字符串抛给上层，便于调试。
        return str(data)

    def _build_prompt(self, task: dict[str, Any]) -> str:
        """
        将飞书表格中的任务记录组装为给模型的提示词。

        这里先做一个简化版本，默认围绕“任务标题”生成文案。
        未来你可以在表格中继续新增“受众”“风格”“字数”等字段，然后在这里扩展。
        """
        topic = self._extract_topic(task)
        return (
            "请根据以下主题生成一段简洁、清晰、适合演示用途的中文文案："
            f"{topic}"
        )

    def _extract_topic(self, task: dict[str, Any]) -> str:
        """
        从任务字典中提取主题。

        优先读取预处理后的 title；如果不存在，再从原始 fields 中兜底提取。
        """
        title = str(task.get("title", "")).strip()
        if title:
            return title

        fields = task.get("fields", {})
        if isinstance(fields, dict):
            raw_value = fields.get(self.settings.title_field_name, "")
            return str(raw_value).strip() or "未命名主题"

        return "未命名主题"
