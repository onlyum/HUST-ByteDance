"""
数据分析Agent
负责定期分析业务数据，生成运营报告和优化建议
"""

from datetime import datetime
from typing import Dict, Any, List
from .base_agent import BaseAgent


class DataAnalysisAgent(BaseAgent):
    """数据分析Agent：定期分析业务数据，生成运营报告"""
    
    AGENT_TYPE = "analyst"
    AGENT_NAME = "数据分析师"
    
    def __init__(self, agent_id: str, settings):
        super().__init__(agent_id, settings)
        # 可以扩展分析维度配置
        self.analysis_dimensions = ["任务完成率", "内容质量", "发布效果", "用户反馈"]

    def run(self, all_tasks: List[Dict[str, Any]], all_contents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行数据分析任务
        :param all_tasks: 所有任务数据
        :param all_contents: 所有内容数据
        :return: 分析报告结果
        """
        self.logger.info(f"开始执行数据分析，总任务数: {len(all_tasks)}, 总内容数: {len(all_contents)}")
        
        # 计算核心指标
        total_tasks = len(all_tasks)
        completed_tasks = len([t for t in all_tasks if t.get(self.settings.task_field_status) == self.settings.task_status_completed])
        rejected_tasks = len([t for t in all_tasks if t.get(self.settings.task_field_status) == self.settings.task_status_rejected])
        
        # 计算质量指标
        avg_quality = 0
        if all_contents:
            quality_scores = [int(c.get(self.settings.content_field_quality_score, 0) or 0) for c in all_contents]
            avg_quality = sum(quality_scores) / len(all_contents)
        
        # 计算发布效果指标
        avg_views = 0
        published_contents = [c for c in all_contents if c.get(self.settings.content_field_publish_url)]
        if published_contents:
            view_counts = [int(c.get(self.settings.content_field_view_count, 0) or 0) for c in published_contents]
            avg_views = sum(view_counts) / len(published_contents)
        
        # 计算完成率和驳回率
        completion_rate = completed_tasks / total_tasks * 100 if total_tasks > 0 else 0
        rejection_rate = rejected_tasks / total_tasks * 100 if total_tasks > 0 else 0
        
        self.logger.info(f"核心指标计算完成：完成率={completion_rate:.1f}%, 平均质量分={avg_quality:.1f}, 平均阅读量={avg_views:.0f}")
        
        # 生成分析报告
        system_prompt = """
        你是一个专业的数据分析师，负责根据业务数据生成运营报告。
        报告要包含核心指标、趋势分析和可落地的优化建议。
        语言要简洁明了，重点突出。
        """
        
        prompt = f"""
        请根据以下数据生成内容创作运营周报：
        统计周期：{datetime.now().strftime('%Y-%m-%d')}
        核心指标：
        - 总任务数：{total_tasks}
        - 完成任务数：{completed_tasks}
        - 完成率：{completion_rate:.1f}%
        - 驳回率：{rejection_rate:.1f}%
        - 平均内容质量得分：{avg_quality:.1f}
        - 平均阅读量：{avg_views:.0f}
        
        请输出完整的周报内容，包含：
        1. 核心指标概览
        2. 趋势分析
        3. 存在的问题
        4. 优化建议
        """
        
        if self.use_mock:
            # Mock模式下生成固定格式报告
            report = f"""
# 内容创作运营周报
统计日期：{datetime.now().strftime('%Y年%m月%d日')}

## 一、核心指标概览
| 指标 | 数值 |
|------|------|
| 总任务数 | {total_tasks} |
| 完成任务数 | {completed_tasks} |
| 任务完成率 | {completion_rate:.1f}% |
| 内容驳回率 | {rejection_rate:.1f}% |
| 平均内容质量分 | {avg_quality:.1f} |
| 平均内容阅读量 | {avg_views:.0f} |

## 二、趋势分析
本周内容生产整体运行稳定，内容质量保持在中等偏上水平，驳回率在可控范围内。

## 三、存在的问题
1. 部分内容质量有待提升，驳回率偏高
2. 发布内容的阅读量差异较大，爆款内容较少

## 四、优化建议
1. 加强创作前的需求沟通，明确内容要求
2. 总结高阅读量内容的特点，形成创作规范
3. 针对驳回的内容组织专项培训，提升创作质量
            """
        else:
            # 真实模式下调用大模型生成报告
            report = self._call_llm(prompt, system_prompt)
        
        self.logger.info("数据分析报告生成完成")
        
        return {
            "report": report,
            "generated_at": datetime.now().isoformat(),
            "metrics": {
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "completion_rate": completion_rate,
                "rejection_rate": rejection_rate,
                "avg_quality_score": avg_quality,
                "avg_view_count": avg_views
            }
        }
