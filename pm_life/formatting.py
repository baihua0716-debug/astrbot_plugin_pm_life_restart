from __future__ import annotations

import json
from typing import Any, Iterable


GRADE_MARKS = {0: "⬜", 1: "🟦", 2: "🟪", 3: "🟨", 4: "🟥"}


def format_talents(talents: Iterable[dict[str, Any]]) -> str:
    lines = ["🎲 本次抽取的天赋（请选择 4 个）："]
    for talent in talents:
        mark = GRADE_MARKS.get(int(talent.get("grade", 0)), "⬜")
        lines.append(
            f"{talent['index']:>2}. {mark} {talent['name']}：{talent['description']}"
        )
    lines.extend(
        [
            "",
            "回复 4 个编号，例如：1 2 3 4。",
            "群聊请引用回复 Bot 提示或 @Bot；私聊可直接发送。",
        ]
    )
    return "\n".join(lines)


def format_property_prompt(points: int, selected: Iterable[dict[str, Any]]) -> str:
    names = "、".join(str(item["name"]) for item in selected)
    remaining = points
    example: list[int] = []
    for slots_left in range(4, 0, -1):
        value = min(15, (remaining + slots_left - 1) // slots_left)
        example.append(value)
        remaining -= value
    return (
        f"已选择：{names}\n"
        f"请把 {points} 点分配给运气、智力、体质、家境；每项 0～15。\n"
        f"直接回复，例如：{' '.join(map(str, example))}\n"
        "顺序固定为：运气 智力 体质 家境\n"
        "群聊请引用回复 Bot 提示或 @Bot；私聊可直接发送。"
    )


def format_summary(
    summary: dict[str, Any], seed: str, details: dict[str, Any] | None = None
) -> str:
    order = ["HCHR", "HINT", "HSTR", "HMNY", "HSPR", "HAGE", "SUM"]
    lines = ["🎉 人生总结"]
    if details:
        selected = details.get("selected") or []
        if selected:
            lines.append("天赋：" + "、".join(str(item["name"]) for item in selected))
        allocation = details.get("allocation") or {}
        if allocation:
            lines.append(
                "初始属性："
                f"运气{allocation.get('CHR', 0)} / 智力{allocation.get('INT', 0)} / "
                f"体质{allocation.get('STR', 0)} / 家境{allocation.get('MNY', 0)}"
            )
    for key in order:
        item = summary[key]
        judge = f"（{item['judge']}）" if item.get("judge") else ""
        lines.append(f"{item['label']}：{item['value']}{judge}")
    lines.append(f"种子：{seed}")
    return "\n".join(lines)


def format_achievements(achievements: Iterable[dict[str, Any]]) -> str:
    items = list(achievements)
    if not items:
        return ""
    return "\n".join(
        ["🏆 本局新成就："]
        + [f"- {item['name']}：{item['description']}" for item in items]
    )


def chunk_trajectory(
    trajectory: Iterable[dict[str, Any]], max_chars: int = 2500
) -> list[str]:
    max_chars = max(500, int(max_chars))
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for item in trajectory:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        extra = len(text) + (1 if current else 0)
        if current and length + extra > max_chars:
            chunks.append("\n".join(current))
            current, length = [], 0
        if len(text) > max_chars:
            if current:
                chunks.append("\n".join(current))
                current, length = [], 0
            for start in range(0, len(text), max_chars):
                chunks.append(text[start : start + max_chars])
            continue
        current.append(text)
        length += extra
    if current:
        chunks.append("\n".join(current))
    return chunks


def profile_counts(profile: dict[str, str]) -> dict[str, int | None]:
    def parsed(key: str, default: Any) -> Any:
        try:
            return json.loads(profile.get(key, ""))
        except (TypeError, json.JSONDecodeError):
            return default

    return {
        "times": int(parsed("times", 0) or 0),
        "talents": len(parsed("ATLT", []) or []),
        "events": len(parsed("AEVT", []) or []),
        "achievements": len(parsed("ACHV", []) or []),
        "inherit": parsed("extendTalent", None),
    }
