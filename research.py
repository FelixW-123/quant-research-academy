#!/usr/bin/env python3
"""知量研究学院：可复现的教学研究。纯 Python 标准库；不连接券商。
X_t 截至 t 收盘；y_t = 1[C_(t+1) > O_(t+1)]。
默认合成数据不能证明真实市场预测能力。详见 README.md。
"""
import argparse
import csv
import json
import math
from datetime import date
from pathlib import Path
from statistics import mean, pstdev


def load_prices(path):
    """严格读取同一价格基准的 OHLC CSV。"""
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < 80:
        raise ValueError("至少需要 80 行日线。")
    for i, row in enumerate(rows):
        if date.fromisoformat(row["date"]).isoformat() != row["date"]:
            raise ValueError("日期必须采用 YYYY-MM-DD。")
        if i and row["date"] <= rows[i - 1]["date"]:
            raise ValueError("日期必须唯一并严格递增。")
        for key in ("open", "high", "low", "close"):
            row[key] = float(row[key])
            if not math.isfinite(row[key]) or row[key] <= 0:
                raise ValueError("价格必须为有限正数。")
        if row["high"] < max(row["open"], row["close"]) or row["low"] > min(row["open"], row["close"]):
            raise ValueError("最高/最低价必须包住开收盘。")
    return rows


def build_samples(prices):
    """特征只切到 t；没有下一日答案的最后一行不生成标签。"""
    samples = []
    for t in range(10, len(prices) - 1):
        returns = [prices[j]["close"] / prices[j - 1]["close"] - 1 for j in range(t - 9, t + 1)]
        nxt = prices[t + 1]
        samples.append({
            "date": prices[t]["date"], "label_date": nxt["date"],
            "x": [returns[-1], prices[t]["close"] / prices[t - 5]["close"] - 1, pstdev(returns)],
            "y": int(nxt["close"] > nxt["open"]),
            "open": nxt["open"], "close": nxt["close"],
        })
    return samples


def split_samples(samples):
    """60/20/20 时间切分，两处边界各隔离一行，适用于本站单日标签。"""
    a, b = int(len(samples) * .6), int(len(samples) * .8)
    parts = {"train": samples[:a], "validation": samples[a + 1:b], "test": samples[b + 1:]}
    assert parts["train"][-1]["label_date"] < parts["validation"][0]["date"]
    assert parts["validation"][-1]["label_date"] < parts["test"][0]["date"]
    return parts


def sigmoid(score):
    return 1 / (1 + math.exp(-max(-35, min(35, score))))


def fit_logistic(rows, penalty=.1, features=(0, 1, 2)):
    """训练集拟合均值、总体标准差与系数；不接收验证/测试数据。"""
    if not rows or not features or not math.isfinite(penalty) or penalty < 0:
        raise ValueError("训练设置无效。")
    centers = [mean(row["x"][j] for row in rows) for j in features]
    scales = [pstdev(row["x"][j] for row in rows) or 1 for j in features]
    x = [[1] + [(row["x"][j] - centers[k]) / scales[k] for k, j in enumerate(features)] for row in rows]
    weights = [0.] * (len(features) + 1)
    # 平均对数损失 + penalty/2 * sum(non-intercept weight**2)
    for _ in range(700):
        gradient = [0.] * len(weights)
        for row, values in zip(rows, x):
            error = sigmoid(sum(a * b for a, b in zip(weights, values))) - row["y"]
            for k, value in enumerate(values):
                gradient[k] += error * value / len(rows)
        weights = [w - .15 * (gradient[k] + (penalty * w if k else 0)) for k, w in enumerate(weights)]
    return {"weights": weights, "means": centers, "scales": scales,
            "features": list(features), "base": mean(row["y"] for row in rows)}


def predict(model, rows):
    return [sigmoid(model["weights"][0] + sum(
        model["weights"][k + 1] * (row["x"][j] - model["means"][k]) / model["scales"][k]
        for k, j in enumerate(model["features"]))) for row in rows]


def metrics(rows, probabilities):
    probabilities = [min(1 - 1e-12, max(1e-12, p)) for p in probabilities]
    bins = []
    for b in range(5):
        pairs = [(row["y"], p) for row, p in zip(rows, probabilities) if min(4, int(p * 5)) == b]
        bins.append({"n": len(pairs), "mean_probability": mean(p for _, p in pairs) if pairs else None,
                     "up_rate": mean(y for y, _ in pairs) if pairs else None})
    return {
        "n": len(rows),
        "accuracy": mean(int(p >= .5) == row["y"] for row, p in zip(rows, probabilities)),
        "brier": mean((p - row["y"]) ** 2 for row, p in zip(rows, probabilities)),
        "logloss": mean(-row["y"] * math.log(p) - (1 - row["y"]) * math.log(1 - p)
                        for row, p in zip(rows, probabilities)),
        "calibration": bins,
    }


