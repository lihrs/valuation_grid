#!/usr/bin/env python3
"""
基金热点筛选器 - 基于热门股票反向筛选基金

数据源：新浪财经（涨幅榜）
评分体系（满分150分）：
- 持仓匹配（40分）：基金持有热门股票的比例
- 资金流入（10分）：匹配股票的涨幅热度
- 基金动量（30分）：近期净值涨幅
- 基金质量（40分）：估值置信度、当日涨幅等
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
import time
import requests

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ==================== 配置 ====================

# 热门概念关键词
HOT_CONCEPTS_KEYWORDS = [
    # AI/算力/通信
    'CPO', '光模块', 'F5G', '光纤', '服务器', '算力', 'AI', '人工智能',
    # 芯片/半导体
    '芯片', '半导体', '光刻机', '集成电路',
    # 机器人
    '机器人', '减速器', '电机',
    # 低空经济
    '低空', '飞行汽车', '无人机', 'eVTOL',
    # 电池/新能源
    '电池', 'HJT', 'BC电池', 'TOPCON', '固态电池', '钙钛矿', '钠离子', '硅能源',
    '锂电', '储能', '光伏', '氢能源', '盐湖提锂', '动力电池回收',
    # 有色金属
    '有色', '稀土', '黄金', '铜', '锂矿',
    # 其他科技
    '数据要素', '数据确权', '大数据', '云计算',
    '元宇宙', '虚拟现实', '增强现实',
    '自动驾驶', '激光雷达', '智能座舱',
    '工业母机', '高端装备', '智能制造'
]

FILTERS = {
    'stock_min_change': 3,        # 个股最小涨幅%
    'fund_min_score': 60,         # 基金最小评分
    'max_fund_results': 30,       # 最大返回基金数量
}

# ==================== 数据获取函数 ====================

def get_hot_stocks_sina() -> Optional[List[dict]]:
    """通过新浪财经 API 获取个股涨幅榜"""
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1,
            "num": 100,
            "sort": "changepercent",
            "asc": 0,
            "node": "hs_a",
            "_s_r_a": "page",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://vip.stock.finance.sina.com.cn/mkt/",
        }

        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()

        if data and isinstance(data, list):
            result = []
            for item in data:
                code = item.get("code", "")
                name = item.get("name", "")
                change = float(item.get("changepercent", 0) or 0)
                price = float(item.get("trade", 0) or 0)
                volume = float(item.get("volume", 0) or 0)  # 成交量

                if change >= FILTERS['stock_min_change']:
                    result.append({
                        'code': code,
                        'name': name,
                        'change': change,
                        'price': price,
                        'volume': volume,
                        'inflow': change * 1000,  # 用涨幅估算热度
                    })
            return result
    except Exception as e:
        print(f"  ❌ 新浪财经获取数据失败: {e}")
    return None

def get_hot_sectors_sina() -> Optional[List[dict]]:
    """通过新浪财经 API 获取板块涨幅榜"""
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1,
            "num": 100,
            "sort": "changepercent",
            "asc": 0,
            "node": "bk_a_gn",  # 概念板块
            "_s_r_a": "page",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://vip.stock.finance.sina.com.cn/mkt/",
        }

        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()

        if data and isinstance(data, list):
            result = []
            for item in data:
                name = item.get("name", "")
                change = float(item.get("changepercent", 0) or 0)

                if change >= 2:  # 板块涨幅>2%
                    is_tech = any(kw in name for kw in HOT_CONCEPTS_KEYWORDS)
                    result.append({
                        'name': name,
                        'change': change,
                        'inflow': change * 10,
                        'is_tech': is_tech,
                    })
            return result
    except Exception as e:
        print(f"  ⚠️ 新浪财经获取板块数据失败: {e}")
    return None

def load_fund_holdings(fund_code: str) -> Optional[dict]:
    """加载基金持仓数据"""
    cache_file = PROJECT_ROOT / "cache" / f"holdings_{fund_code}.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None

def load_all_fund_holdings() -> Dict[str, dict]:
    """加载所有基金持仓数据"""
    cache_dir = PROJECT_ROOT / "cache"
    holdings = {}
    for cache_file in cache_dir.glob("holdings_*.json"):
        fund_code = cache_file.stem.replace("holdings_", "")
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                holdings[fund_code] = data
        except Exception:
            pass
    return holdings

def load_state_funds() -> Dict[str, List[str]]:
    """加载板块配置中的基金，返回 {板块名: [基金代码列表]}"""
    state_file = PROJECT_ROOT / "data" / "state.json"
    if not state_file.exists():
        return {}

    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)

        sector_funds = {}
        for sector in state.get("sectors", []):
            sector_name = sector.get("name", "")
            funds = [f.get("code") for f in sector.get("funds", []) if f.get("code")]
            if sector_name and funds:
                sector_funds[sector_name] = funds
        return sector_funds
    except Exception:
        return {}

def get_fund_valuation(fund_code: str) -> Optional[dict]:
    """获取基金估值数据"""
    try:
        from valuation.core import calculate_valuation
        return calculate_valuation(fund_code)
    except Exception:
        return None

def get_fund_nav_history(fund_code: str, days: int = 20) -> List[dict]:
    """获取基金净值历史"""
    try:
        from valuation.providers import get_fund_nav_history
        return get_fund_nav_history(fund_code, days)
    except Exception:
        return []

# ==================== 核心计算函数 ====================

def match_fund_to_hot_stocks(fund_code: str, fund_holdings: dict,
                              hot_stocks: List[dict]) -> dict:
    """计算基金与热门股票的匹配度"""
    if not fund_holdings or 'positions' not in fund_holdings:
        return {'matched_stocks': [], 'matched_weight': 0, 'matched_change': 0}

    # 基金持仓股票代码集合
    fund_positions = {p['stock_code']: p.get('weight', 0)
                      for p in fund_holdings.get('positions', [])}

    # 热门股票代码集合
    hot_stock_codes = {s['code']: s for s in hot_stocks}

    # 计算交集
    matched_stocks = []
    matched_weight = 0
    matched_change = 0

    for stock_code, weight in fund_positions.items():
        if stock_code in hot_stock_codes:
            hot_stock = hot_stock_codes[stock_code]
            matched_stocks.append({
                'code': stock_code,
                'name': hot_stock.get('name', ''),
                'weight': weight,
                'change': hot_stock.get('change', 0),
            })
            matched_weight += weight
            matched_change += hot_stock.get('change', 0)

    return {
        'matched_stocks': matched_stocks,
        'matched_weight': matched_weight,
        'matched_change': matched_change,
    }

def calc_fund_score(fund_code: str, match_info: dict,
                    valuation: dict, nav_history: List[dict]) -> dict:
    """
    计算基金综合评分（满分150分）
    """
    score = 0
    score_details = {}

    # 1. 持仓匹配度（40分）
    matched_weight = match_info.get('matched_weight', 0)
    matched_count = len(match_info.get('matched_stocks', []))

    if matched_weight > 0.5:
        score += 40
    elif matched_weight > 0.3:
        score += 35
    elif matched_weight > 0.15:
        score += 25
    elif matched_weight > 0.05:
        score += 15
    score_details['holdings_score'] = score

    # 2. 匹配股票涨幅热度（额外加分，最多10分）
    matched_change = match_info.get('matched_change', 0)
    inflow_score = min(10, matched_change / 5)
    score += inflow_score
    score_details['inflow_score'] = inflow_score

    # 3. 基金动量（30分）：基于净值历史
    momentum_score = 0
    if nav_history and len(nav_history) >= 5:
        changes = [h.get('change', 0) for h in nav_history[:5] if h.get('change') is not None]
        if changes:
            compound = 1
            for c in changes:
                compound *= (1 + c/100)
            cumulative = (compound - 1) * 100

            if cumulative > 10:
                momentum_score = 30
            elif cumulative > 5:
                momentum_score = 25
            elif cumulative > 2:
                momentum_score = 20
            elif cumulative > 0:
                momentum_score = 10
            elif cumulative < -5:
                momentum_score = 5
    score += momentum_score
    score_details['momentum_score'] = momentum_score

    # 4. 基金质量（40分）：估值置信度 + 当日涨幅
    quality_score = 0
    if valuation:
        confidence = valuation.get('calibrated_confidence', valuation.get('confidence', 0))
        estimation_change = valuation.get('estimation_change', 0)

        if confidence > 0.8:
            quality_score += 20
        elif confidence > 0.6:
            quality_score += 15
        elif confidence > 0.4:
            quality_score += 10

        if estimation_change > 3:
            quality_score += 20
        elif estimation_change > 1:
            quality_score += 15
        elif estimation_change > 0:
            quality_score += 10

    score += quality_score
    score_details['quality_score'] = quality_score

    return {
        'total_score': score,
        'details': score_details,
    }

# ==================== 主程序 ====================

def screen_funds():
    """主筛选函数"""
    print("=" * 70)
    print(f"📊 基金热点筛选器 [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print("=" * 70)
    print()

    start_time = time.time()

    # ========== 步骤1：获取市场数据 ==========
    print("【步骤1】获取市场热门股票数据...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_stocks = executor.submit(get_hot_stocks_sina)
        future_sectors = executor.submit(get_hot_sectors_sina)

        hot_stocks = future_stocks.result()
        hot_sectors = future_sectors.result()

    if hot_stocks:
        print(f"  ✅ 热门个股: {len(hot_stocks)}只 (涨幅≥{FILTERS['stock_min_change']}%)")
    else:
        print(f"  ❌ 热门个股: 获取失败")

    if hot_sectors:
        tech_count = sum(1 for s in hot_sectors if s.get('is_tech'))
        print(f"  ✅ 热门板块: {len(hot_sectors)}个 (科技/新能源: {tech_count}个)")
    else:
        print(f"  ⚠️ 热门板块: 获取失败")

    if not hot_stocks:
        print("  ❌ 无法获取市场数据，退出")
        return

    # 打印TOP10热门股票
    if hot_stocks:
        print("\n  🔥 TOP10 热门股票:")
        for i, s in enumerate(hot_stocks[:10], 1):
            print(f"     {i}. {s['code']} {s['name']} 涨幅:{s['change']:.2f}%")

    print()

    # ========== 步骤2：加载基金持仓数据 ==========
    print("【步骤2】加载基金持仓数据...")

    all_holdings = load_all_fund_holdings()
    sector_funds = load_state_funds()

    print(f"  基金持仓缓存: {len(all_holdings)}只")
    print(f"  板块配置: {len(sector_funds)}个板块")
    print()

    # ========== 步骤3：匹配基金与热门股票 ==========
    print("【步骤3】匹配基金与热门股票...")

    fund_scores = []

    for fund_code, fund_holdings in all_holdings.items():
        match_info = match_fund_to_hot_stocks(fund_code, fund_holdings, hot_stocks)

        if match_info['matched_weight'] < 0.01:
            continue

        valuation = None
        nav_history = []
        try:
            valuation = get_fund_valuation(fund_code)
            nav_history = get_fund_nav_history(fund_code, 10)
        except Exception:
            pass

        score_info = calc_fund_score(fund_code, match_info, valuation, nav_history)

        if score_info['total_score'] >= FILTERS['fund_min_score']:
            sector_name = ""
            for s_name, codes in sector_funds.items():
                if fund_code in codes:
                    sector_name = s_name
                    break

            fund_scores.append({
                'fund_code': fund_code,
                'fund_name': fund_holdings.get('fund_name', ''),
                'sector': sector_name,
                'score': score_info['total_score'],
                'score_details': score_info['details'],
                'match_info': match_info,
                'valuation': valuation,
            })

    fund_scores.sort(key=lambda x: x['score'], reverse=True)

    print(f"  符合条件的基金: {len(fund_scores)}只")
    print()

    # ========== 步骤4：输出结果 ==========
    print("=" * 70)
    print(f"🎯 精选 TOP {min(FILTERS['max_fund_results'], len(fund_scores))} 基金")
    print("=" * 70)

    for i, fund in enumerate(fund_scores[:FILTERS['max_fund_results']], 1):
        print(f"\n{i}. {fund['fund_code']} - {fund['fund_name'] or '未知'}")
        print(f"   板块: {fund['sector'] or '未分类'}")
        print(f"   综合评分: {fund['score']:.0f}分")
        print(f"   评分明细: 持仓{fund['score_details'].get('holdings_score', 0):.0f} + "
              f"热度{fund['score_details'].get('inflow_score', 0):.0f} + "
              f"动量{fund['score_details'].get('momentum_score', 0):.0f} + "
              f"质量{fund['score_details'].get('quality_score', 0):.0f}")

        matched = fund['match_info'].get('matched_stocks', [])
        if matched:
            print(f"   匹配热门股: {len(matched)}只 (权重{fund['match_info']['matched_weight']*100:.1f}%)")
            for s in matched[:3]:
                print(f"      - {s['code']} {s['name']} 权重{s['weight']*100:.1f}% 涨幅{s['change']:.2f}%")

        val = fund.get('valuation')
        if val:
            est = val.get('estimation_change', 0)
            conf = val.get('calibrated_confidence', 0)
            print(f"   今日估值: {est:+.2f}% 置信度:{conf:.0%}")

    # ========== 保存结果 ==========
    output = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'hot_sectors': hot_sectors[:20] if hot_sectors else [],
        'hot_stocks': [{'code': s['code'], 'name': s['name'], 'change': s['change']}
                       for s in hot_stocks[:30]],
        'top_funds': [{
            'fund_code': f['fund_code'],
            'fund_name': f['fund_name'],
            'sector': f['sector'],
            'score': f['score'],
            'matched_stocks': f['match_info'].get('matched_stocks', []),
            'matched_weight': f['match_info'].get('matched_weight', 0),
        } for f in fund_scores[:FILTERS['max_fund_results']]]
    }

    output_file = PROJECT_ROOT / "data" / f"fund_screener_{datetime.now().strftime('%Y%m%d')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 结果已保存: {output_file}")
    print(f"总用时: {time.time() - start_time:.1f}秒")

    return fund_scores

def main():
    """命令行入口"""
    screen_funds()

if __name__ == "__main__":
    main()
