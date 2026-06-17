"""
grid/shortterm.py - 7天短线策略引擎（完全独立实现）

独立数据文件: data/shortterm_positions.json
不依赖 positions.py，完全隔离于低频网格策略

策略特点：
- 持仓周期1-7天
- 止损：-10%（可调），最大-15%
- 目标止盈：5%
- 分批止盈：15%减1/3，20%再减1/3
- 回撤止盈：峰值回撤5%清仓
- 止损冷却期：14天
"""
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any

# ============================================================
# 独立数据文件路径
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data"
SHORTTERM_FILE = DATA_DIR / "shortterm_positions.json"
HISTORY_FILE = DATA_DIR / "shortterm_history.json"

_lock = threading.Lock()

# ============================================================
# 默认配置
# ============================================================

DEFAULT_CONFIG = {
    # 止损
    "stop_loss_pct": -10.0,
    "stop_loss_max_pct": -15.0,
    # 止盈
    "take_profit_target": 10.0,
    "take_profit_tier1": 15.0,
    "take_profit_tier2": 20.0,
    # 回撤止盈
    "trail_stop_pct": 5.0,
    "trail_activate_profit": 10.0,
    # 买入
    "first_build_ratio": 0.30,
    "supplement_ratio": 0.20,
    "max_supplement_count": 1,
    # 冷却
    "cooldown_days": 14,
    # 买入信号阈值
    "dip_buy_threshold": -2.0,
    "bounce_buy_threshold": 0.5,
}


# ============================================================
# 独立数据读写（不调用 positions.py）
# ============================================================

