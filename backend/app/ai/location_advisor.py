"""库位推荐（X02 / 接口 52 / PRD 7.2）。

纯函数：输入候选库位与上下文，输出 Top1 + 2 备选 + 3 条理由 + 置信度。
数据怎么取在 service 层，这里只算——好测，也好在没库的时候单独验证。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 权重（PRD 7.2）：冷启动时 w4 置 0 后归一化
W_AFFINITY = 0.35
W_CAPACITY = 0.20
W_DISTANCE = 0.25
W_TURNOVER = 0.20
W_PENALTY = 1.0

# 置信度按 Top1−Top2 分差（ADR-007）
CONF_HIGH = 8.0
CONF_MID = 3.0


@dataclass
class Candidate:
    location_id: int
    code: str
    type: str
    status: str
    cap_pallet: int
    used_pallet: int
    dist_to_pack: float | None
    same_sku_pallets: int = 0       # 同 SKU 在本库区的托数
    turnover_30d: int = 0           # 近 30 天该库位出库频次（冷启动为 0）


@dataclass
class Context:
    pallet_count: int
    warehouse_id: int
    is_dangerous: bool = False
    temp_control: str = "NONE"
    cold_start: bool = True         # < 30 天数据
    coord_required: bool = True


@dataclass
class Scored:
    c: Candidate
    score: float
    parts: dict[str, float] = field(default_factory=dict)


def _allowed(c: Candidate, ctx: Context) -> bool:
    """BR-013 / BR-008：库位类型与物料属性匹配，锁定与维保不参与。"""
    if c.status not in ("IDLE", "OCCUPIED"):
        return False
    if c.type == "DANGEROUS" and not ctx.is_dangerous:
        return False
    if c.type == "CONSTANT_TEMP" and ctx.temp_control == "NONE":
        return False
    return True


def _capacity_ok(c: Candidate, ctx: Context) -> bool:
    return c.used_pallet + ctx.pallet_count <= c.cap_pallet


def score_candidates(cands: list[Candidate], ctx: Context) -> tuple[list[Scored], bool]:
    """返回 (按分排序的候选, degraded)。

    degraded=True 表示所有候选都缺坐标，距离维度权重被置 0（PRD 7.7 / 接口 3.4）。
    """
    alive = [c for c in cands if _allowed(c, ctx) and _capacity_ok(c, ctx)]
    if not alive:
        return [], False

    has_coord = any(c.dist_to_pack is not None for c in alive)
    degraded = ctx.coord_required and not has_coord
    # 缺坐标的候选不参与排序（BR-025）
    if has_coord:
        alive = [c for c in alive if c.dist_to_pack is not None]

    w1, w2, w3, w4 = W_AFFINITY, W_CAPACITY, W_DISTANCE, W_TURNOVER
    if degraded:
        w3 = 0.0
    if ctx.cold_start:
        w4 = 0.0
    total_w = w1 + w2 + w3 + w4
    if total_w <= 0:
        total_w = 1.0

    max_pallets = max((c.same_sku_pallets for c in alive), default=0) or 1
    max_dist = max((c.dist_to_pack or 0) for c in alive) or 1
    max_turn = max((c.turnover_30d for c in alive), default=0) or 1
    cap_pallet = max((c.cap_pallet for c in alive), default=1) or 1

    out: list[Scored] = []
    for c in alive:
        affinity = c.same_sku_pallets / max_pallets
        # 容量适配：放下后剩余的比例，太满和太空都不理想，取「放得下且留有余量」
        remain = (c.cap_pallet - c.used_pallet - ctx.pallet_count) / cap_pallet
        capacity = max(0.0, min(1.0, remain))
        distance = 1.0 - ((c.dist_to_pack or 0) / max_dist)
        turnover = 1.0 - abs(c.turnover_30d - max_turn / 2) / max_turn

        raw = (w1 * affinity + w2 * capacity + w3 * distance + w4 * turnover) / total_w
        out.append(Scored(c=c, score=round(raw * 100, 1),
                          parts={"affinity": affinity, "capacity": capacity,
                                 "distance": distance, "turnover": turnover}))

    out.sort(key=lambda s: (-s.score, s.c.code))
    return out, degraded


def _reason(sc: Scored, ctx: Context, degraded: bool) -> str:
    """理由只讲事实，不讲算法——现场的人要能读懂。"""
    c = sc.c
    if sc.parts["affinity"] >= 0.5:
        return f"同物料已有 {c.same_sku_pallets} 托在此区，集中管理"
    if sc.parts["capacity"] >= 0.3:
        free = c.cap_pallet - c.used_pallet
        return f"剩余容量 {free} 托，可容纳本次 {ctx.pallet_count} 托"
    if not degraded and c.dist_to_pack is not None:
        return f"距打包区 {c.dist_to_pack:.0f}m"
    return "空库位，可直接上架"


def recommend(cands: list[Candidate], ctx: Context) -> dict:
    scored, degraded = score_candidates(cands, ctx)
    if not scored:
        return {
            "primary": None, "alternatives": [], "degraded": degraded,
            "confidence": "LOW", "reason": "没有满足硬约束的库位（类型/容量/状态）",
        }

    top = scored[0]
    gap = top.score - (scored[1].score if len(scored) > 1 else 0.0)
    if gap >= CONF_HIGH:
        confidence = "HIGH"
    elif gap >= CONF_MID:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # 理由条数：正常 3 条；降级时没有距离维度，只给 2 条（接口 3.4）
    want = 2 if degraded else 3
    reasons: list[str] = []
    for sc in scored[:3]:
        r = _reason(sc, ctx, degraded)
        if r not in reasons:
            reasons.append(r)
    if len(reasons) < want:
        for sc in scored[:5]:
            r = _reason(sc, ctx, degraded)
            if r not in reasons:
                reasons.append(r)
    reasons = reasons[:want]

    if confidence == "LOW":
        # 低置信度不给 Top1，只并列 3 个候选（AC-AI-03）
        return {
            "primary": None,
            "alternatives": [
                {"location_id": s.c.location_id, "location_code": s.c.code,
                 "score": s.score, "note": _reason(s, ctx, degraded)}
                for s in scored[:3]
            ],
            "degraded": degraded,
            "confidence": "LOW",
            "reason": "候选库位分差过小，建议人工判断",
        }

    return {
        "primary": {
            "location_id": top.c.location_id,
            "location_code": top.c.code,
            "confidence": confidence,
            "score": top.score,
            "reasons": reasons,
        },
        "alternatives": [
            {"location_id": s.c.location_id, "location_code": s.c.code,
             "score": s.score, "note": _reason(s, ctx, degraded)}
            for s in scored[1:3]
        ],
        "degraded": degraded,
        "confidence": confidence,
        "reason": None,
    }
