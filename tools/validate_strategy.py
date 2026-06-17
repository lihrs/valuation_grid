#!/usr/bin/env python3
"""
策略优化验证脚本

用法:
    python3 tools/validate_strategy.py --baseline     # 运行基准回测
    python3 tools/validate_strategy.py --compare      # 对比结果
    python3 tools/validate_strategy.py --quick        # 快速验证(90天)

功能:
    1. 运行历史回测
    2. 计算关键指标
    3. 对比优化前后效果
    4. 输出验证报告
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
RESULT_FILE = PROJECT_ROOT / "backtest_validation_result.json"


def run_backtest(days=365, funds=None, regime="auto", detail=False):
    """
    运行回测并返回结果

    Args:
        days: 回测天数
        funds: 基金代码列表，None表示默认
        regime: 行情模式
        detail: 是否打印明细

    Returns:
        dict: 回测结果
    """
    cmd_parts = [
        "python3",
        str(PROJECT_ROOT / "tools" / "backtest.py"),
        f"--days={days}",
        "--no-csv",
        f"--regime={regime}",
    ]

    if funds:
        cmd_parts.extend(["--funds"] + funds)

    if detail:
        cmd_parts.append("--detail")

    print(f"执行命令: {' '.join(cmd_parts)}")

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=300,  # 5分钟超时
            cwd=str(PROJECT_ROOT)
        )
        return parse_backtest_output(result.stdout)
    except subprocess.TimeoutExpired:
        print("回测超时，请尝试减少天数或基金数量")
        return None
    except Exception as e:
        print(f"回测执行失败: {e}")
        return None


def parse_backtest_output(output):
    """
    解析回测输出

    Args:
        output: 回测命令的stdout

    Returns:
        dict: 解析后的结果
    """
    result = {
        "funds": [],
        "summary": {},
        "raw_output": output
    }

    lines = output.split("\n")

    for line in lines:
        # 解析基金级别结果
        # 示例行: "017193  天弘中证...  有色金属  12.5%  15.2%  1.2  -8.5%  85"
        if "%" in line and len(line.split()) > 5:
            parts = line.split()
            if parts[0].isdigit() and len(parts[0]) == 6:
                try:
                    fund_result = {
                        "code": parts[0],
                        "name": parts[1] if len(parts) > 1 else "",
                        "annual_return": parse_percentage(parts[-5]) if len(parts) > 4 else 0,
                        "strategy_return": parse_percentage(parts[-4]) if len(parts) > 3 else 0,
                        "sharpe": float(parts[-3]) if len(parts) > 2 else 0,
                        "max_drawdown": parse_percentage(parts[-2]) if len(parts) > 1 else 0,
                    }
                    result["funds"].append(fund_result)
                except:
                    pass

        # 解析汇总行
        if "平均" in line or "汇总" in line:
            result["summary"]["raw"] = line

    return result


def parse_percentage(s):
    """解析百分比字符串"""
    try:
        return float(s.replace("%", "").replace("+", ""))
    except:
        return 0.0


def calculate_metrics(results):
    """
    计算关键指标

    Args:
        results: 回测结果

    Returns:
        dict: 关键指标
    """
    if not results or not results.get("funds"):
        return None

    funds = results["funds"]

    metrics = {
        "fund_count": len(funds),
        "avg_annual_return": sum(f["annual_return"] for f in funds) / len(funds) if funds else 0,
        "avg_strategy_return": sum(f["strategy_return"] for f in funds) / len(funds) if funds else 0,
        "avg_sharpe": sum(f["sharpe"] for f in funds) / len(funds) if funds else 0,
        "avg_max_drawdown": sum(f["max_drawdown"] for f in funds) / len(funds) if funds else 0,
        "win_rate": sum(1 for f in funds if f["strategy_return"] > 0) / len(funds) if funds else 0,
    }

    return metrics


def compare_results(baseline, optimized):
    """
    对比基准和优化结果

    Args:
        baseline: 基准结果
        optimized: 优化结果

    Returns:
        dict: 对比结果
    """
    if not baseline or not optimized:
        return None

    comparison = {
        "timestamp": datetime.now().isoformat(),
        "baseline": baseline,
        "optimized": optimized,
        "changes": {}
    }

    # 计算变化
    for key in ["avg_annual_return", "avg_strategy_return", "avg_sharpe", "avg_max_drawdown", "win_rate"]:
        if key in baseline and key in optimized:
            change = optimized[key] - baseline[key]
            comparison["changes"][key] = {
                "baseline": baseline[key],
                "optimized": optimized[key],
                "change": change,
                "improved": change > 0 if "drawdown" not in key else change < 0
            }

    return comparison


def print_report(comparison):
    """打印验证报告"""
    print("\n" + "=" * 70)
    print("策略优化验证报告")
    print("=" * 70)
    print(f"验证时间: {comparison['timestamp']}")
    print("-" * 70)

    print("\n📊 指标对比:")
    print("-" * 70)
    print(f"{'指标':<25} {'基准':>12} {'优化后':>12} {'变化':>12} {'结果':>8}")
    print("-" * 70)

    for key, data in comparison["changes"].items():
        name = {
            "avg_annual_return": "平均年化收益",
            "avg_strategy_return": "平均策略收益",
            "avg_sharpe": "平均夏普比率",
            "avg_max_drawdown": "平均最大回撤",
            "win_rate": "胜率"
        }.get(key, key)

        symbol = "✓" if data["improved"] else "✗"
        change_str = f"{data['change']:+.2f}%"

        print(f"{name:<25} {data['baseline']:>11.2f}% {data['optimized']:>11.2f}% {change_str:>12} {symbol:>8}")

    print("-" * 70)

    # 总体评价
    improved_count = sum(1 for d in comparison["changes"].values() if d["improved"])
    total_count = len(comparison["changes"])

    print(f"\n📈 总体评价: {improved_count}/{total_count} 指标改善")

    if improved_count >= total_count * 0.6:
        print("✅ 验证通过！优化效果显著。")
        return True
    else:
        print("⚠️ 验证未通过，建议检查优化参数。")
        return False


def save_result(result, filename=None):
    """保存验证结果"""
    filepath = filename or RESULT_FILE
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"结果已保存到: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="策略优化验证工具")
    parser.add_argument("--baseline", action="store_true", help="运行基准回测")
    parser.add_argument("--optimized", action="store_true", help="运行优化后回测")
    parser.add_argument("--compare", action="store_true", help="对比结果")
    parser.add_argument("--quick", action="store_true", help="快速验证(90天)")
    parser.add_argument("--days", type=int, default=365, help="回测天数")
    parser.add_argument("--funds", nargs="+", help="指定基金代码")
    parser.add_argument("--regime", default="auto", help="行情模式")

    args = parser.parse_args()

    days = 90 if args.quick else args.days

    print("=" * 70)
    print("策略优化验证工具")
    print("=" * 70)
    print(f"回测天数: {days}")
    print(f"行情模式: {args.regime}")
    if args.funds:
        print(f"指定基金: {args.funds}")
    print("-" * 70)

    # 运行回测
    print("\n🔄 运行回测中...")
    results = run_backtest(days=days, funds=args.funds, regime=args.regime)

    if not results:
        print("❌ 回测失败")
        return 1

    # 计算指标
    metrics = calculate_metrics(results)

    if not metrics:
        print("❌ 无法解析回测结果")
        print("请检查回测工具输出格式")
        return 1

    # 输出结果
    print("\n📊 回测结果:")
    print("-" * 40)
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")

    # 保存结果
    save_result({
        "metrics": metrics,
        "raw_results": results,
        "config": {
            "days": days,
            "regime": args.regime,
            "funds": args.funds
        }
    })

    return 0


if __name__ == "__main__":
    sys.exit(main())
