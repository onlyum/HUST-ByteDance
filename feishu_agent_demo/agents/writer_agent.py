"""
内容创作者Agent
负责根据选题要求生成对应的内容
"""

import uuid
import random
from typing import Dict, Any, Tuple
from .base_agent import BaseAgent


class ContentWriterAgent(BaseAgent):
    """内容创作者Agent：根据选题要求生成符合规范的内容"""
    
    AGENT_TYPE = "writer"
    AGENT_NAME = "内容创作者"
    
    def __init__(self, agent_id: str, settings):
        super().__init__(agent_id, settings)
        # 可以扩展创作者的专属配置，比如擅长领域、写作风格等
        self.writing_style = "专业严谨"

    def run(self, task: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """
        执行内容创作任务
        :param task: 任务信息
        :return: (创作结果, 下一步状态)
        """
        task_id = task.get(self.settings.task_field_task_id)
        task_title = task.get(self.settings.task_field_title, "")
        task_requirement = task.get(self.settings.task_field_requirement, "")
        content_type = task.get(self.settings.task_field_content_type, "")
        
        self.logger.info(f"开始执行创作任务，任务ID: {task_id}, 标题: {task_title}")
        
        system_prompt = f"""
        你是一个专业的{content_type}创作专家，擅长撰写各种类型的内容。
        请严格按照用户的要求生成内容，内容要符合{self.writing_style}的风格。
        """
        
        prompt = f"""
        请生成{content_type}类型的内容：
        标题：{task_title}
        具体要求：{task_requirement}
        
        要求：
        1. 内容紧扣主题，符合要求
        2. 结构清晰，逻辑通顺
        3. 字数符合要求
        """
        
        content = self._call_llm(prompt, system_prompt)
        
        # 生成质量评分（Mock模式下随机生成，真实模式下可以通过大模型评估）
        if self.use_mock:
            quality_score = random.randint(60, 95)
        else:
            # TODO: 可以实现基于大模型的内容质量评分
            quality_score = random.randint(70, 90)
        
        self.logger.info(f"内容创作完成，质量评分: {quality_score}")
        
        result = {
            self.settings.content_field_content_id: str(uuid.uuid4()),
            # 关联字段需要传目标表的原生record_id（飞书自动生成的rec_xxx格式）
            self.settings.content_field_task_id: [task.get("record_id")],
            self.settings.content_field_writer_agent: self.agent_id,
            self.settings.content_field_content_text: content,
            self.settings.content_field_quality_score: quality_score
        }
        
        return result, self.settings.task_status_pending_audit
