"""
services/recommendation.py - 推荐服务

职责：
- 筛选空仓/轻仓基金
- 生成并过滤买入信号
- 按板块分组，返回每组最优推荐
"""
from typing import List, Optional, Dict
from datetime import datetime

from valuation.core import load_state
from valuation.providers import get_fund_name
from positions import get_all_positions, parse_fund_key
from grid import generate_all_signals
from grid.engine import _is_short_term_downtrend


# 信号类型优先级映射
SIGNAL_PRIORITY = {
    "大跌抄底": 1,
    "低位建仓": 2,
    "反弹建仓": 3,
    "温和回调建仓": 4,
    "跌势放缓建仓": 5,
    "连跌低吸": 6,
    "冷却期后建仓": 7,
    "冷却期后加仓": 7,
}


class RecommendationFilter:
    """推荐筛选参数"""
    def __init__(
        self,
        sector_filter: Optional[List[str]] = None,
        signal_filter: Optional[List[str]] = None,
        min_confidence: Optional[float] = None,
        position_mode: str = "empty_light",
    ):
        self.sector_filter = sector_filter
        self.signal_filter = signal_filter
        self.min_confidence = min_confidence
        self.position_mode = position_mode


def get_sector_fund_codes(sector_filter: Optional[List[str]] = None) -> tuple:
    """
    获取板块基金代码集合

    Args:
        sector_filter: 板块名称列表，为 None 时返回所有板块

    Returns:
        (fund_codes, sector_map) - 基金代码集合, 代码->板块名称映射
    """
    state = load_state()
    fund_codes = set()
    sector_map = {}

    for sector in state.get('sectors', []):
        sector_name = sector.get('name', '')
        if sector_filter and sector_name not in sector_filter:
            continue
        for fund in sector.get('funds', []):
            code = fund.get('code', '')
            if code:
                fund_codes.add(code)
                sector_map[code] = sector_name

    return fund_codes, sector_map


def filter_by_position(
    fund_codes: set,
    position_mode: str = "empty_light"
) -> set:
    """
    按仓位过滤基金

    Args:
        fund_codes: 待过滤的基金代码集合
        position_mode: "empty" | "empty_light" | "all"

    Returns:
        符合条件的基金代码集合
    """
    if position_mode == "all":
        return fund_codes

    pos_data = get_all_positions()
    funds_data = pos_data.get('funds', {})
    result = set()

    for code in fund_codes:
        fund = funds_data.get(code, {})
        holding = [b for b in fund.get('batches', []) if b.get('status') == 'holding']
        total_cost = sum(b.get('amount', 0) for b in holding)
        max_pos = fund.get('max_position', 5000)
        position_ratio = total_cost / max_pos if max_pos > 0 else 0

        if position_mode == "empty" and position_ratio == 0:
            result.add(code)
        elif position_mode == "empty_light" and position_ratio < 0.3:
            result.add(code)

    return result


def select_best_per_sector(
    recommendations: List[dict],
    sector_map: dict
) -> List[dict]:
    """
    按板块分组，每组只保留最优推荐

    Args:
        recommendations: 推荐列表（需预先排序）
        sector_map: 基金代码 -> 板块名称映射

    Returns:
        每个板块的最优推荐列表
    """
    # 按板块分组
    sector_groups: Dict[str, List[dict]] = {}
    for rec in recommendations:
        real_code, _ = parse_fund_key(rec.get('fund_code', ''))
        sector = sector_map.get(real_code, "未分组")
        sector_groups.setdefault(sector, []).append(rec)

    # 每组选择最优（已按优先级排序，取第一个）
    best_recommendations = []
    for sector, recs in sector_groups.items():
        if recs:
            best = recs[0]  # 已经排序过，第一个就是最优
            best_recommendations.append(best)

    # 再次排序输出
    best_recommendations.sort(key=lambda r: (
        SIGNAL_PRIORITY.get(r.get('signal_name', ''), 99),
        r.get('priority', 99),
        r.get('sub_priority', 0)
    ))

    return best_recommendations


def get_recommendations(filters: RecommendationFilter) -> dict:
    """
    获取可购买推荐列表

    每个板块只返回最优推荐基金。

    Args:
        filters: RecommendationFilter 实例，包含筛选条件

    Returns:
        {
            recommendations: List[dict],  # 每个板块最优推荐
            total: int,
            generated_at: str,
            filters: dict
        }
    """
    # 1. 获取板块基金
    sector_fund_codes, sector_map = get_sector_fund_codes(filters.sector_filter)

    # 2. 按仓位过滤
    eligible_codes = filter_by_position(sector_fund_codes, filters.position_mode)

    # 3. 生成信号（include_state_funds=True 确保包含板块基金）
    all_signals = generate_all_signals(include_state_funds=True).get('signals', [])

    # 4. 筛选买入信号
    recommendations = []
    pos_data = get_all_positions()
    funds_data = pos_data.get('funds', {})

    for sig in all_signals:
        # 只保留买入信号
        if sig.get('action') != 'buy':
            continue

        real_code, _ = parse_fund_key(sig.get('fund_code', ''))

        # 必须在符合条件的基金列表中
        if real_code not in eligible_codes:
            continue

        # 置信度过滤
        confidence = sig.get('_confidence', sig.get('confidence', 1.0))
        if filters.min_confidence is not None and confidence < filters.min_confidence:
            continue

        # 信号类型过滤
        signal_name = sig.get('signal_name', '')
        if filters.signal_filter:
            matched = any(s in signal_name for s in filters.signal_filter)
            if not matched:
                continue

        # 3日累计下跌过滤（短期趋势向下，不应建仓）
        ma = sig.get('market_analysis', {})
        trend_ctx = {
            'short_3d': ma.get('short_3d'),
        }
        if _is_short_term_downtrend(trend_ctx):
            continue

        # 添加额外信息
        rec = {
            **sig,
            "sector": sector_map.get(real_code, "未分组"),
            "position_ratio": 0.0,
            "fund_name": sig.get("fund_name") or get_fund_name(real_code) or "",
        }

        # 计算仓位比例
        fund = funds_data.get(real_code, {})
        holding = [b for b in fund.get('batches', []) if b.get('status') == 'holding']
        total_cost = sum(b.get('amount', 0) for b in holding)
        max_pos = fund.get('max_position', 5000)
        rec["position_ratio"] = round(total_cost / max_pos * 100, 1) if max_pos > 0 else 0

        recommendations.append(rec)

    # 5. 排序
    recommendations.sort(key=lambda r: (
        SIGNAL_PRIORITY.get(r.get('signal_name', ''), 99),
        r.get('priority', 99),
        r.get('sub_priority', 0)
    ))

    # 6. 每板块只保留最优
    best_recommendations = select_best_per_sector(recommendations, sector_map)

    return {
        "recommendations": best_recommendations,
        "total": len(best_recommendations),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters": {
            "sector_filter": filters.sector_filter,
            "signal_filter": filters.signal_filter,
            "min_confidence": filters.min_confidence,
            "position_mode": filters.position_mode,
        }
    }
