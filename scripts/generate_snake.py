"""Generate an animated SVG of a smart, tail-growing Snake AI eating GitHub contributions."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import urllib.request
from collections import deque
from pathlib import Path

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""

LEVEL_MAP = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

THEMES = {
    "light": {
        "bg": "#ffffff",
        "board_bg": "#f6f8fa",
        "board_border": "#d0d7de",
        "hud_bg": "#eef2ff",
        "hud_border": "#c7d2fe",
        "text_main": "#1f2328",
        "text_muted": "#59636e",
        "empty": "#ebedf0",
        "empty_stroke": "#1b1f230f",
        "c1": "#9be9a8",
        "c2": "#40c463",
        "c3": "#30a14e",
        "c4": "#216e39",
        "head": "#2563eb",
        "head_eye": "#ffffff",
        "pupil": "#0f172a",
        "s0": "#38bdf8",
        "s1": "#3b82f6",
        "s2": "#6366f1",
        "s3": "#8b5cf6",
        "flash": "#f59e0b",
        "accent": "#3b82f6",
        "accent2": "#8b5cf6",
    },
    "dark": {
        "bg": "#0d1117",
        "board_bg": "#0d1117",
        "board_border": "#30363d",
        "hud_bg": "#161b22",
        "hud_border": "#30363d",
        "text_main": "#e6edf3",
        "text_muted": "#8b949e",
        "empty": "#161b22",
        "empty_stroke": "#ffffff0d",
        "c1": "#0e4429",
        "c2": "#006d32",
        "c3": "#26a641",
        "c4": "#39d353",
        "head": "#38bdf8",
        "head_eye": "#0d1117",
        "pupil": "#ffffff",
        "s0": "#38bdf8",
        "s1": "#3b82f6",
        "s2": "#6366f1",
        "s3": "#8b5cf6",
        "flash": "#fbbf24",
        "accent": "#38bdf8",
        "accent2": "#a78bfa",
    },
}


def fetch_contributions(username: str, token: str | None) -> tuple[int, int, dict[tuple[int, int], int]]:
    """Fetch (width, height, {(col, row): level}) via GraphQL or public HTML fallback."""
    if token:
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": username}}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "snake-ai-svg",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        grid: dict[tuple[int, int], int] = {}
        for col, week in enumerate(weeks):
            for day in week["contributionDays"]:
                dt = datetime.date.fromisoformat(day["date"])
                row = (dt.weekday() + 1) % 7
                grid[(col, row)] = LEVEL_MAP.get(day["contributionLevel"], 0)
        return len(weeks), 7, grid

    url = f"https://github.com/users/{username}/contributions"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8")

    tds = re.findall(r'<td[^>]*data-date="([^"]+)"[^>]*data-level="(\d+)"[^>]*>', html)
    if not tds:
        tds = [(d, l) for l, d in re.findall(r'<td[^>]*data-level="(\d+)"[^>]*data-date="([^"]+)"[^>]*>', html)]

    parsed = []
    for d_str, lv_str in tds:
        dt = datetime.date.fromisoformat(d_str)
        row = (dt.weekday() + 1) % 7
        parsed.append((dt, row, int(lv_str)))
    parsed.sort(key=lambda item: item[0])

    first_sun = parsed[0][0] - datetime.timedelta(days=parsed[0][1])
    grid = {}
    for dt, row, lv in parsed:
        col = (dt - first_sun).days // 7
        grid[(col, row)] = lv
    width = max(c for c, _ in grid) + 1
    return width, 7, grid


def neighbors(pos: tuple[int, int], width: int, height: int):
    x, y = pos
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            yield (nx, ny)


def bfs_dist(start: tuple[int, int], blocked: set[tuple[int, int]], width: int, height: int):
    dist = {start: 0}
    parent: dict[tuple[int, int], tuple[int, int]] = {}
    q = deque([start])
    while q:
        u = q.popleft()
        for v in neighbors(u, width, height):
            if v not in blocked and v not in dist:
                dist[v] = dist[u] + 1
                parent[v] = u
                q.append(v)
    return dist, parent


def reconstruct_path(parent: dict[tuple[int, int], tuple[int, int]], start: tuple[int, int], target: tuple[int, int]):
    cur = target
    path = []
    while cur != start:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    return path


def can_reach_tail(sim_snake: list[tuple[int, int]], width: int, height: int) -> bool:
    head = sim_snake[0]
    tail = sim_snake[-1]
    blocked = set(sim_snake[:-1])
    dist, _ = bfs_dist(head, blocked, width, height)
    return tail in dist


def pick_start_snake(width: int, height: int, foods: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """Pick 3 connected empty cells near top-left (or left edge) so all food is visible."""
    for x in range(width - 2):
        for y in range(height):
            cand = [(x + 2, y), (x + 1, y), (x, y)]
            if all(p not in foods for p in cand):
                return cand
    return [(2, 0), (1, 0), (0, 0)]


def simulate_snake(width: int, height: int, grid: dict[tuple[int, int], int]):
    """Run smart A*/BFS + tail-reachability Snake AI eating all green cells with 1:1 growth."""
    foods = {pos for pos, lv in grid.items() if lv > 0}
    snake = pick_start_snake(width, height, foods)
    rem_foods = set(foods) - set(snake)
    eaten_at: dict[tuple[int, int], int] = {p: 0 for p in (set(foods) & set(snake))}
    history = [list(snake)]

    # Track exact interval [t_enter, t_leave] for each cell visit
    # Initial 3 segments entered at t=0
    active_visits: dict[tuple[int, int], int] = {pos: 0 for pos in snake}
    visit_intervals: list[tuple[tuple[int, int], int, int, tuple[int, int] | None]] = []
    # Also track step-by-step cell successor for seamless bridges: (pos, next_pos, t_bridge_on, t_leave_pos)
    cell_next_at_enter: dict[tuple[int, int], tuple[int, tuple[int, int] | None]] = {}
    for idx in range(len(snake)):
        nxt = snake[idx - 1] if idx > 0 else None
        cell_next_at_enter[snake[idx]] = (0, nxt)

    step = 0
    max_steps = 4500
    while rem_foods and step < max_steps:
        step += 1
        head = snake[0]
        blocked = set(snake[:-1])  # tail cell vacates unless we eat on the step entering it

        dist, parent = bfs_dist(head, blocked, width, height)
        # Prefer nearest reachable food (tie-break: keep horizontal sweep compact)
        candidates = [
            (dist[f], -grid[f], f[0], f[1], f)
            for f in rem_foods
            if f in dist
        ]
        candidates.sort()

        chosen_next = None
        for _, _, _, _, target in candidates[:18]:
            path = reconstruct_path(parent, head, target)
            sim = list(snake)
            for p in path:
                ate_p = p in rem_foods
                sim = [p] + (sim if ate_p else sim[:-1])
            if can_reach_tail(sim, width, height):
                chosen_next = path[0]
                break

        if chosen_next is None:
            # Tail-safety fallback: pick reachable neighbor that preserves tail reachability + max flood area
            best_score = -1
            for nb in neighbors(head, width, height):
                if nb in blocked:
                    continue
                ate_nb = nb in rem_foods
                sim = [nb] + (snake if ate_nb else snake[:-1])
                if can_reach_tail(sim, width, height):
                    d_tail, _ = bfs_dist(nb, set(sim[:-1]), width, height)
                    score = len(d_tail) * 1000 + d_tail.get(sim[-1], 0)
                    if score > best_score:
                        best_score = score
                        chosen_next = nb

        if chosen_next is None:
            # Emergency non-body move if parity corner occurs
            for nb in neighbors(head, width, height):
                if nb not in set(snake[:-1]):
                    chosen_next = nb
                    break

        if chosen_next is None:
            break

        ate = chosen_next in rem_foods
        old_tail = snake[-1]

        # Old head now connects forward to chosen_next
        if not ate:
            # old_tail vacates at `step`
            t_in = active_visits.pop(old_tail)
            _, nxt_from_tail = cell_next_at_enter.pop(old_tail)
            visit_intervals.append((old_tail, t_in, step, nxt_from_tail))
            snake = [chosen_next] + snake[:-1]
        else:
            snake = [chosen_next] + snake
            rem_foods.remove(chosen_next)
            eaten_at[chosen_next] = step

        # Update old head's forward neighbor to chosen_next
        t_in_head, _ = cell_next_at_enter[head]
        cell_next_at_enter[head] = (t_in_head, chosen_next)

        active_visits[chosen_next] = step
        cell_next_at_enter[chosen_next] = (step, None)
        history.append(list(snake))

    total_moves = step
    pause_steps = max(35, int(total_moves * 0.07))
    total_frames = total_moves + pause_steps

    # Flush remaining body segments at end of animation loop
    end_snake = history[-1]
    end_rank = {pos: i for i, pos in enumerate(end_snake)}
    for pos, t_in in active_visits.items():
        _, nxt = cell_next_at_enter[pos]
        visit_intervals.append((pos, t_in, total_frames, nxt, end_rank.get(pos, 0)))

    # Normalize non-final visits to 5-tuple (pos, t_in, t_out, nxt, end_rank_or_None)
    normalized_visits = []
    for item in visit_intervals:
        if len(item) == 4:
            normalized_visits.append((*item, None))
        else:
            normalized_visits.append(item)

    return {
        "foods": foods,
        "eaten_at": eaten_at,
        "history": history,
        "visit_intervals": normalized_visits,
        "total_moves": total_moves,
        "total_frames": total_frames,
    }


def pct(frame: float, total: int) -> str:
    return f"{min(100.0, max(0.0, (frame / total) * 100.0)):.3f}".rstrip("0").rstrip(".") + "%"


def build_svg(
    width: int,
    height: int,
    grid: dict[tuple[int, int], int],
    sim: dict,
    theme_name: str,
    step_ms: int = 55,
) -> str:
    t = THEMES[theme_name]
    cell = 11
    gap = 4
    pitch = cell + gap
    ox = 22
    oy = 46

    svg_w = ox * 2 + width * pitch - gap
    svg_h = oy + height * pitch - gap + 20

    total_moves = sim["total_moves"]
    total_frames = sim["total_frames"]
    dur_ms = total_frames * step_ms
    history = sim["history"]
    eaten_at = sim["eaten_at"]
    total_foods = len(sim["foods"])

    css: list[str] = []
    css.append(
        f"""
        .bg {{ fill: {t['bg']}; }}
        .board {{ fill: {t['board_bg']}; stroke: {t['board_border']}; stroke-width: 1; }}
        .hud {{ fill: {t['hud_bg']}; stroke: {t['hud_border']}; stroke-width: 1; }}
        .txt {{ font-family: ui-monospace, 'Cascadia Code', 'Fira Code', Menlo, Consolas, monospace; fill: {t['text_main']}; }}
        .muted {{ font-family: ui-monospace, 'Cascadia Code', 'Fira Code', Menlo, Consolas, monospace; fill: {t['text_muted']}; }}
        .cell0 {{ fill: {t['empty']}; stroke: {t['empty_stroke']}; stroke-width: 1; }}
        .food {{ stroke: {t['empty_stroke']}; stroke-width: 1; animation: none {dur_ms}ms steps(1, end) infinite; }}
        .seg {{ opacity: 0; animation: none {dur_ms}ms steps(1, end) infinite; }}
        .head {{ animation: headMove {dur_ms}ms steps(1, end) infinite; transform-box: fill-box; transform-origin: center; }}
        .hud-step {{ opacity: 0; animation: none {dur_ms}ms steps(1, end) infinite; }}
        .prog {{ transform-box: fill-box; transform-origin: left center; animation: progFill {dur_ms}ms linear infinite; }}
        .pulse {{ fill: none; stroke: {t['flash']}; stroke-width: 1.5; opacity: 0; animation: none {dur_ms}ms ease-out infinite; }}
        """.strip()
    )

    # 1. Grid cells (static level-0 + animated food cells)
    food_rects: list[str] = []
    empty_rects: list[str] = []
    pulse_rects: list[str] = []
    for c in range(width):
        for r in range(height):
            lv = grid.get((c, r), 0)
            x = ox + c * pitch
            y = oy + r * pitch
            if lv == 0:
                empty_rects.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" class="cell0"/>')
            else:
                fc = t[f"c{lv}"]
                t_eat = eaten_at.get((c, r))
                if t_eat is not None:
                    fid = f"f_{c}_{r}"
                    p_eat = pct(t_eat, total_frames)
                    p_flash_end = pct(min(total_frames, t_eat + 2), total_frames)
                    css.append(
                        f"@keyframes {fid}{{0%{{fill:{fc}}} {p_eat}{{fill:{t['flash']}}} {p_flash_end},100%{{fill:{t['empty']}}}}}"
                    )
                    food_rects.append(
                        f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" class="food" style="fill:{fc};animation-name:{fid}"/>'
                    )
                    pid = f"p_{c}_{r}"
                    p_end = pct(min(total_frames, t_eat + 5), total_frames)
                    css.append(
                        f"@keyframes {pid}{{0%,{p_eat}{{opacity:0;transform:scale(1)}} {pct(t_eat+0.2,total_frames)}{{opacity:.95;transform:scale(1.35)}} {p_end},100%{{opacity:0;transform:scale(1.85)}}}}"
                    )
                    pulse_rects.append(
                        f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" class="pulse" style="transform-box:fill-box;transform-origin:center;animation-name:{pid}"/>'
                    )
                else:
                    food_rects.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" fill="{fc}"/>')

    # 2. Connected snake body visits + bridges
    seg_elems: list[str] = []
    end_len = max(1, len(history[-1]) - 1)
    for idx, (pos, t_in, t_out, nxt, end_rk) in enumerate(sim["visit_intervals"]):
        c, r = pos
        x = ox + c * pitch
        y = oy + r * pitch
        p0 = pct(t_in, total_frames)
        p_end = pct(t_out, total_frames)

        if end_rk is not None:
            # Segment stays visible through victory pause: shade by final rank along body
            frac = end_rk / end_len
            end_color = t["s0"] if frac < 0.2 else (t["s1"] if frac < 0.5 else (t["s2"] if frac < 0.8 else t["s3"]))
            p_freeze = pct(max(t_in + 1, total_moves), total_frames)
            vid = f"v{idx}"
            if t_in == 0:
                kf = f"@keyframes {vid}{{0%{{opacity:1;fill:{t['s1']}}} {p_freeze},100%{{opacity:1;fill:{end_color}}}}}"
            else:
                kf = (
                    f"@keyframes {vid}{{0%{{opacity:0}} {p0}{{opacity:1;fill:{t['s0']}}} "
                    f"{p_freeze},100%{{opacity:1;fill:{end_color}}}}}"
                )
        else:
            span = max(1, t_out - t_in)
            p1 = pct(t_in + span * 0.18, total_frames)
            p2 = pct(t_in + span * 0.45, total_frames)
            p3 = pct(t_in + span * 0.72, total_frames)
            vid = f"v{idx}"
            if t_in == 0:
                kf = f"@keyframes {vid}{{0%{{opacity:1;fill:{t['s1']}}} {p2}{{fill:{t['s2']}}} {p3}{{fill:{t['s3']}}} {p_end},100%{{opacity:0}}}}"
            else:
                kf = (
                    f"@keyframes {vid}{{0%{{opacity:0}} {p0}{{opacity:1;fill:{t['s0']}}} "
                    f"{p1}{{fill:{t['s1']}}} {p2}{{fill:{t['s2']}}} {p3}{{fill:{t['s3']}}} {p_end},100%{{opacity:0}}}}"
                )
        css.append(kf)
        seg_elems.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" class="seg" style="animation-name:{vid}"/>')

        # Bridge to successor cell (starts when successor enters, ends when this cell leaves)
        if nxt is not None:
            nc, nr = nxt
            if t_in == 0 and pos in history[0] and nxt in history[0]:
                bt_in = 0
            else:
                bt_in = t_in + 1
            if bt_in < t_out:
                if nr == r:  # horizontal bridge
                    bx = min(c, nc) * pitch + ox + cell - 1
                    by = r * pitch + oy + 1
                    bw = gap + 2
                    bh = cell - 2
                else:  # vertical bridge
                    bx = c * pitch + ox + 1
                    by = min(r, nr) * pitch + oy + cell - 1
                    bw = cell - 2
                    bh = gap + 2
                bid = f"b{idx}"
                bp0 = pct(bt_in, total_frames)
                if end_rk is not None:
                    frac = end_rk / end_len
                    end_color = t["s0"] if frac < 0.2 else (t["s1"] if frac < 0.5 else (t["s2"] if frac < 0.8 else t["s3"]))
                    p_freeze = pct(max(bt_in + 1, total_moves), total_frames)
                    if bt_in == 0:
                        bkf = f"@keyframes {bid}{{0%{{opacity:1;fill:{t['s1']}}} {p_freeze},100%{{opacity:1;fill:{end_color}}}}}"
                    else:
                        bkf = f"@keyframes {bid}{{0%{{opacity:0}} {bp0}{{opacity:1;fill:{t['s0']}}} {p_freeze},100%{{opacity:1;fill:{end_color}}}}}"
                else:
                    bp1 = pct(bt_in + max(1, t_out - bt_in) * 0.25, total_frames)
                    bp2 = pct(bt_in + max(1, t_out - bt_in) * 0.6, total_frames)
                    if bt_in == 0:
                        bkf = f"@keyframes {bid}{{0%{{opacity:1;fill:{t['s1']}}} {bp1}{{fill:{t['s2']}}} {bp2}{{fill:{t['s3']}}} {p_end},100%{{opacity:0}}}}"
                    else:
                        bkf = f"@keyframes {bid}{{0%{{opacity:0}} {bp0}{{opacity:1;fill:{t['s0']}}} {bp1}{{fill:{t['s1']}}} {bp2}{{fill:{t['s2']}}} {p_end},100%{{opacity:0}}}}"
                css.append(bkf)
                seg_elems.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="1.5" class="seg" style="animation-name:{bid}"/>')

    # 3. Snake Head movement + directional rotation
    head_kf_parts: list[str] = []
    prev_tx, prev_ty, prev_ang = None, None, None
    for f in range(len(history)):
        hx, hy = history[f][0]
        nx, ny = history[f][1]
        dx, dy = hx - nx, hy - ny
        ang = 0 if dx == 1 else (180 if dx == -1 else (90 if dy == 1 else -90))
        tx = ox + hx * pitch
        ty = oy + hy * pitch
        if (tx, ty, ang) != (prev_tx, prev_ty, prev_ang):
            head_kf_parts.append(f"{pct(f, total_frames)}{{transform:translate({tx}px,{ty}px) rotate({ang}deg)}}")
            prev_tx, prev_ty, prev_ang = tx, ty, ang
    head_kf_parts.append(f"100%{{transform:translate({prev_tx}px,{prev_ty}px) rotate({prev_ang}deg)}}")
    css.append("@keyframes headMove{" + " ".join(head_kf_parts) + "}")

    # 4. Live HUD Score, Length, and Progress Bar
    events = sorted((t_eat, pos) for pos, t_eat in eaten_at.items())
    # Deduplicate same-step events if any
    hud_frames: list[tuple[int, int, int]] = [(0, 0, len(history[0]))]
    score = 0
    for t_eat, _ in events:
        if t_eat == 0:
            score += 1
            hud_frames[0] = (0, score, len(history[0]))
        else:
            score += 1
            hud_frames.append((t_eat, score, len(history[t_eat])))

    hud_elems: list[str] = []
    prog_kf_parts: list[str] = []
    for i, (f_start, sc, ln) in enumerate(hud_frames):
        f_end = hud_frames[i + 1][0] if i + 1 < len(hud_frames) else total_frames
        hid = f"h{i}"
        if f_start == 0:
            css.append(f"@keyframes {hid}{{0%{{opacity:1}} {pct(f_end, total_frames)},100%{{opacity:0}}}}")
        elif i == len(hud_frames) - 1:
            css.append(f"@keyframes {hid}{{0%{{opacity:0}} {pct(f_start, total_frames)},100%{{opacity:1}}}}")
        else:
            css.append(f"@keyframes {hid}{{0%{{opacity:0}} {pct(f_start, total_frames)}{{opacity:1}} {pct(f_end, total_frames)},100%{{opacity:0}}}}")

        done_tag = " | WIN!" if sc == total_foods else ""
        hud_elems.append(
            f'<text x="{svg_w - 34}" y="25" text-anchor="end" font-size="11" font-weight="700" class="txt hud-step" style="animation-name:{hid}">'
            f'SCORE {sc:03d}/{total_foods:03d} | LEN {ln:03d}{done_tag}</text>'
        )
        prog_kf_parts.append(f"{pct(f_start, total_frames)}{{transform:scaleX({max(0.02, sc / max(1, total_foods)):.3f})}}")

    prog_kf_parts.append("100%{transform:scaleX(1)}")
    css.append("@keyframes progFill{" + " ".join(prog_kf_parts) + "}")

    hud_w = svg_w - 44
    board_w = width * pitch - gap + 16
    board_h = height * pitch - gap + 16

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" width="{svg_w}" height="{svg_h}">
  <title>Contribution Snake AI ({total_foods} green cells eaten, length {len(history[0])} to {len(history[-1])})</title>
  <defs>
    <linearGradient id="hudGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{t['accent']}"/>
      <stop offset="100%" stop-color="{t['accent2']}"/>
    </linearGradient>
  </defs>
  <style>
{chr(10).join(css)}
  </style>
  <rect x="0" y="0" width="{svg_w}" height="{svg_h}" rx="12" class="bg"/>
  <rect x="22" y="8" width="{hud_w}" height="26" rx="7" class="hud"/>
  <circle cx="36" cy="21" r="4" fill="url(#hudGrad)"/>
  <text x="47" y="25" font-size="11" font-weight="700" class="txt">SNAKE AI</text>
  <text x="110" y="25" font-size="10.5" class="muted">BFS Shortest-Path + Tail-Safety | 1:1 Growth</text>
  <rect x="{svg_w - 435}" y="17" width="150" height="8" rx="4" fill="{t['empty']}"/>
  <rect x="{svg_w - 435}" y="17" width="150" height="8" rx="4" fill="url(#hudGrad)" class="prog"/>
  {''.join(hud_elems)}
  <rect x="{ox - 8}" y="{oy - 8}" width="{board_w}" height="{board_h}" rx="8" class="board"/>
  <g id="grid">
    {''.join(empty_rects)}
    {''.join(food_rects)}
  </g>
  <g id="snake-body">
    {''.join(seg_elems)}
  </g>
  <g id="fx">
    {''.join(pulse_rects)}
  </g>
  <g class="head">
    <rect x="-1" y="-1" width="{cell + 2}" height="{cell + 2}" rx="4" fill="{t['head']}"/>
    <circle cx="9.2" cy="3.2" r="2.1" fill="{t['head_eye']}"/>
    <circle cx="9.2" cy="7.8" r="2.1" fill="{t['head_eye']}"/>
    <circle cx="9.8" cy="3.2" r="1.0" fill="{t['pupil']}"/>
    <circle cx="9.8" cy="7.8" r="1.0" fill="{t['pupil']}"/>
  </g>
</svg>
"""
    return svg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER", "TedXpro"))
    parser.add_argument("--out-dir", default="dist")
    parser.add_argument("--step-ms", type=int, default=45)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    width, height, grid = fetch_contributions(args.user, token)
    sim = simulate_snake(width, height, grid)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    light_svg = build_svg(width, height, grid, sim, "light", step_ms=args.step_ms)
    dark_svg = build_svg(width, height, grid, sim, "dark", step_ms=args.step_ms)

    (out_dir / "github-snake.svg").write_text(light_svg, encoding="utf-8")
    (out_dir / "github-snake-dark.svg").write_text(dark_svg, encoding="utf-8")

    print(
        f"Generated Snake AI SVGs for {args.user}: "
        f"foods={len(sim['foods'])}, eaten={len(sim['eaten_at'])}, "
        f"steps={sim['total_moves']}, len={len(sim['history'][0])}->{len(sim['history'][-1])}, "
        f"light={len(light_svg)/1024:.1f}KB, dark={len(dark_svg)/1024:.1f}KB"
    )


if __name__ == "__main__":
    main()
