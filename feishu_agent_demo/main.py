"""
主程序入口模块。

本文件负责：
1. 加载配置、初始化依赖
2. 实现多Agent任务调度逻辑
3. 处理业务流程状态流转
4. 定时执行数据分析任务

流程架构：
待分配 → 分配给创作者 → 待创作 → 创作者生成内容 → 待审核 → 审核员审核 → 
   ↓(通过)                          ↓(驳回)
待发布 → 发布员发布 → 已完成        已驳回
"""

import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any

from config import load_settings
from feishu_client import FeishuBitableClient
from agents import (
    ContentWriterAgent,
    ContentAuditAgent,
    ContentPublisherAgent,
    DataAnalysisAgent
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Agent调度器，负责协调各个Agent的工作流程"""
    
    def __init__(self):
        self.settings = load_settings()
        self.bitable_client = FeishuBitableClient(self.settings)
        
        # 初始化所有Agent
        self.writer_agent = ContentWriterAgent("agent_writer_01", self.settings)
        self.auditor_agent = ContentAuditAgent("agent_auditor_01", self.settings)
        self.publisher_agent = ContentPublisherAgent("agent_publisher_01", self.settings)
        self.analyst_agent = DataAnalysisAgent("agent_analyst_01", self.settings)
        
        # 数据分析定时器，默认每天执行一次
        self.last_analysis_time = datetime.now() - timedelta(days=1)
        self.analysis_interval = timedelta(days=1)
        
        logger.info("Agent调度器初始化完成，所有Agent已就绪")

    def process_pending_assign_tasks(self):
        """处理待分配的任务：自动分配Agent"""
        tasks = self.bitable_client.get_tasks_by_status(self.settings.task_status_pending_assign)
        
        for task in tasks:
            try:
                task_id = task.get(self.settings.task_field_task_id)
                record_id = task.get("record_id")
                logger.info(f"开始分配任务：{task_id}")
                
                # 自动分配Agent（这里简单分配固定Agent，可扩展为负载均衡策略）
                update_fields = {
                    self.settings.task_field_creator_agent: self.writer_agent.agent_id,
                    self.settings.task_field_auditor_agent: self.auditor_agent.agent_id,
                    self.settings.task_field_publisher_agent: self.publisher_agent.agent_id,
                    self.settings.task_field_status: self.settings.task_status_pending_write
                }
                
                self.bitable_client.update_task_fields(record_id, update_fields)
                logger.info(f"任务分配完成：{task_id}，状态更新为待创作")
                
            except Exception as e:
                logger.error(f"处理任务分配失败，task_id={task_id}：{str(e)}")
                logger.error(traceback.format_exc())

    def process_pending_write_tasks(self):
        """处理待创作的任务：调用创作者Agent生成内容"""
        tasks = self.bitable_client.get_tasks_by_status(self.settings.task_status_pending_write)
        
        for task in tasks:
            try:
                task_id = task.get(self.settings.task_field_task_id)
                record_id = task.get("record_id")
                logger.info(f"开始创作内容，任务：{task_id}")
                
                # 调用创作者Agent
                content_result, next_status = self.writer_agent.run(task)
                
                # 创建内容记录
                self.bitable_client.create_content_record(content_result)
                
                # 更新任务状态
                self.bitable_client.update_task_fields(
                    record_id,
                    {self.settings.task_field_status: next_status}
                )
                
                logger.info(f"内容创作完成，任务：{task_id}，状态更新为：{next_status}")
                
            except Exception as e:
                logger.error(f"内容创作失败，task_id={task_id}：{str(e)}")
                logger.error(traceback.format_exc())
                # 更新状态为失败
                try:
                    self.bitable_client.update_task_fields(
                        record_id,
                        {self.settings.task_field_status: self.settings.task_status_rejected}
                    )
                except:
                    pass

    def process_pending_audit_tasks(self):
        """处理待审核的任务：调用审核员Agent审核内容"""
        tasks = self.bitable_client.get_tasks_by_status(self.settings.task_status_pending_audit)
        
        for task in tasks:
            try:
                task_id = task.get(self.settings.task_field_task_id)
                record_id = task.get("record_id")
                logger.info(f"开始审核内容，任务：{task_id}")
                
                # 查询对应的内容记录
                content_record = self.bitable_client.get_content_by_task_id(task_id)
                if not content_record:
                    logger.warning(f"未找到任务对应的内容记录，task_id={task_id}")
                    continue
                
                # 调用审核员Agent
                audit_result, next_status = self.auditor_agent.run(task, content_record)
                
                # 更新内容记录
                self.bitable_client.update_content_record(
                    content_record["record_id"],
                    audit_result
                )
                
                # 更新任务状态
                self.bitable_client.update_task_fields(
                    record_id,
                    {self.settings.task_field_status: next_status}
                )
                
                logger.info(f"内容审核完成，任务：{task_id}，结果：{audit_result[self.settings.content_field_audit_result]}，状态更新为：{next_status}")
                
            except Exception as e:
                logger.error(f"内容审核失败，task_id={task_id}：{str(e)}")
                logger.error(traceback.format_exc())

    def process_pending_publish_tasks(self):
        """处理待发布的任务：调用发布员Agent发布内容"""
        tasks = self.bitable_client.get_tasks_by_status(self.settings.task_status_pending_publish)
        
        for task in tasks:
            try:
                task_id = task.get(self.settings.task_field_task_id)
                record_id = task.get("record_id")
                logger.info(f"开始发布内容，任务：{task_id}")
                
                # 查询对应的内容记录
                content_record = self.bitable_client.get_content_by_task_id(task_id)
                if not content_record:
                    logger.warning(f"未找到任务对应的内容记录，task_id={task_id}")
                    continue
                
                # 调用发布员Agent
                publish_result, next_status = self.publisher_agent.run(task, content_record)
                
                # 提取任务更新字段和内容更新字段
                task_update_fields = {
                    self.settings.task_field_final_score: publish_result.pop(self.settings.task_field_final_score, 0),
                    self.settings.task_field_status: next_status
                }
                
                # 更新内容记录
                self.bitable_client.update_content_record(
                    content_record["record_id"],
                    publish_result
                )
                
                # 更新任务状态
                self.bitable_client.update_task_fields(
                    record_id,
                    task_update_fields
                )
                
                logger.info(f"内容发布完成，任务：{task_id}，状态更新为：{next_status}")
                
            except Exception as e:
                logger.error(f"内容发布失败，task_id={task_id}：{str(e)}")
                logger.error(traceback.format_exc())

    def run_data_analysis_if_needed(self):
        """如果到了分析时间，执行数据分析"""
        now = datetime.now()
        if now - self.last_analysis_time >= self.analysis_interval:
            logger.info("开始执行定期数据分析")
            try:
                all_tasks = self.bitable_client.get_all_tasks()
                all_contents = self.bitable_client.get_all_contents()
                
                analysis_result = self.analyst_agent.run(all_tasks, all_contents)
                
                # 打印分析报告
                logger.info("\n" + "="*50)
                logger.info("数据分析报告")
                logger.info("="*50)
                logger.info(analysis_result["report"])
                logger.info("="*50 + "\n")
                
                # TODO: 可以将报告发送到飞书群或者保存到多维表格
                self.last_analysis_time = now
                logger.info("数据分析完成")
                
            except Exception as e:
                logger.error(f"数据分析失败：{str(e)}")
                logger.error(traceback.format_exc())

    def run_one_cycle(self):
        """执行一个完整的轮询周期"""
        logger.info("开始新的轮询周期")
        
        # 按流程顺序处理不同状态的任务
        self.process_pending_assign_tasks()
        self.process_pending_write_tasks()
        self.process_pending_audit_tasks()
        self.process_pending_publish_tasks()
        
        # 检查是否需要执行数据分析
        self.run_data_analysis_if_needed()
        
        logger.info(f"轮询周期结束，等待 {self.settings.poll_interval_seconds} 秒后继续...")

    def run_forever(self):
        """持续运行调度器"""
        logger.info("多Agent虚拟组织系统启动成功！")
        logger.info(f"轮询间隔：{self.settings.poll_interval_seconds}秒")
        logger.info(f"Mock模式：{'开启' if self.settings.use_mock_llm else '关闭'}")
        
        try:
            while True:
                self.run_one_cycle()
                time.sleep(self.settings.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("收到停止信号，系统正在退出...")
        except Exception as e:
            logger.critical(f"系统发生致命错误：{str(e)}")
            logger.critical(traceback.format_exc())
            raise


if __name__ == "__main__":
    orchestrator = AgentOrchestrator()
    orchestrator.run_forever()
