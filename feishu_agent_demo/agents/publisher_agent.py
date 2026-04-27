"""
运营发布Agent
负责将审核通过的内容优化后发布
"""

import uuid
import random
from datetime import datetime
from typing import Dict, Any, Tuple
from .base_agent import BaseAgent


class ContentPublisherAgent(BaseAgent):
    """运营发布Agent：将审核通过的内容优化后发布到对应平台"""
    
    AGENT_TYPE = "publisher"
    AGENT_NAME = "运营发布员"
    
    def __init__(self, agent_id: str, settings):
        super().__init__(agent_id, settings)
        # 可以扩展发布平台配置
        self.support_platforms = ["微信公众号", "抖音", "小红书", "微博"]

    def run(self, task: Dict[str, Any], content_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """
        执行内容发布任务
        :param task: 任务信息
        :param content_record: 内容记录
        :return: (发布结果, 下一步状态)
        """
        task_id = task.get(self.settings.task_field_task_id)
        content_id = content_record.get(self.settings.content_field_content_id)
        content_text = content_record.get(self.settings.content_field_content_text, "")
        audit_result = content_record.get(self.settings.content_field_audit_result, "")
        
        self.logger.info(f"开始发布内容，任务ID: {task_id}, 内容ID: {content_id}, 审核结果: {audit_result}")
        
        system_prompt = """
        你是一个专业的运营专员，负责将内容优化后发布到各个平台。
        请根据内容类型和平台特点，优化内容的标题、标签和简介，提升传播效果。
        """
        
        prompt = f"""
        请将以下内容优化后发布：
        内容类型：{task.get(self.settings.task_field_content_type, "")}
        内容正文：{content_text[:500]}
        审核意见：{content_record.get(self.settings.content_field_audit_comment, "")}
        
        请给出：
        1. 优化后的发布标题
        2. 发布标签
        3. 发布简介
        """
        
        publish_optimization = self._call_llm(prompt, system_prompt)
        
        # 模拟发布结果
        publish_url = f"https://example.com/article/{uuid.uuid4().hex[:8]}"
        view_count = random.randint(100, 5000)
        
        self.logger.info(f"内容发布成功，发布链接: {publish_url}, 预计初始阅读量: {view_count}")
        
        # 飞书日期时间字段需要传入毫秒级时间戳（整数）
        current_timestamp = int(datetime.now().timestamp() * 1000)
        result = {
            self.settings.content_field_publish_url: publish_url,
            self.settings.content_field_publish_time: current_timestamp,
            self.settings.content_field_view_count: view_count
        }
        
        # 更新任务表的最终评分
        task_update = {
            self.settings.task_field_final_score: int(content_record.get(self.settings.content_field_quality_score, 0) or 0)
        }
        
        return {**result, **task_update}, self.settings.task_status_completed
