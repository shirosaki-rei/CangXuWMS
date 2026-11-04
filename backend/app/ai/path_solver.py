"""拣货路径优化（X03 / 接口 53 / PRD 7.3 + ADR-005）。

三档算法：
  ≤12 点    Held-Karp 精确解
  13–50 点  最近邻构造 + 2-opt 改进
  >50 点   按库区聚类 + 区内 S 型

距离 = 欧氏(coord) × 通道系数 1.25。纯函数，不碰数据库。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

CHANNEL_FACTOR = 1.25
EXACT_MAX = 12
HEURISTIC_MAX = 50


@dataclass
class Point:
    code: str
    x: float
    y: float
    qty: int = 1


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y) * CHANNEL_FACTOR


def _matrix(pts: list[Point]) -> list[list[float]]:
    n = len(pts)
    return [[_dist(pts[i], pts[j]) for j in range(n)] for i in range(n)]


def _tour_len(route: list[int], m: list[list[float]]) -> float:
    return sum(m[route[i]][route[i + 1]] for i in range(len(route) - 1))


def held_karp(pts: list[Point], m: list[list[float]]) -> list[int]:
    """精确解：起点固定为 0 号点（出入口），DP over subsets。"""
    n = len(pts)
    if n <= 2:
        return list(range(n))
    INF = float("inf")
    # dp[mask][i] = 从 0 出发、访问 mask 内的点、停在 i 的最短距离
    dp = [[INF] * n for _ in range(1 << n)]
    prev = [[-1] * n for _ in range(1 << n)]
    dp[1][0] = 0.0
    for mask in range(1 << n):
        if not (mask & 1):
            continue
        for i in range(n):
            if dp[mask][i] == INF:
                continue
            for j in range(1, n):
                if mask & (1 << j):
                    continue
                nm = mask | (1 << j)
                nd = dp[mask][i] + m[i][j]
                if nd < dp[nm][j]:
                    dp[nm][j] = nd
                    prev[nm][j] = i
    full = (1 << n) - 1
    best, best_i = INF, -1
    for i in range(1, n):
        if dp[full][i] < best:
            best, best_i = dp[full][i], i
    route, mask, cur = [], full, best_i
    while cur != -1:
        route.append(cur)
        cur, mask = prev[mask][cur], mask ^ (1 << cur)
    route.reverse()
    return route


def nearest_neighbor(pts: list[Point], m: list[list[float]]) -> list[int]:
    n = len(pts)
    unvisited = set(range(1, n))
    route = [0]
    while unvisited:
        last = route[-1]
        nxt = min(unvisited, key=lambda j: (m[last][j], pts[j].code))
        route.append(nxt)
        unvisited.remove(nxt)
    return route


def two_opt(route: list[int], m: list[list[float]], max_rounds: int = 60) -> list[int]:
    """经典 2-opt：反转一段看是否更短。点数有限，够用。"""
    best = route[:]
    improved = True
    rounds = 0
    while improved and rounds < max_rounds:
        improved = False
        rounds += 1
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best)):
                if j - i == 1:
                    continue
                a, b = best[i - 1], best[i]
                c, d = best[j - 1], best[j]
                if m[a][c] + m[b][d] < m[a][b] + m[c][d] - 1e-9:
                    best[i:j] = reversed(best[i:j])
                    improved = True
    return best


def cluster_s_shape(pts: list[Point]) -> list[int]:
    """>50 点：按库区（编码首段字母）聚类，区内按坐标蛇形走。"""
    n = len(pts)
    zones: dict[str, list[int]] = {}
    for i in range(1, n):
        zone = pts[i].code.split("-")[0][:1] or "Z"
        zones.setdefault(zone, []).append(i)

    order = [0]
    for zone in sorted(zones):
        idx = sorted(zones[zone], key=lambda i: (round(pts[i].y / 3), pts[i].x))
        # 蛇形：偶数排从左到右，奇数排从右到左，少走回头路
        rows: dict[int, list[int]] = {}
        for i in idx:
            rows.setdefault(round(pts[i].y / 3), []).append(i)
        for r_i, r in enumerate(sorted(rows)):
            seq = sorted(rows[r], key=lambda i: pts[i].x)
            order.extend(seq if r_i % 2 == 0 else reversed(seq))
    return order


def optimize(points: list[Point], *, timeout_ms: int = 500) -> dict:
    """返回顺序、距离、相对基线（按库位编码排序）的节省。"""
    started = time.perf_counter()
    if not points:
        return {"sequence": [], "distance_m": 0.0, "baseline_m": 0.0, "saved_m": 0.0,
                "saved_pct": 0.0, "algorithm": "NONE", "point_count": 0, "elapsed_ms": 0}

    pts = points
    m = _matrix(pts)
    n = len(pts)

    if n <= 2:
        route = list(range(n))
        algo = "TRIVIAL"
    elif n <= EXACT_MAX:
        route = held_karp(pts, m)
        algo = "HELD_KARP"
    elif n <= HEURISTIC_MAX:
        route = two_opt(nearest_neighbor(pts, m), m)
        algo = "NN_2OPT"
    else:
        route = cluster_s_shape(pts)
        algo = "CLUSTER_S"

    dist = _tour_len(route, m)
    # 基线：默认按库位编码顺序走
    base_order = sorted(range(n), key=lambda i: pts[i].code)
    baseline = _tour_len(base_order, m)
    saved = max(0.0, baseline - dist)
    pct = (saved / baseline * 100) if baseline > 0 else 0.0
    elapsed = (time.perf_counter() - started) * 1000

    return {
        "sequence": [pts[i].code for i in route],
        "distance_m": round(dist, 1),
        "baseline_m": round(baseline, 1),
        "saved_m": round(saved, 1),
        "saved_pct": round(pct, 0),
        "algorithm": algo,
        "point_count": n,
        "elapsed_ms": round(elapsed, 1),
    }
