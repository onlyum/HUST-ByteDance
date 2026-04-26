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
from typing import Any

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
    - 获取待处理任务
    - 更新任务状态和结果

    调用方无需了解底层 SDK 的 Request Builder 细节。
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
        troubleshooter = response.get_troubleshooter()
        error_message = (
            f"{action}失败，code={response.code}，msg={response.msg}，"
            f"log_id={log_id}，troubleshooter={troubleshooter}"
        )

        if response.code == 91403:
            raise FeishuPermissionDeniedError(
                f"{error_message}。"
                "这通常表示应用缺少当前多维表格的文档权限。"
                "请先在飞书开放平台确认应用已开通并发布多维表格读写权限，"
                "再到目标 Base 左上角「... -> 更多 -> 添加文档应用」中添加该企业自建应用，"
                "并授予“可编辑”权限。"
            )

        raise FeishuApiError(error_message)

    def _build_pending_filter(self) -> str:
        """
        构造默认筛选条件。

        飞书多维表格的 filter 语法支持按照字段值过滤。
        这里默认只取“状态 = 待处理”的记录。
        """
        return (
            f'CurrentValue.[{self.settings.status_field_name}] = '
            f'"{self.settings.pending_status}"'
        )

    def get_pending_tasks(self, filter_formula: str | None = None) -> list[dict[str, Any]]:
        """
        拉取所有“待处理”任务。

        参数：
        - filter_formula：可选，自定义飞书 filter 语法。
          如果不传，则默认查询“状态 = 待处理”。

        返回值：
        - 一个列表，列表中的每一项都是一个任务字典，包含 record_id、fields、title 等信息。
        """
        effective_filter = filter_formula or self._build_pending_filter()
        page_token: str | None = None
        tasks: list[dict[str, Any]] = []

        self.logger.info("开始从多维表格拉取待处理任务，filter=%s", effective_filter)

        while True:
            # 使用 Builder 构造“列出记录”请求。
            request_builder = (
                lark.bitable.v1.ListAppTableRecordRequest.builder()
                .app_token(self.settings.bitable_app_token)
                .table_id(self.settings.table_id)
                .filter(effective_filter)
                .page_size(100)
            )

            # 如果上一页返回了 page_token，则继续翻页拉取。
            if page_token:
                request_builder = request_builder.page_token(page_token)

            request = request_builder.build()

            # 调用官方 SDK 的 list 接口获取记录。
            response = self.client.bitable.v1.app_table_record.list(request)
            self._raise_if_failed(response, action="列出多维表格记录")

            # 飞书返回的数据主体在 response.data 里。
            items = response.data.items if response.data and response.data.items else []

            for item in items:
                fields = item.fields or {}
                task = {
                    "record_id": item.record_id,
                    "fields": fields,
                    "title": self._extract_text_value(
                        fields.get(self.settings.title_field_name)
                    ),
                    "status": self._extract_text_value(
                        fields.get(self.settings.status_field_name)
                    ),
                    "output_result": self._extract_text_value(
                        fields.get(self.settings.output_field_name)
                    ),
                }
                tasks.append(task)

            has_more = bool(response.data and response.data.has_more)
            page_token = response.data.page_token if response.data else None

            if not has_more:
                break

        self.logger.info("待处理任务拉取完成，共获取到 %s 条记录。", len(tasks))
        return tasks

    def update_task_status_and_result(self, record_id: str, status: str, result: str) -> None:
        """
        更新指定记录的状态和输出结果。

        参数：
        - record_id：飞书多维表格记录 ID
        - status：要写入“状态”字段的值，例如“处理中”或“待审核”
        - result：要写入“输出结果”字段的文本内容
        """
        fields_to_update = {
            self.settings.status_field_name: status,
            self.settings.output_field_name: result,
        }

        # 构造记录对象，fields 中传入“字段名 -> 字段值”的映射。
        record_body = lark.bitable.v1.AppTableRecord.builder().fields(fields_to_update).build()

        # 构造“更新记录”请求。
        request = (
            lark.bitable.v1.UpdateAppTableRecordRequest.builder()
            .app_token(self.settings.bitable_app_token)
            .table_id(self.settings.table_id)
            .record_id(record_id)
            .request_body(record_body)
            .build()
        )

        response = self.client.bitable.v1.app_table_record.update(request)
        self._raise_if_failed(response, action=f"更新记录 {record_id}")

        self.logger.info(
            "记录写回成功，record_id=%s，status=%s",
            record_id,
            status,
        )

    @staticmethod
    def _extract_text_value(value: Any) -> str:
        """
        尽量把飞书返回的字段值安全地转成字符串。

        多维表格不同字段类型的返回结构可能不同：
        - 纯文本字段通常直接返回字符串；
        - 有些字段可能返回列表；
        - 也可能出现 None。
        """
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, list):
            return ", ".join(str(item) for item in value)

        return str(value)
