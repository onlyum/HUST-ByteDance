"""
Agent基类模块
定义所有Agent的标准接口和通用方法
新增Agent只需要继承BaseAgent，实现run方法即可
"""

import logging
import time
import requests
from typing import Dict, Any, Tuple
from config import Settings


class BaseAgent:
    """
    Agent基类，所有业务Agent都必须继承此类
    定义了统一的接口规范和通用能力
    """
    
    # Agent类型标识，子类必须重写
    AGENT_TYPE = "base"
    # Agent名称，子类必须重写
    AGENT_NAME = "基础Agent"
    
    def __init__(self, agent_id: str, settings: Settings):
        """
        初始化Agent
        :param agent_id: Agent唯一标识
        :param settings: 全局配置对象
        """
        self.agent_id = agent_id
        self.settings = settings
        self.use_mock = settings.use_mock_llm
        
        # 初始化日志
        self.logger = logging.getLogger(f"{self.AGENT_TYPE}_{agent_id}")
        self.logger.info(f"{self.AGENT_NAME} 初始化完成，ID: {agent_id}")

    def run(self, *args, **kwargs) -> Tuple[Dict[str, Any], str]:
        """
        执行任务的统一入口，子类必须实现
        返回: (处理结果数据, 下一步状态)
        """
        raise NotImplementedError(f"Agent {self.AGENT_NAME} 必须实现run方法")

    def _call_llm(self, prompt: str, system_prompt: str = None) -> str:
        """
        统一调用大模型接口
        :param prompt: 用户prompt
        :param system_prompt: 系统prompt，可选
        :return: 大模型返回结果
        """
        if self.use_mock:
            return self._mock_llm_response(prompt)
        
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        try:
            self.logger.info(f"开始调用大模型，prompt长度: {len(prompt)}")
            start_time = time.time()
            
            response = requests.post(
                self.settings.llm_api_url,
                headers=headers,
                json=payload,
                timeout=self.settings.llm_timeout_seconds
            )
            response.raise_for_status()
            result = response.json()
            
            elapsed = time.time() - start_time
            self.logger.info(f"大模型调用完成，耗时: {elapsed:.2f}s")
            
            return result["choices"][0]["message"]["content"].strip()
            
        except Exception as e:
            self.logger.error(f"调用大模型失败：{str(e)}")
            # 调用失败时降级使用Mock
            return self._mock_llm_response(prompt)

    def _mock_llm_response(self, prompt: str) -> str:
        """
        Mock大模型响应，用于演示流程和降级处理
        """
        time.sleep(1)  # 模拟模型调用耗时
        mock_response = f"[{self.AGENT_NAME} Mock响应] 已处理请求：{prompt[:50]}..."
        self.logger.debug(f"返回Mock响应: {mock_response}")
        return mock_response
