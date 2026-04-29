"""
主程序入口模块（采购供应链版）。

编排模式：状态触发型
- 扫描 Demands / Orders 的状态，唤醒对应 Agent
- 所有写操作后落 Audit_Logs（由 BaseAgent 提供统一接口）
"""

import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List

from agents import PlannerAgent, SourcingAuditorAgent, StrategyAgent, TrackerAgent
from config import BusinessStatus, TABLE_IDS, load_settings
from feishu_bitable_toolbox import FeishuBitableToolbox

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

        logger.info("采购编排引擎初始化完成")

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
        # 1) 待规划需求 -> Planner
        pending_demands = self._list_by_filter(
            TABLE_IDS["demands"],
            filter_formula=f'CurrentValue.[{self.settings.demand_field_status}] = "{BusinessStatus.DEMAND_PENDING}"',
            fields=[self.settings.demand_field_status, self.settings.demand_field_source_instruction],
        )
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
            except Exception as exc:
                logger.error(f"Planner 执行失败: {exc}")
                logger.error(traceback.format_exc())

        # 2) 已选型需求 -> Auditor（审查供应商并下单）
        selected_demands = self._list_by_filter(
            TABLE_IDS["demands"],
            filter_formula=f'CurrentValue.[{self.settings.demand_field_status}] = "{BusinessStatus.SUPPLIER_SELECTED}"',
            fields=[self.settings.demand_field_status, self.settings.demand_field_recommended_suppliers],
        )
        for d in selected_demands:
            try:
                update_fields, _ = self.auditor.run(d)
                if update_fields:
                    self.bitable.update_record(
                        app_token=self.settings.bitable_app_token,
                        table_id=TABLE_IDS["demands"],
                        record_id=d["record_id"],
                        fields=update_fields,
                    )
            except Exception as exc:
                logger.error(f"Auditor 执行失败: {exc}")
                logger.error(traceback.format_exc())

        # 3) 订单追踪（待发货/运输中/异常）-> Tracker
        active_orders = self._list_by_filter(
            TABLE_IDS["orders"],
            filter_formula=(
                f'OR('
                f'CurrentValue.[{self.settings.order_field_logistics_status}] = "待发货",'
                f'CurrentValue.[{self.settings.order_field_logistics_status}] = "运输中",'
                f'CurrentValue.[{self.settings.order_field_logistics_status}] = "异常"'
                f')'
            ),
            fields=[self.settings.order_field_logistics_status, self.settings.order_field_demand],
        )
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
            except Exception as exc:
                logger.error(f"Tracker 执行失败: {exc}")
                logger.error(traceback.format_exc())

        # 4) 策略看板（定期）
        now = datetime.now()
        if now - self.last_strategy_time >= self.strategy_interval:
            try:
                all_demands = list(self.bitable.iter_records(app_token=self.settings.bitable_app_token, table_id=TABLE_IDS["demands"], max_pages=10))
                all_orders = list(self.bitable.iter_records(app_token=self.settings.bitable_app_token, table_id=TABLE_IDS["orders"], max_pages=10))
                _ = self.strategy.run(demands=all_demands, orders=all_orders)
                self.last_strategy_time = now
            except Exception as exc:
                logger.error(f"Strategy 执行失败: {exc}")
                logger.error(traceback.format_exc())

    def run_forever(self) -> None:
        logger.info("采购多Agent系统启动成功")
        logger.info(f"轮询间隔：{self.settings.poll_interval_seconds}秒")
        try:
            while True:
                self.run_orchestrator_once()
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