def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _empty_data() -> dict:
    return {
        "funds": {},
        "cooldowns": {},
        "config": DEFAULT_CONFIG.copy(),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _load_data() -> dict:
    """加载短线策略数据（独立文件）"""
    _ensure_data_dir()
    if not SHORTTERM_FILE.exists():
        return _empty_data()
    try:
        with open(SHORTTERM_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_data()
        # 确保必要字段
        if "funds" not in data:
            data["funds"] = {}
        if "cooldowns" not in data:
            data["cooldowns"] = {}
        if "config" not in data:
            data["config"] = DEFAULT_CONFIG.copy()
        return data
    except Exception as e:
        print(f"[ShortTerm] 加载数据失败: {e}")
        return _empty_data()


def _save_data(data: dict):
    """保存短线策略数据（独立文件）"""
    _ensure_data_dir()
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        try:
            tmp = SHORTTERM_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(SHORTTERM_FILE)
        except Exception as e:
            print(f"[ShortTerm] 保存数据失败: {e}")


# ============================================================
# 配置管理
# ============================================================

def get_config() -> dict:
    """获取当前配置"""
    data = _load_data()
    return data.get("config", DEFAULT_CONFIG.copy())


def update_config(updates: dict) -> dict:
    """更新配置"""
    data = _load_data()
    config = data.get("config", DEFAULT_CONFIG.copy())
    # 只更新有效字段
    valid_keys = set(DEFAULT_CONFIG.keys())
    for k, v in updates.items():
        if k in valid_keys:
            config[k] = v
    data["config"] = config
    _save_data(data)
    return config


def reset_config() -> dict:
    """重置为默认配置"""
    data = _load_data()
    data["config"] = DEFAULT_CONFIG.copy()
    _save_data(data)
    return DEFAULT_CONFIG.copy()


# ============================================================
# 持仓管理（独立实现）
# ============================================================

def get_all_positions() -> dict:
    """获取所有短线持仓"""
    return _load_data()


def get_position(fund_code: str) -> dict:
    """获取单只基金的短线持仓"""
    data = _load_data()
    fund = data.get("funds", {}).get(fund_code, {})

    if not fund:
        return {
            "fund_code": fund_code,
            "has_position": False,
            "batches": [],
            "max_position": 5000,
        }

    batches = [b for b in fund.get("batches", []) if b.get("status") == "holding"]
    total_amount = sum(b.get("amount", 0) for b in batches)
    total_shares = sum(b.get("shares", 0) for b in batches)

    return {
        "fund_code": fund_code,
        "has_position": len(batches) > 0,
        "batches": batches,
        "total_amount": total_amount,
        "total_shares": total_shares,
        "max_position": fund.get("max_position", 5000),
        "fund_name": fund.get("fund_name", ""),
        "supplement_count": fund.get("supplement_count", 0),
        "peak_profit": fund.get("peak_profit"),
    }


def add_position(fund_code: str, amount: float, nav: float = None,
                 note: str = "", buy_date: str = None,
                 max_position: float = 5000, fund_name: str = "") -> dict:
    """
    添加短线买入记录

    Args:
        fund_code: 基金代码
        amount: 买入金额
        nav: 确认净值（可后补）
        note: 备注
        buy_date: 买入日期（默认今天）
        max_position: 仓位上限
        fund_name: 基金名称

    Returns:
        新增的批次信息
    """
    if amount <= 0:
        raise ValueError("金额必须大于0")

    data = _load_data()
    funds = data.setdefault("funds", {})

    if fund_code not in funds:
        funds[fund_code] = {
            "fund_name": fund_name,
            "max_position": max_position,
            "batches": [],
            "supplement_count": 0,
        }

    fund = funds[fund_code]

    # 更新基金名称
    if fund_name and not fund.get("fund_name"):
        fund["fund_name"] = fund_name

    # 买入日期
    if buy_date:
        try:
            datetime.strptime(buy_date, "%Y-%m-%d")
            date_str = buy_date
        except ValueError:
            date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 生成批次ID
    date_part = date_str.replace("-", "")
    existing = [b["id"] for b in fund.get("batches", []) if b["id"].startswith(f"b{date_part}")]
    idx = len(existing)
    letter = chr(ord("a") + min(idx, 25))
    batch_id = f"b{date_part}{letter}"

    # 净值和份额
    _nav = nav if nav and nav > 0 else 0.0
    shares = round(amount / _nav, 2) if _nav > 0 else 0.0

    batch = {
        "id": batch_id,
        "buy_date": date_str,
        "amount": round(amount, 2),
        "nav": round(_nav, 4),
        "shares": shares,
        "status": "holding",
        "note": note,
    }

    fund["batches"].append(batch)
    _save_data(data)

    print(f"[ShortTerm] 买入 {fund_code} {batch_id}: {amount}元 @ {_nav or '待确认'}")

    return batch


def sell_position(fund_code: str, batch_id: str, sell_shares: float,
                  sell_nav: float = None, sell_date: str = None) -> dict:
    """
    卖出短线持仓

    Args:
        fund_code: 基金代码
        batch_id: 批次ID
        sell_shares: 卖出份额
        sell_nav: 卖出净值
        sell_date: 卖出日期

    Returns:
        卖出结果
    """
    data = _load_data()
    fund = data.get("funds", {}).get(fund_code)

    if not fund:
        raise ValueError(f"基金 {fund_code} 不存在")

    batch = None
    for b in fund.get("batches", []):
        if b["id"] == batch_id:
            batch = b
            break

    if not batch:
        raise ValueError(f"批次 {batch_id} 不存在")

    if batch.get("status") != "holding":
        raise ValueError(f"批次 {batch_id} 已卖出")

    if sell_shares <= 0:
        raise ValueError("卖出份额必须大于0")

    if sell_shares > batch.get("shares", 0) + 0.01:
        raise ValueError(f"卖出份额超过持有份额")

    # 卖出日期
    if sell_date:
        try:
            sd = datetime.strptime(sell_date, "%Y-%m-%d").date()
        except ValueError:
            sd = datetime.now().date()
    else:
        sd = datetime.now().date()

    buy_date = datetime.strptime(batch["buy_date"], "%Y-%m-%d").date()
    hold_days = (sd - buy_date).days

    # 计算收益
    cost = batch["amount"] * (sell_shares / batch["shares"]) if batch["shares"] > 0 else 0

    if sell_nav and sell_nav > 0:
        gross = sell_shares * sell_nav
        profit = round(gross - cost, 2)
        profit_pct = round(profit / cost * 100, 1) if cost > 0 else 0
    else:
        gross = None
        profit = None
        profit_pct = None

    # 判断是否全部卖出
    is_full = abs(sell_shares - batch.get("shares", 0)) < 0.01

    if is_full:
        batch["status"] = "sold"
        batch["sell_date"] = sd.strftime("%Y-%m-%d")
        batch["sell_nav"] = round(sell_nav, 4) if sell_nav else None
        batch["sell_shares"] = round(sell_shares, 2)
        batch["profit"] = profit
        batch["profit_pct"] = profit_pct
    else:
        # 部分卖出
        if "original_amount" not in batch:
            batch["original_amount"] = batch["amount"]
            batch["original_shares"] = batch["shares"]
        ratio = sell_shares / batch["shares"]
        batch["shares"] = round(batch["shares"] - sell_shares, 2)
        batch["amount"] = round(batch["amount"] * (1 - ratio), 2)

    # 检查是否止损卖出
    if profit_pct is not None and profit_pct <= -10:
        # 设置冷却期
        config = data.get("config", DEFAULT_CONFIG)
        cooldown_days = config.get("cooldown_days", 14)
        cooldowns = data.setdefault("cooldowns", {})
        cooldowns[fund_code] = {
            "until": (sd + timedelta(days=cooldown_days)).strftime("%Y-%m-%d"),
            "start": sd.strftime("%Y-%m-%d"),
            "reason": f"止损{profit_pct:.1f}%"
        }
        print(f"[ShortTerm] {fund_code} 止损冷却期设置 {cooldown_days} 天")

    # 清空持仓后重置
    remaining = [b for b in fund.get("batches", []) if b.get("status") == "holding"]
    if not remaining:
        fund["supplement_count"] = 0
        fund.pop("peak_profit", None)
        fund.pop("peak_nav", None)

    _save_data(data)

    print(f"[ShortTerm] 卖出 {fund_code} {batch_id}: {sell_shares}份 @ {sell_nav or '待确认'}")

    return {
        "batch_id": batch_id,
        "sell_shares": round(sell_shares, 2),
        "hold_days": hold_days,
        "profit": profit,
        "profit_pct": profit_pct,
        "is_full": is_full,
        "nav_pending": sell_nav is None,
    }


def remove_position(fund_code: str) -> bool:
    """移除基金的所有短线持仓"""
    data = _load_data()
    funds = data.get("funds", {})

    if fund_code not in funds:
        return False

    del funds[fund_code]
    data.get("cooldowns", {}).pop(fund_code, None)
    _save_data(data)

    print(f"[ShortTerm] 移除 {fund_code}")
    return True


def update_position_nav(fund_code: str, batch_id: str, nav: float) -> dict:
    """补录买入净值"""
    if not nav or nav <= 0:
        raise ValueError("净值必须大于0")

    data = _load_data()
    fund = data.get("funds", {}).get(fund_code)

    if not fund:
        raise ValueError(f"基金 {fund_code} 不存在")

    for b in fund.get("batches", []):
        if b["id"] == batch_id:
            b["nav"] = round(nav, 4)
            b["shares"] = round(b["amount"] / nav, 2)
            _save_data(data)
            print(f"[ShortTerm] 补录净值 {fund_code} {batch_id}: {nav}")
            return b

    raise ValueError(f"批次 {batch_id} 不存在")


# ============================================================
# 冷却期管理
# ============================================================

def is_in_cooldown(fund_code: str) -> tuple:
    """检查是否在冷却期"""
    data = _load_data()
    cooldown = data.get("cooldowns", {}).get(fund_code)

    if not cooldown:
        return False, 0, ""

    try:
        until = datetime.strptime(cooldown["until"], "%Y-%m-%d").date()
        today = datetime.now().date()
        if today < until:
            remaining = (until - today).days
            return True, remaining, cooldown.get("reason", "冷却期中")
    except:
        pass

    return False, 0, ""


def clear_cooldown(fund_code: str):
    """清除冷却期"""
    data = _load_data()
    data.get("cooldowns", {}).pop(fund_code, None)
    _save_data(data)


# ============================================================
# 信号生成（独立实现）
# ============================================================

def _analyze_trend(today_change: float, hist_changes: list) -> dict:
    """分析趋势"""
    all_changes = [today_change] + (hist_changes or [])

    # 连续下跌
    consecutive_down = 0
    for c in all_changes:
        if c < 0:
            consecutive_down += 1
        else:
            break

    # 短期累计
    def _compound(changes):
        product = 1.0
        for c in changes:
            product *= (1 + c / 100)
        return round((product - 1) * 100, 2)

    short_3d = _compound(all_changes[:3]) if len(all_changes) >= 3 else None
    short_5d = _compound(all_changes[:5]) if len(all_changes) >= 5 else None

    # 趋势标签
    if consecutive_down >= 3:
        trend = "连跌"
    elif short_3d and short_3d < -3:
        trend = "偏弱"
    elif short_3d and short_3d > 3:
        trend = "偏强"
    else:
        trend = "震荡"

    return {
        "consecutive_down": consecutive_down,
        "short_3d": short_3d,
        "short_5d": short_5d,
        "trend": trend,
    }


def _estimate_nav(batch_nav: float, today_change: float, nav_history: list) -> float:
    """估算当前净值"""
    from valuation.core import _is_market_closed

    today_str = datetime.now().strftime("%Y-%m-%d")

    if _is_market_closed() and nav_history:
        latest = nav_history[0]
        if latest.get("date") == today_str and latest.get("nav"):
            return latest["nav"]
        if latest.get("nav"):
            return latest["nav"]

    if nav_history and nav_history[0].get("nav"):
        return nav_history[0]["nav"] * (1 + today_change / 100)

    return batch_nav * (1 + today_change / 100) if batch_nav else 0


def generate_signal(fund_code: str) -> dict:
    """
    生成单只基金的短线策略信号

    Returns:
        {
            "fund_code": str,
            "signal_name": str,
            "action": "buy" | "sell" | "hold",
            "priority": int,
            "reason": str,
            "amount": float,       # 买入金额
            "sell_pct": int,        # 卖出比例
            "sell_shares": float,   # 卖出份额
            "target_batch_id": str, # 目标批次
            "profit_pct": float,    # 当前盈亏
            "market_analysis": dict,
            "config": dict,
        }
    """
    config = get_config()

    # 获取估值数据（从 valuation 模块，这是共享的只读数据）
    from valuation.core import calculate_valuation
    from valuation.providers import get_fund_nav_history, get_fund_name

    val = calculate_valuation(fund_code)
    today_change = val.get("estimation_change") or 0.0
    source = val.get("_source", "estimation")
    confidence = val.get("calibrated_confidence", val.get("confidence", 0.5))

    nav_history = get_fund_nav_history(fund_code, 30)
    hist_changes = [h["change"] for h in nav_history if h.get("change") is not None]

    trend_ctx = _analyze_trend(today_change, hist_changes)
    fund_name = get_fund_name(fund_code) or val.get("fund_name", "")

    market_analysis = {
        "today_change": round(today_change, 2),
        "source": source,
        "confidence": round(confidence, 2),
        "trend": trend_ctx["trend"],
        "consecutive_down": trend_ctx["consecutive_down"],
        "short_3d": trend_ctx["short_3d"],
        "short_5d": trend_ctx["short_5d"],
    }

    # 获取持仓
    pos = get_position(fund_code)
    batches = pos.get("batches", [])
    batches_sorted = sorted(batches, key=lambda b: b.get("buy_date", ""))

    # ===== 有持仓：检查卖出信号 =====
    if batches_sorted:
        # 估算当前净值
        current_nav = _estimate_nav(
            batches_sorted[0].get("nav", 1.0),
            today_change,
            nav_history
        )

        # 计算总盈亏
        total_shares = sum(b.get("shares", 0) for b in batches_sorted)
        total_cost = sum(b.get("amount", 0) for b in batches_sorted)
        total_profit_pct = round((total_shares * current_nav / total_cost - 1) * 100, 2) if total_cost > 0 else 0

        market_analysis["current_nav"] = round(current_nav, 4)
        market_analysis["total_profit_pct"] = total_profit_pct

        # 检查冷却期
        in_cd, remaining, cd_reason = is_in_cooldown(fund_code)
        if in_cd:
            return {
                "fund_code": fund_code,
                "fund_name": fund_name,
                "signal_name": "冷却期中",
                "action": "hold",
                "priority": 8,
                "reason": f"{cd_reason}，还需等待{remaining}天",
                "market_analysis": market_analysis,
                "config": config,
            }

        # 遍历批次检查卖出信号
        best_signal = None

        for batch in batches_sorted:
            batch_nav = batch.get("nav", 0)
            if batch_nav <= 0:
                continue

            profit_pct = round((current_nav / batch_nav - 1) * 100, 2)
            peak_profit = batch.get("peak_profit", profit_pct)

            # 更新峰值
            data = _load_data()
            fund_data = data.get("funds", {}).get(fund_code, {})
            if profit_pct > peak_profit:
                batch["peak_profit"] = profit_pct
                batch["peak_nav"] = current_nav
                fund_data["peak_profit"] = profit_pct
                fund_data["peak_nav"] = current_nav
                _save_data(data)
                peak_profit = profit_pct

            shares = batch.get("shares", 0)

            # 1. 强制止损
            if profit_pct <= config["stop_loss_max_pct"]:
                signal = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "signal_name": "强制止损",
                    "action": "sell",
                    "priority": 1,
                    "target_batch_id": batch["id"],
                    "sell_pct": 100,
                    "sell_shares": shares,
                    "profit_pct": profit_pct,
                    "reason": f"浮亏{profit_pct:.1f}%触及最大止损线{config['stop_loss_max_pct']}%",
                    "market_analysis": market_analysis,
                    "config": config,
                    "is_stop_loss": True,
                }
                if not best_signal or signal["priority"] < best_signal.get("priority", 8):
                    best_signal = signal
                continue

            # 2. 常规止损
            if profit_pct <= config["stop_loss_pct"]:
                signal = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "signal_name": "止损卖出",
                    "action": "sell",
                    "priority": 1,
                    "target_batch_id": batch["id"],
                    "sell_pct": 100,
                    "sell_shares": shares,
                    "profit_pct": profit_pct,
                    "reason": f"浮亏{profit_pct:.1f}%触发止损线{config['stop_loss_pct']}%",
                    "market_analysis": market_analysis,
                    "config": config,
                    "is_stop_loss": True,
                }
                if not best_signal or signal["priority"] < best_signal.get("priority", 8):
                    best_signal = signal
                continue

            # 3. 目标止盈
            if profit_pct >= config["take_profit_target"]:
                signal = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "signal_name": "目标止盈",
                    "action": "sell",
                    "priority": 2,
                    "target_batch_id": batch["id"],
                    "sell_pct": 100,
                    "sell_shares": shares,
                    "profit_pct": profit_pct,
                    "reason": f"浮盈{profit_pct:.1f}%达成目标{config['take_profit_target']}%，落袋为安",
                    "market_analysis": market_analysis,
                    "config": config,
                }
                if not best_signal or signal["priority"] < best_signal.get("priority", 8):
                    best_signal = signal
                continue

            # 4. 分批止盈档位2
            if profit_pct >= config["take_profit_tier2"]:
                sell_shares = round(shares * 0.33, 2)
                signal = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "signal_name": "分批止盈(20%)",
                    "action": "sell",
                    "priority": 3,
                    "target_batch_id": batch["id"],
                    "sell_pct": 33,
                    "sell_shares": sell_shares,
                    "profit_pct": profit_pct,
                    "reason": f"浮盈{profit_pct:.1f}%≥20%，减仓1/3锁定收益",
                    "market_analysis": market_analysis,
                    "config": config,
                }
                if not best_signal or signal["priority"] < best_signal.get("priority", 8):
                    best_signal = signal
                continue

            # 5. 分批止盈档位1
            if profit_pct >= config["take_profit_tier1"]:
                sell_shares = round(shares * 0.33, 2)
                signal = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "signal_name": "分批止盈(15%)",
                    "action": "sell",
                    "priority": 3,
                    "target_batch_id": batch["id"],
                    "sell_pct": 33,
                    "sell_shares": sell_shares,
                    "profit_pct": profit_pct,
                    "reason": f"浮盈{profit_pct:.1f}%≥15%，减仓1/3",
                    "market_analysis": market_analysis,
                    "config": config,
                }
                if not best_signal or signal["priority"] < best_signal.get("priority", 8):
                    best_signal = signal
                continue

            # 6. 回撤止盈
            if profit_pct >= config["trail_activate_profit"]:
                drawdown = peak_profit - profit_pct
                if drawdown >= config["trail_stop_pct"]:
                    signal = {
                        "fund_code": fund_code,
                        "fund_name": fund_name,
                        "signal_name": "回撤止盈",
                        "action": "sell",
                        "priority": 2,
                        "target_batch_id": batch["id"],
                        "sell_pct": 100,
                        "sell_shares": shares,
                        "profit_pct": profit_pct,
                        "reason": f"峰值{peak_profit:.1f}%回撤{drawdown:.1f}%，清仓锁定收益",
                        "market_analysis": market_analysis,
                        "config": config,
                    }
                    if not best_signal or signal["priority"] < best_signal.get("priority", 8):
                        best_signal = signal
                    continue

        if best_signal:
            return best_signal

        # 持有
        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "signal_name": "持有观察",
            "action": "hold",
            "priority": 8,
            "reason": f"浮盈{total_profit_pct:.1f}%，未触发卖出条件",
            "profit_pct": total_profit_pct,
            "market_analysis": market_analysis,
            "config": config,
        }

    # ===== 空仓：检查买入信号 =====
    market_analysis["has_position"] = False

    # 检查冷却期
    in_cd, remaining, cd_reason = is_in_cooldown(fund_code)
    if in_cd:
        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "signal_name": "冷却期中",
            "action": "hold",
            "priority": 8,
            "reason": f"{cd_reason}，还需等待{remaining}天",
            "market_analysis": market_analysis,
            "config": config,
        }

    # 置信度检查
    if source == "estimation" and confidence < 0.5:
        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "signal_name": "置信度不足",
            "action": "hold",
            "priority": 8,
            "reason": f"估值置信度{confidence:.0%}偏低",
            "market_analysis": market_analysis,
            "config": config,
        }

    max_position = pos.get("max_position", 5000)

    # 1. 回调买入
    if today_change <= config["dip_buy_threshold"]:
        amount = round(max_position * config["first_build_ratio"], 2)
        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "signal_name": "回调买入",
            "action": "buy",
            "priority": 6,
            "amount": amount,
            "reason": f"今日跌{today_change:.2f}%，回调买入机会，建议{amount:.0f}元（30%仓位）",
            "market_analysis": market_analysis,
            "config": config,
        }

    # 2. 反弹买入
    if (trend_ctx["consecutive_down"] >= 2 and
        today_change > config["bounce_buy_threshold"]):
        amount = round(max_position * config["first_build_ratio"], 2)
        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "signal_name": "反弹买入",
            "action": "buy",
            "priority": 6,
            "amount": amount,
            "reason": f"连跌{trend_ctx['consecutive_down']}天后反弹{today_change:.2f}%，趋势反转信号",
            "market_analysis": market_analysis,
            "config": config,
        }

    # 观望
    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "signal_name": "观望等待",
        "action": "hold",
        "priority": 8,
        "reason": f"今日{today_change:.2f}%，趋势{trend_ctx['trend']}，等待买入时机",
        "market_analysis": market_analysis,
        "config": config,
    }


