"""
主程序入口。

运行逻辑：
1. 读取配置；
2. 初始化飞书客户端与 Agent；
3. 进入 while True 轮询；
4. 每隔 10 秒扫描一次“待处理”记录；
5. 逐条处理并写回结果。

这个文件更像“调度中心”，负责串联配置、飞书 API、Agent 与日志。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agent_logic import ContentWriterAgent
from config import load_settings
from feishu_client import FeishuBitableClient, FeishuPermissionDeniedError


def setup_logging() -> None:
    """
    初始化日志格式。

    force=True 可以确保重复运行脚本时，basicConfig 仍然会生效。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def process_single_task(
    feishu_client: FeishuBitableClient,
    agent: ContentWriterAgent,
    task: dict[str, Any],
) -> None:
    """
    处理单条任务记录。

    流程拆分为独立函数后，可读性更高，也更方便未来扩展成线程池或异步处理。
    """
    logger = logging.getLogger("TaskProcessor")

    record_id = task["record_id"]
    title = task.get("title", "未命名任务")

    logger.info("开始处理记录，record_id=%s，title=%s", record_id, title)

    # 第一步：先把状态改成“处理中”，避免下一轮轮询重复拾取同一条任务。
    feishu_client.update_task_status_and_result(
        record_id=record_id,
        status=feishu_client.settings.processing_status,
        result="Agent 已接单，正在生成内容，请稍候……",
    )

    # 第二步：调用 Agent 生成内容。
    result = agent.run(task)

    # 第三步：将生成结果写回表格，并把状态改成“待审核”。
    feishu_client.update_task_status_and_result(
        record_id=record_id,
        status=feishu_client.settings.review_status,
        result=result,
    )

    logger.info("记录处理完成，record_id=%s，title=%s", record_id, title)


def main() -> None:
    """
    主循环。

    注意：
    这里使用最容易理解的 while True 轮询模型，
    非常适合比赛 Demo、课堂演示、本地 PoC。
    """
    setup_logging()
    logger = logging.getLogger("Main")

    try:
        # 启动时先读取配置，若 .env 缺失或字段不完整，会在这里直接失败并报清晰错误。
        settings = load_settings()

        # 初始化飞书 API 封装客户端与内容写作 Agent。
        feishu_client = FeishuBitableClient(settings=settings)
        agent = ContentWriterAgent(settings=settings)
    except Exception:
        logger.exception("启动失败，请检查 .env 配置、飞书应用参数以及依赖安装情况。")
        raise

    logger.info("飞书多维表格 Agent Demo 已启动。")
    logger.info(
        "当前配置：table_id=%s，轮询间隔=%s 秒，USE_MOCK_LLM=%s",
        settings.table_id,
        settings.poll_interval_seconds,
        settings.use_mock_llm,
    )

    while True:
        try:
            logger.info("开始新一轮任务轮询。")

            # 拉取所有“待处理”记录。
            pending_tasks = feishu_client.get_pending_tasks()

            if not pending_tasks:
                logger.info("本轮没有待处理任务。")

            for task in pending_tasks:
                record_id = task.get("record_id", "unknown")

                try:
                    process_single_task(
                        feishu_client=feishu_client,
                        agent=agent,
                        task=task,
                    )
                except FeishuPermissionDeniedError as permission_error:
                    logger.error(
                        "检测到飞书写权限不足，record_id=%s。程序将停止轮询，"
                        "避免对同一条记录持续重复重试。",
                        record_id,
                    )
                    logger.error("%s", permission_error)
                    return
                except Exception as task_error:
                    logger.exception("任务处理失败，record_id=%s", record_id)

                    # 如果单条任务失败，尽量把失败信息写回飞书，便于在表格中排查。
                    try:
                        feishu_client.update_task_status_and_result(
                            record_id=record_id,
                            status=settings.failed_status,
                            result=f"任务处理失败：{task_error}",
                        )
                    except FeishuPermissionDeniedError as permission_error:
                        logger.error(
                            "回写失败状态时发现飞书写权限不足，record_id=%s。"
                            "请修复权限后重新启动程序。",
                            record_id,
                        )
                        logger.error("%s", permission_error)
                        return
                    except Exception:
                        logger.exception("回写失败状态时再次出错，record_id=%s", record_id)

        except KeyboardInterrupt:
            logger.info("收到手动中断信号，程序即将退出。")
            break
        except FeishuPermissionDeniedError as permission_error:
            logger.error("检测到飞书表格访问权限不足，程序将退出。")
            logger.error("%s", permission_error)
            return
        except Exception:
            # 外层异常用于兜住整轮轮询，避免因一次网络波动导致整个进程退出。
            logger.exception("轮询主循环发生异常，本轮结束后将继续下一轮。")

        logger.info("休眠 %s 秒后进入下一轮。", settings.poll_interval_seconds)
        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
