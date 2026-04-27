"""
内容审核Agent
负责审核内容的合规性、质量和匹配度
"""

from datetime import datetime
from typing import Dict, Any, Tuple
from .base_agent import BaseAgent


class ContentAuditAgent(BaseAgent):
    """内容审核Agent：审核内容的合规性和质量，给出审核结果"""
    
    AGENT_TYPE = "auditor"
    AGENT_NAME = "内容审核员"
    
    def __init__(self, agent_id: str, settings):
        super().__init__(agent_id, settings)
        # 可以扩展审核规则配置
        self.audit_standards = {
            "excellent": 90,
            "good": 70,
            "failed": 60
        }

    def run(self, task: Dict[str, Any], content_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """
        执行内容审核任务
        :param task: 任务信息
        :param content_record: 内容记录
        :return: (审核结果, 下一步状态)
        """
        task_id = task.get(self.settings.task_field_task_id)
        content_id = content_record.get(self.settings.content_field_content_id)
        content_text = content_record.get(self.settings.content_field_content_text, "")
        quality_score = int(content_record.get(self.settings.content_field_quality_score, 0) or 0)
        
        self.logger.info(f"开始审核内容，任务ID: {task_id}, 内容ID: {content_id}, 当前质量分: {quality_score}")
        
        system_prompt = """
        你是一个专业的内容审核专家，负责审核内容的合规性、质量和匹配度。
        请严格按照以下标准进行审核：
        1. 90分以上：内容质量优秀，完全符合要求，直接通过
        2. 70-89分：内容整体符合要求，稍作修改即可通过
        3. 70分以下：内容质量不达标，不符合要求，驳回
        审核结果要客观公正，给出明确的审核意见。
        """
        
        prompt = f"""
        请审核以下内容：
        任务标题：{task.get(self.settings.task_field_title, "")}
        任务要求：{task.get(self.settings.task_field_requirement, "")}
        内容正文：{content_text[:1000]}  # 限制长度避免超出token
        质量得分：{quality_score}
        
        请给出：
        1. 审核结果（通过/修改后通过/驳回）
        2. 详细的审核意见
        """
        
        audit_response = self._call_llm(prompt, system_prompt)
        
        # 根据质量分决定审核结果（Mock模式下直接使用分数字段，真实模式下可以解析大模型返回结果）
        if self.use_mock:
            if quality_score >= self.audit_standards["excellent"]:
                audit_result = self.settings.audit_result_pass
                audit_comment = "内容质量优秀，完全符合要求，同意通过。"
                next_status = self.settings.task_status_pending_publish
            elif quality_score >= self.audit_standards["good"]:
                audit_result = self.settings.audit_result_modify_pass
                audit_comment = "内容整体符合要求，建议稍作修改后发布。"
                next_status = self.settings.task_status_pending_publish
            else:
                audit_result = self.settings.audit_result_reject
                audit_comment = "内容质量不达标，不符合要求，请重新创作。"
                next_status = self.settings.task_status_rejected
        else:
            # TODO: 解析大模型返回的结构化审核结果
            if quality_score >= self.audit_standards["good"]:
                audit_result = self.settings.audit_result_pass
                audit_comment = audit_response[:200]
                next_status = self.settings.task_status_pending_publish
            else:
                audit_result = self.settings.audit_result_reject
                audit_comment = audit_response[:200]
                next_status = self.settings.task_status_rejected
        
        self.logger.info(f"内容审核完成，结果: {audit_result}, 下一步状态: {next_status}")
        
        # 飞书日期时间字段需要传入毫秒级时间戳（整数）
        current_timestamp = int(datetime.now().timestamp() * 1000)
        result = {
            self.settings.content_field_audit_result: audit_result,
            self.settings.content_field_audit_comment: audit_comment,
            self.settings.content_field_audit_time: current_timestamp
        }
        
        return result, next_status