def generate_all_signals() -> dict:
    """生成所有基金的短线信号"""
    data = _load_data()
    fund_codes = list(data.get("funds", {}).keys())

    signals = []
    for code in fund_codes:
        try:
            sig = generate_signal(code)
            signals.append(sig)
        except Exception as e:
            print(f"[ShortTerm] 生成 {code} 信号失败: {e}")
            signals.append({
                "fund_code": code,
                "signal_name": "信号生成失败",
                "action": "hold",
                "priority": 8,
                "reason": str(e),
            })

    # 按优先级排序
    signals.sort(key=lambda s: (s.get("priority", 8), s.get("profit_pct", 0) or 0))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": "shortterm",
        "signals": signals,
        "config": get_config(),
    }


# ============================================================
# 信号历史
# ============================================================

def append_history(fund_code: str, signal: dict):
    """追加信号历史"""
    _ensure_data_dir()

    with _lock:
        try:
            history = {}
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
        except:
            history = {}

    records = history.setdefault(fund_code, [])
    records.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "signal_name": signal.get("signal_name"),
        "action": signal.get("action"),
        "profit_pct": signal.get("profit_pct"),
        "sell_pct": signal.get("sell_pct"),
        "reason": signal.get("reason"),
    })

    # 保留90条
    if len(records) > 90:
        records[:] = records[-90:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_history(fund_code: str = None, limit: int = 30) -> dict:
    """获取信号历史"""
    _ensure_data_dir()

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except:
        return {}

    if fund_code:
        return {fund_code: history.get(fund_code, [])[-limit:]}

    return {k: v[-limit:] for k, v in history.items()}
