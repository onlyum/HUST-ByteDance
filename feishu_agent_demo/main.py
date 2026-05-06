"""
主程序入口模块（采购供应链版）。

编排模式：状态触发型
- 扫描 Demands / Orders 的状态，唤醒对应 Agent
- 所有写操作后落 Audit_Logs（由 BaseAgent 提供统一接口）
"""

import logging
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List

from agents import PlannerAgent, SourcingAuditorAgent, StrategyAgent, TrackerAgent
from config import BusinessStatus, TABLE_IDS, load_settings
from feishu_bitable_toolbox import FeishuBitableToolbox
from feishu_client_ws import FeishuWebSocketClient
from handler.bot_handler import BotHandler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """采购编排引擎：按状态触发唤醒不同 Agent。"""

    def __init__(self) -> None:
        self.settings = load_settings()
        self.bitable = FeishuBitableToolbox(
            app_id=self.settings.feishu_app_id,
            app_secret=self.settings.feishu_app_secret,
        )

        self.planner = PlannerAgent("planner-1", self.settings, self.bitable)
        self.auditor = SourcingAuditorAgent("auditor-1", self.settings, self.bitable)
        self.tracker = TrackerAgent("tracker-1", self.settings, self.bitable)
        self.strategy = StrategyAgent("strategy-1", self.settings, self.bitable)

        self.last_strategy_time = datetime.now() - timedelta(days=1)
        self.strategy_interval = timedelta(hours=12)

        app_id = self.settings.feishu_app_id
        token_hint = self.settings.bitable_app_token
        logger.info(
            "采购编排引擎初始化完成 | app_id=%s… | bitable_token=%s…%s",
            app_id[:12] if len(app_id) > 12 else app_id,
            token_hint[:4] if len(token_hint) > 4 else token_hint,
            token_hint[-4:] if len(token_hint) > 8 else "",
        )
        logger.info(
            "核心表 table_id: demands=%s… suppliers=%s… orders=%s…",
            TABLE_IDS["demands"][:12],
            TABLE_IDS["suppliers"][:12],
            TABLE_IDS["orders"][:12],
        )
        logger.info(
            "LLM: use_mock=%s | connect_timeout=%ss read_timeout=%ss",
            self.settings.use_mock_llm,
            self.settings.llm_connect_timeout_seconds,
            self.settings.llm_timeout_seconds,
        )
        logger.info(
            "审批链: multi_stage_approval=%s（true=终审→采购对接→运输→建单；false=单卡待审批一键下单）",
            self.settings.multi_stage_approval,
        )

    def _list_by_filter(self, table_id: str, *, filter_formula: str, fields: List[str] | None = None, max_pages: int = 5) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for rec in self.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=table_id,
            filter_formula=filter_formula,
            fields=fields,
            max_pages=max_pages,
        ):
            out.append(rec)
        return out

    def run_orchestrator_once(self) -> None:
        tick_start = time.perf_counter()
        logger.info("—— 编排轮询 tick 开始 ——")

        # 1) 待规划需求 -> Planner
        pending_demands = self._list_by_filter(
            TABLE_IDS["demands"],
            filter_formula=f'CurrentValue.[{self.settings.demand_field_status}] = "{BusinessStatus.DEMAND_PENDING}"',
            fields=[self.settings.demand_field_status, self.settings.demand_field_source_instruction],
        )
        pending_debate = self._list_by_filter(
            TABLE_IDS["demands"],
            filter_formula=f'CurrentValue.[{self.settings.demand_field_status}] = "{BusinessStatus.DEMAND_PENDING_DEBATE}"',
            fields=[self.settings.demand_field_status],
            max_pages=5,
        )
        auto_debate = self.settings.auto_run_audit_debate
        logger.info(
            "需求队列快照: 待规划=%s 条 | 待辩论=%s 条（自动辩论=%s，每 tick 最多处理 1 条待辩论）",
            len(pending_demands),
            len(pending_debate),
            auto_debate,
        )
        if pending_debate:
            sample = ", ".join(str(x.get("record_id", ""))[:16] for x in pending_debate[:5])
            logger.info("待辩论 record_id 样例（前5）: %s%s", sample, " …" if len(pending_debate) > 5 else "")

        planner_ok = 0
        for d in pending_demands:
            try:
                update_fields, _ = self.planner.run(d)
                if update_fields:
                    self.bitable.update_record(
                        app_token=self.settings.bitable_app_token,
                        table_id=TABLE_IDS["demands"],
                        record_id=d["record_id"],
                        fields=update_fields,
                    )
                    planner_ok += 1
                    logger.info("Planner 已处理: record_id=%s → %s", d.get("record_id"), update_fields.get(self.settings.demand_field_status))
            except Exception as exc:
                logger.error(f"Planner 执行失败: {exc}")
                logger.error(traceback.format_exc())
        if not pending_demands:
            logger.info("Planner: 无「待规划」需求，跳过")
        elif planner_ok == 0:
            logger.info("Planner: 本 tick 有待规划 %s 条但未成功写入（请查上方异常）", len(pending_demands))
        else:
            logger.info("Planner: 本 tick 成功更新 %s 条需求", planner_ok)

        # 2) 待辩论 -> 自动 run_audit_debate（与 IM「触发审批」等价；每 tick 最多 1 条，避免 LLM/飞书堆积）
        if self.settings.auto_run_audit_debate:
            debate_queue = self._list_by_filter(
                TABLE_IDS["demands"],
                filter_formula=f'CurrentValue.[{self.settings.demand_field_status}] = "{BusinessStatus.DEMAND_PENDING_DEBATE}"',
                fields=[
                    self.settings.demand_field_status,
                    self.settings.demand_field_category,
                    self.settings.demand_field_source_instruction,
                ],
                max_pages=5,
            )
            if debate_queue:
                first = debate_queue[0]
                rid = str(first.get("record_id", "") or "")
                if rid:
                    try:
                        logger.info("Auditor: 自动辩论与挂起待审批 record_id=%s", rid)
                        self.auditor.run_audit_debate(rid)
                    except Exception as exc:
                        logger.error("自动 run_audit_debate 失败: %s", exc)
                        logger.error(traceback.format_exc())
            else:
                logger.info("Auditor: 无「待辩论」需求，跳过自动辩论")

        # 3) 「已选型」自动下单已关闭：正常链路为 待规划→待辩论→run_audit_debate→待审批→卡片通过下单。
        #    若 Base 中仍有历史「已选型」记录需要自动消化，可手工改状态或临时恢复下方循环。
        #
        # selected_demands = self._list_by_filter(
        #     TABLE_IDS["demands"],
        #     filter_formula=f'CurrentValue.[{self.settings.demand_field_status}] = "{BusinessStatus.SUPPLIER_SELECTED}"',
        #     fields=[self.settings.demand_field_status, self.settings.demand_field_recommended_suppliers],
        # )
        # for d in selected_demands:
        #     ...

        # 4) 订单追踪（待发货/运输中/异常）-> Tracker
        active_orders = self._list_by_filter(
            TABLE_IDS["orders"],
            filter_formula=(
                f'OR('
                f'CurrentValue.[{self.settings.order_field_logistics_status}] = "待发货",'
                f'CurrentValue.[{self.settings.order_field_logistics_status}] = "运输中",'
                f'CurrentValue.[{self.settings.order_field_logistics_status}] = "异常"'
                f')'
            ),
            fields=[
                self.settings.order_field_logistics_status,
                self.settings.order_field_demand,
                "exception_reason",
            ],
        )
        logger.info("物流追踪: 待处理订单（待发货/运输中/异常）=%s 条", len(active_orders))
        tracker_ok = 0
        for o in active_orders:
            try:
                update_fields, next_state = self.tracker.run(o)
                if update_fields:
                    self.bitable.update_record(
                        app_token=self.settings.bitable_app_token,
                        table_id=TABLE_IDS["orders"],
                        record_id=o["record_id"],
                        fields=update_fields,
                    )
                    tracker_ok += 1
                    logger.info(
                        "Tracker 已更新: order_id=%s logistics→%s",
                        o.get("record_id"),
                        update_fields.get(self.settings.order_field_logistics_status),
                    )
            except Exception as exc:
                logger.error(f"Tracker 执行失败: {exc}")
                logger.error(traceback.format_exc())
        if active_orders and tracker_ok == 0:
            logger.info("Tracker: 本 tick 无订单字段被写入")
        elif tracker_ok:
            logger.info("Tracker: 本 tick 成功更新 %s 条订单", tracker_ok)

        # 5) 策略看板（定期）
        now = datetime.now()
        if now - self.last_strategy_time >= self.strategy_interval:
            try:
                all_demands = list(self.bitable.iter_records(app_token=self.settings.bitable_app_token, table_id=TABLE_IDS["demands"], max_pages=10))
                all_orders = list(self.bitable.iter_records(app_token=self.settings.bitable_app_token, table_id=TABLE_IDS["orders"], max_pages=10))
                _ = self.strategy.run(demands=all_demands, orders=all_orders)
                self.last_strategy_time = now
                logger.info(
                    "Strategy: 已生成 KPI 看板（demands=%s orders=%s），下次不早于 12h 后",
                    len(all_demands),
                    len(all_orders),
                )
            except Exception as exc:
                logger.error(f"Strategy 执行失败: {exc}")
                logger.error(traceback.format_exc())
        else:
            remain = self.strategy_interval - (now - self.last_strategy_time)
            logger.info("Strategy: 本 tick 跳过，距下次执行约 %s", str(remain).split(".")[0])

        elapsed = time.perf_counter() - tick_start
        logger.info("—— 编排轮询 tick 结束，耗时 %.2fs ——", elapsed)

    def run_forever(self) -> None:
        logger.info("采购多Agent系统启动成功")
        logger.info(f"轮询间隔：{self.settings.poll_interval_seconds}秒")
        try:
            while True:
                try:
                    self.run_orchestrator_once()
                except Exception as exc:
                    # 轮询链路出现网络/代理抖动时不中断主进程，避免连带 WS 监听退出。
                    logger.error(f"编排轮询失败，将在下一轮重试: {exc}")
                    logger.error(traceback.format_exc())
                time.sleep(self.settings.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("收到停止信号，系统正在退出...")


if __name__ == "__main__":
    logger.info("进程启动: 初始化编排器与飞书 WS…")
    orchestrator = AgentOrchestrator()
    bot_handler = BotHandler(orchestrator.bitable)
    ws_client = FeishuWebSocketClient(orchestrator.settings, bot_handler)

    ws_thread = threading.Thread(target=ws_client.start, name="feishu-ws-listener", daemon=True)
    ws_thread.start()
    logger.info("飞书 WS 线程已启动 (daemon=True)，主线程将进入编排循环")

    orchestrator.run_forever()