def size_position(equity=100000, cash=80000, entry=50, stop=48, risk_pct=.5,
                  cap_pct=20, total_risk_pct=2, existing_risk_pct=.8, fee_bps=5, slip_bps=5, lot=1):
    """四个数量约束取最小；计划止损损失不是损失保证。"""
    values = [equity, cash, entry, stop, risk_pct, cap_pct, total_risk_pct, existing_risk_pct, fee_bps, slip_bps, lot]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("输入必须为有限数字。")
    if equity <= 0 or not 0 <= cash <= equity or not 0 < stop < entry:
        raise ValueError("账户、现金或做多价格关系无效。")
    if any(not 0 <= p <= 100 for p in [risk_pct, cap_pct, total_risk_pct, existing_risk_pct]):
        raise ValueError("比例须在 0–100%。")
    if not 0 <= fee_bps <= 1000 or not 0 <= slip_bps <= 1000 or lot < 1 or lot != int(lot):
        raise ValueError("费用或交易单位无效。")
    fee, slip = fee_bps / 10000, slip_bps / 10000
    buy = entry * (1 + slip) * (1 + fee)
    planned_sell = stop * (1 - slip) * (1 - fee)
    per_share = buy - planned_sell
    budget = equity * risk_pct / 100
    remaining = equity * max(0, total_risk_pct - existing_risk_pct) / 100
    limits = {"single_trade_risk": budget / per_share, "asset_cap": equity * cap_pct / 100 / entry,
              "cash": cash / buy, "portfolio_planned_risk": remaining / per_share}
    binding = min(limits, key=limits.get)
    shares = max(0, math.floor((limits[binding] + 1e-9) / lot) * int(lot))
    return {"shares": shares, "binding": binding, "buy": buy, "planned_loss": shares * per_share,
            "notional": shares * entry, "cash_used": shares * buy, "limits": limits}


def max_drawdown(curve):
    high, result = curve[0], 0
    for value in curve:
        high = max(high, value)
        result = max(result, 1 - value / high)
    return result


def simulate(rows, probabilities, threshold=.55, risk_pct=.5, cap_pct=30,
             stop_pct=4, fee_bps=5, slip_bps=5):
    """日内做多；距离仅定数量，不模拟止损。日终净值不捕获日内最大回撤。"""
    equity, costs, exposure = 100000., 0., 0.
    curve, ledger = [equity], []
    for row, probability in zip(rows, probabilities):
        if probability >= threshold:
            q = size_position(equity, equity, row["open"], row["open"] * (1 - stop_pct / 100),
                              risk_pct, cap_pct, risk_pct, 0, fee_bps, slip_bps, 1)
            exit_net = row["close"] * (1 - slip_bps / 10000) * (1 - fee_bps / 10000)
            pnl = q["shares"] * (exit_net - q["buy"])
            costs += q["shares"] * ((q["buy"] - row["open"]) + (row["close"] - exit_net))
            exposure += q["notional"] / equity
            equity += pnl
            if q["shares"]:
                ledger.append({"date": row["label_date"], "probability": probability,
                               "shares": q["shares"], "pnl": pnl, "equity": equity})
        curve.append(equity)
    return {"equity": equity, "return": equity / 100000 - 1, "drawdown": max_drawdown(curve),
            "trades": len(ledger), "costs": costs, "exposure": exposure / len(rows), "ledger": ledger}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path(__file__).with_name("sample_prices.csv"))
    parser.add_argument("--penalty", type=float, default=.1)
    parser.add_argument("--features", default="0,1,2", help="0=1日收益，1=5日动量，2=10日波动")
    parser.add_argument("--threshold", type=float, default=.55)
    parser.add_argument("--fee-bps", type=float, default=5)
    parser.add_argument("--slip-bps", type=float, default=5)
    parser.add_argument("--reveal-test", action="store_true", help="方案冻结后才用；看过后不再是未见样本")
    parser.add_argument("--out", type=Path, help="可选 JSON 输出路径；每次使用新文件名保存尝试")
    args = parser.parse_args()
    features = tuple(int(j) for j in args.features.split(","))
    if not features or len(features) != len(set(features)) or any(j not in (0, 1, 2) for j in features):
        parser.error("特征必须为不重复的 0、1、2。")
    if not 0 <= args.threshold <= 1 or not 0 <= args.fee_bps <= 1000 or not 0 <= args.slip_bps <= 1000:
        parser.error("阈值需在 0–1，费用和滑点需在 0–1000 bp。")
    prices = load_prices(args.csv)
    parts = split_samples(build_samples(prices))
    model = fit_logistic(parts["train"], args.penalty, features)
    report = {"data": str(args.csv), "data_note": "默认 CSV 是合成数据；真实数据必须自行核对来源与价格基准。",
              "protocol": "t close features; t+1 open-to-close gross direction; costs in trading layer",
              "counts": {k: len(v) for k, v in parts.items()}, "model": model,
              "settings": {"threshold": args.threshold, "fee_bps": args.fee_bps, "slip_bps": args.slip_bps,
                           "risk_pct": .5, "cap_pct": 30, "sizing_distance_pct": 4, "stop_executed": False},
              "position_example": size_position()}
    for key in (["validation", "test"] if args.reveal_test else ["validation"]):
        rows = parts[key]
        probabilities = predict(model, rows)
        params = {"threshold": args.threshold, "fee_bps": args.fee_bps, "slip_bps": args.slip_bps}
        report[key] = {"metrics": metrics(rows, probabilities),
                       "baseline_metrics": metrics(rows, [model["base"]] * len(rows)),
                       "strategy": simulate(rows, probabilities, **params),
                       "daily_intraday_baseline": simulate(rows, [1.] * len(rows), **params)}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with args.out.open("x", encoding="utf-8") as handle:
            handle.write(output + "\n")  # x 模式防止覆盖历史研究记录
    print(output)
    print("\n合成样本结果不证明真实市场优势。测试一旦揭晓，后续修改属于探索。")


if __name__ == "__main__":
    main()
