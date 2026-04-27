"""
飞书 API 交互封装模块。

本文件负责两件核心事情：
1. 初始化飞书官方 SDK Client，并让 SDK 自动处理 tenant_access_token；
2. 提供与多维表格交互的高层方法，供主程序直接调用。

为什么单独封装？
1. 让 main.py 更聚焦业务流程，而不是 HTTP / SDK 细节；
2. 后续如果 API 版本升级，变更点会集中在这里；
3. 更方便在比赛答辩时解释“系统分层”。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import lark_oapi as lark

from config import Settings


class FeishuApiError(RuntimeError):
    """飞书 API 调用失败时抛出的基础异常。"""


class FeishuPermissionDeniedError(FeishuApiError):
    """飞书返回权限不足时抛出的异常。"""


class FeishuBitableClient:
    """
    飞书多维表格客户端封装。

    这里对外暴露简单的方法，例如：
    - 获取不同状态的任务
    - 创建/更新任务记录
    - 创建/更新内容记录
    """

    def __init__(self, settings: Settings) -> None:
        # 保存配置，后续构造请求时会重复使用。
        self.settings = settings

        # 使用标准 logging，方便与主程序的日志体系保持一致。
        self.logger = logging.getLogger(self.__class__.__name__)

        # 使用飞书官方 SDK 初始化 Client。
        # SDK 会在内部自动申请并刷新 tenant_access_token，因此这里不需要手写鉴权接口。
        self.client = (
            lark.Client.builder()
            .app_id(settings.feishu_app_id)
            .app_secret(settings.feishu_app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    def _raise_if_failed(self, response: Any, action: str) -> None:
        """
        统一校验飞书 SDK 返回结果。

        如果接口调用失败，抛出带上下文信息的异常。
        这样主程序只需要 try-except，不必在每个调用点重复拼错误消息。
        """
        if response.success():
            return

        log_id = response.get_log_id()
        code = response.code
        msg = response.msg
        
        # 兼容不同版本SDK的错误格式
        try:
            troubleshooter = response.get_troubleshooter()
        except (AttributeError, TypeError):
            # 如果获取失败，手动从error中提取
            troubleshooter = ""
            if hasattr(response, 'error'):
                error = response.error
                if isinstance(error, dict):
                    troubleshooter = error.get('troubleshooter', '')
                else:
                    troubleshooter = getattr(error, 'troubleshooter', '')

        error_message = (
            f"{action}失败，code={code}，msg={msg}，"
            f"log_id={log_id}，troubleshooter={troubleshooter}"
        )

        if code == 91403:
            raise FeishuPermissionDeniedError(
                f"{error_message}。"
                "这通常表示应用缺少当前多维表格的文档权限。"
                "请先在飞书开放平台确认应用已开通并发布多维表格读写权限，"
                "再到目标 Base 左上角「... -> 更多 -> 添加文档应用」中添加该企业自建应用，"
                "并授予“可编辑”权限。"
            )

        raise FeishuApiError(error_message)

    def _extract_text_value(self, value: Any) -> str:
        """提取字段的文本值，处理飞书多维表格不同字段类型的返回格式"""
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, dict) and "text" in value:
            return str(value["text"])
        return str(value) if value is not None else ""

    def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        根据状态获取任务表中的记录
        """
        filter_formula = f'CurrentValue.[{self.settings.task_field_status}] = "{status}"'
        page_token: Optional[str] = None
        tasks: List[Dict[str, Any]] = []

        self.logger.info(f"拉取状态为[{status}]的任务，filter={filter_formula}")

        while True:
            request_builder = (
                lark.bitable.v1.ListAppTableRecordRequest.builder()
                .app_token(self.settings.bitable_app_token)
                .table_id(self.settings.task_table_id)
                .filter(filter_formula)
                .page_size(100)
            )

            if page_token:
                request_builder = request_builder.page_token(page_token)

            request = request_builder.build()
            response = self.client.bitable.v1.app_table_record.list(request)
            self._raise_if_failed(response, action="获取任务记录")

            items = response.data.items if response.data and response.data.items else []

            for item in items:
                fields = item.fields or {}
                task = {
                    "record_id": item.record_id,
                    **fields,
                }
                tasks.append(task)

            has_more = bool(response.data and response.data.has_more)
            page_token = response.data.page_token if response.data else None

            if not has_more:
                break

        self.logger.info(f"拉取完成，共获取到 {len(tasks)} 条记录")
        return tasks

    def update_task_fields(self, record_id: str, fields: Dict[str, Any]) -> None:
        """
        更新任务表中指定记录的字段
        """
        record_body = lark.bitable.v1.AppTableRecord.builder().fields(fields).build()

        request = (
            lark.bitable.v1.UpdateAppTableRecordRequest.builder()
            .app_token(self.settings.bitable_app_token)
            .table_id(self.settings.task_table_id)
            .record_id(record_id)
            .request_body(record_body)
            .build()
        )

        response = self.client.bitable.v1.app_table_record.update(request)
        self._raise_if_failed(response, action=f"更新任务记录 {record_id}")

        self.logger.info(f"任务记录更新成功，record_id={record_id}")

    def create_content_record(self, fields: Dict[str, Any]) -> str:
        """
        在内容表中创建新记录
        返回新创建记录的record_id
        """
        record_body = lark.bitable.v1.AppTableRecord.builder().fields(fields).build()

        request = (
            lark.bitable.v1.CreateAppTableRecordRequest.builder()
            .app_token(self.settings.bitable_app_token)
            .table_id(self.settings.content_table_id)
            .request_body(record_body)
            .build()
        )

        response = self.client.bitable.v1.app_table_record.create(request)
        self._raise_if_failed(response, action="创建内容记录")

        record_id = response.data.record.record_id
        self.logger.info(f"内容记录创建成功，record_id={record_id}")
        return record_id

    def get_content_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        根据任务ID查询对应的内容记录
        """
        filter_formula = f'CurrentValue.[{self.settings.content_field_task_id}] = "{task_id}"'
        
        request = (
            lark.bitable.v1.ListAppTableRecordRequest.builder()
            .app_token(self.settings.bitable_app_token)
            .table_id(self.settings.content_table_id)
            .filter(filter_formula)
            .page_size(1)
            .build()
        )

        response = self.client.bitable.v1.app_table_record.list(request)
        self._raise_if_failed(response, action="查询内容记录")

        items = response.data.items if response.data and response.data.items else []
        if items:
            item = items[0]
            return {
                "record_id": item.record_id,
                **item.fields,
            }
        return None

    def update_content_record(self, record_id: str, fields: Dict[str, Any]) -> None:
        """
        更新内容表中指定记录的字段
        """
        record_body = lark.bitable.v1.AppTableRecord.builder().fields(fields).build()

        request = (
            lark.bitable.v1.UpdateAppTableRecordRequest.builder()
            .app_token(self.settings.bitable_app_token)
            .table_id(self.settings.content_table_id)
            .record_id(record_id)
            .request_body(record_body)
            .build()
        )

        response = self.client.bitable.v1.app_table_record.update(request)
        self._raise_if_failed(response, action=f"更新内容记录 {record_id}")

        self.logger.info(f"内容记录更新成功，record_id={record_id}")

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """获取所有任务记录，用于数据分析"""
        page_token: Optional[str] = None
        tasks: List[Dict[str, Any]] = []

        while True:
            request_builder = (
                lark.bitable.v1.ListAppTableRecordRequest.builder()
                .app_token(self.settings.bitable_app_token)
                .table_id(self.settings.task_table_id)
                .page_size(100)
            )

            if page_token:
                request_builder = request_builder.page_token(page_token)

            request = request_builder.build()
            response = self.client.bitable.v1.app_table_record.list(request)
            self._raise_if_failed(response, action="获取所有任务记录")

            items = response.data.items if response.data and response.data.items else []
            for item in items:
                tasks.append({"record_id": item.record_id, **item.fields})

            has_more = bool(response.data and response.data.has_more)
            page_token = response.data.page_token if response.data else None

            if not has_more:
                break

        return tasks

    def get_all_contents(self) -> List[Dict[str, Any]]:
        """获取所有内容记录，用于数据分析"""
        page_token: Optional[str] = None
        contents: List[Dict[str, Any]] = []

        while True:
            request_builder = (
                lark.bitable.v1.ListAppTableRecordRequest.builder()
                .app_token(self.settings.bitable_app_token)
                .table_id(self.settings.content_table_id)
                .page_size(100)
            )

            if page_token:
                request_builder = request_builder.page_token(page_token)

            request = request_builder.build()
            response = self.client.bitable.v1.app_table_record.list(request)
            self._raise_if_failed(response, action="获取所有内容记录")

            items = response.data.items if response.data and response.data.items else []
            for item in items:
                contents.append({"record_id": item.record_id, **item.fields})

            has_more = bool(response.data and response.data.has_more)
            page_token = response.data.page_token if response.data else None

            if not has_more:
                break

        return contents
