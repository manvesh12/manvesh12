#!/usr/bin/env python3
"""Draw a self-contained GitHub profile from GitHub's GraphQL API.

The scheduled workflow needs only Python's standard library. Generated SVGs use
no remote fonts, cards, trackers, or other runtime dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com/graphql"
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
WIDTH = 620
LEFT = 34
REVEAL = 1.25
RAMP = [" ", ":", "+", "#", "@"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date weekday } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 privacy: PUBLIC) {
      nodes {
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

LIGHT = dict(data="#59636e", emph="#7a263a", dim="#8c959f",
             rule="#d8dee4", surface="#ffffff")
DARK = dict(data="#c9d1d9", emph="#ff9eb1", dim="#8b949e",
            rule="#30363d", surface="#0d1117")


def contribution_window() -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    return (f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z")


def fetch(login: str, token: str) -> dict:
    start, end = contribution_window()
    body = json.dumps({"query": QUERY, "variables": {
        "login": login, "from": start, "to": end}}).encode()
    request = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": f"{login}-profile-generator"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL errors: {payload['errors']}")
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise SystemExit(f"No GitHub user found for {login!r}")
    return user


def pretty(iso_date: str) -> str:
    value = date.fromisoformat(iso_date)
    return f"{MONTHS[value.month - 1]} {value.day}"


def calculate_streaks(days: list[dict]) -> tuple[dict, dict]:
    best = dict(length=0, start=None, end=None)
    length, started = 0, None
    for day in days:
        if day["contributionCount"] > 0:
            length += 1
            started = started or day["date"]
            if length > best["length"]:
                best = dict(length=length, start=started, end=day["date"])
        else:
            length, started = 0, None

    current = dict(length=0, start=None, end=None)
    tail = days[:-1] if days and days[-1]["contributionCount"] == 0 else days
    for day in reversed(tail):
        if day["contributionCount"] == 0:
            break
        current["length"] += 1
        current["start"] = day["date"]
        current["end"] = current["end"] or day["date"]
    return current, best


def rank_languages(repositories: list[dict]) -> tuple[list, list]:
    by_bytes: dict[str, int] = {}
    by_repo: dict[str, int] = {}
    for repository in repositories:
        edges = (repository.get("languages") or {}).get("edges") or []
        for edge in edges:
            name = edge["node"]["name"]
            by_bytes[name] = by_bytes.get(name, 0) + edge["size"]
        if edges:
            primary = edges[0]["node"]["name"]
            by_repo[primary] = by_repo.get(primary, 0) + 1

    def top(values: dict[str, int]) -> list[tuple[str, int]]:
        return sorted(values.items(), key=lambda item: (-item[1], item[0]))[:5]

    return top(by_bytes), top(by_repo)


def summarise(user: dict) -> dict:
    calendar = user["contributionsCollection"]["contributionCalendar"]
    weeks = [week["contributionDays"] for week in calendar["weeks"]]
    days = [day for week in weeks for day in week]
    weekly = [sum(day["contributionCount"] for day in week) for week in weeks]
    current, longest = calculate_streaks(days)
    by_bytes, by_repo = rank_languages(user["repositories"]["nodes"])
    return {
        "total": calendar["totalContributions"],
        "active": sum(day["contributionCount"] > 0 for day in days),
        "best_week": max(weekly) if weekly else 0,
        "weekly": weekly,
        "weeks": weeks,
        "current": current,
        "longest": longest,
        "by_bytes": by_bytes,
        "by_repo": by_repo,
    }


def css() -> str:
    def theme(colors: dict) -> str:
        return (f".data{{fill:{colors['data']}}}.data-stroke{{stroke:{colors['data']}}}"
                f".emph{{fill:{colors['emph']}}}.dim{{fill:{colors['dim']}}}"
                f".rule{{stroke:{colors['rule']}}}.surface{{stroke:{colors['surface']}}}")
    return (f"<style>{theme(LIGHT)}.wash{{fill:{LIGHT['data']};opacity:.12}}"
            f"@media(prefers-color-scheme:dark){{{theme(DARK)}"
            f".wash{{fill:{DARK['data']};opacity:.16}}}}</style>")


def svg_head(height: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
            f'height="{height}" viewBox="0 0 {WIDTH} {height}" fill="none" '
            f'font-family="{MONO}">{css()}')


def fade(delay: float, duration: float = .42) -> str:
    return (f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{delay:.2f}s" dur="{duration}s" fill="freeze"/>')


def label(x: float, y: float, value, size: float = 11, css_class: str = "dim",
          anchor: str = "start", extra: str = "") -> str:
    anchor_attr = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x}" y="{y}" class="{css_class}" font-size="{size}"'
            f'{anchor_attr}{extra}>{value}</text>')


def wipe(identifier: str, x: float, y: float, width: float, height: float,
         delay: float, duration: float = REVEAL) -> tuple[str, str]:
    clip = (f'<clipPath id="{identifier}"><rect x="{x}" y="{y}" '
            f'height="{height}" width="0"><animate attributeName="width" '
            f'from="0" to="{width}" begin="{delay:.2f}s" dur="{duration}s" '
            f'fill="freeze"/></rect></clipPath>')
    cursor = (f'<rect y="{y}" width="2" height="{height}" class="emph" opacity="0">'
              f'<animate attributeName="x" from="{x}" to="{x + width}" '
              f'begin="{delay:.2f}s" dur="{duration}s" fill="freeze"/>'
              f'<set attributeName="opacity" to=".7" begin="{delay:.2f}s"/>'
              f'<set attributeName="opacity" to="0" begin="{delay + duration:.2f}s"/>'
              f'</rect>')
    return clip, cursor


def draw_stats(summary: dict) -> str:
    height = 148
    weekly = summary["weekly"] or [0]
    peak = max(weekly) or 1
    parts = [svg_head(height)]
    parts.append(f'<g opacity="0">{fade(.08)}'
                 + label(0, 50, summary["total"], 52, "emph",
                         extra=' font-weight="700"')
                 + label(0, 72, "contributions in the last year", 12) + "</g>")
    for index, (value, caption) in enumerate(((summary["active"], "active days"),
                                               (summary["best_week"], "best week"))):
        parts.append(f'<g opacity="0">{fade(.28 + index * .12)}'
                     + label(WIDTH, 30 + index * 40, value, 19, "emph", "end",
                             ' font-weight="700"')
                     + label(WIDTH, 47 + index * 40, caption, 11, "dim", "end")
                     + "</g>")

    baseline, top = height - 10, height - 58
    step = WIDTH / max(len(weekly) - 1, 1)
    points = [(index * step, baseline - value / peak * (baseline - top))
              for index, value in enumerate(weekly)]
    clip, cursor = wipe("stats-reveal", 0, top - 6, WIDTH, baseline - top + 8, .48)
    parts.extend([clip, '<g clip-path="url(#stats-reveal)">'])
    parts.append(f'<path d="M{points[0][0]:.1f} {baseline:.1f}'
                 + "".join(f'L{x:.1f} {y:.1f}' for x, y in points)
                 + f'L{points[-1][0]:.1f} {baseline:.1f}Z" class="wash"/>')
    parts.append(f'<path d="M{points[0][0]:.1f} {points[0][1]:.1f}'
                 + "".join(f'L{x:.1f} {y:.1f}' for x, y in points[1:])
                 + '" class="data-stroke" stroke-width="2" stroke-linejoin="round" '
                   'stroke-linecap="round"/></g>')
    parts.append(cursor)
    end_x, end_y = points[-1]
    parts.append(f'<circle cx="{end_x - 2:.1f}" cy="{end_y:.1f}" r="4.5" '
                 f'class="emph surface" stroke-width="2" opacity="0">'
                 f'{fade(.48 + REVEAL, .3)}</circle></svg>')
    return "".join(parts)


def draw_streak(summary: dict) -> str:
    height = 96
    parts = [svg_head(height)]
    middle = WIDTH / 2
    parts.append(f'<line x1="{middle}" y1="16" x2="{middle}" y2="80" '
                 f'class="rule" opacity="0">{fade(.18)}</line>')
    for index, (key, caption) in enumerate((("current", "current streak"),
                                             ("longest", "longest streak"))):
        value = summary[key]
        span = (f"{pretty(value['start'])} &#8211; {pretty(value['end'])}"
                if value["length"] else "&#8212;")
        x = LEFT if index == 0 else middle + LEFT
        parts.append(f'<g opacity="0">{fade(.10 + index * .14)}'
                     + label(x, 44, value["length"], 34, "emph",
                             extra=' font-weight="700"')
                     + label(x, 64, caption, 11, "data")
                     + label(x, 80, span, 10) + "</g>")
    parts.append("</svg>")
    return "".join(parts)


def rounded_bar(x: float, y: float, width: float, height: float = 7) -> str:
    if width <= .6:
        return ""
    radius = min(3, height / 2, width)
    return (f'<path d="M{x:.1f} {y:.1f}H{x + width - radius:.1f}'
            f'Q{x + width:.1f} {y:.1f} {x + width:.1f} {y + radius:.1f}'
            f'V{y + height - radius:.1f}Q{x + width:.1f} {y + height:.1f} '
            f'{x + width - radius:.1f} {y + height:.1f}H{x:.1f}Z" class="data"/>')


def draw_languages(summary: dict) -> str:
    rows = max(len(summary["by_bytes"]), len(summary["by_repo"]), 1)
    height = 32 + rows * 22
    column_width = (WIDTH - LEFT - 30) / 2
    name_width, bar_width = 86, column_width - 86 - 42
    parts = [svg_head(height)]
    groups = ((LEFT, "BY BYTES", summary["by_bytes"], True),
              (LEFT + column_width + 30, "BY REPOS", summary["by_repo"], False))
    for group_index, (group_x, title, data, percentage) in enumerate(groups):
        parts.append(f'<g opacity="0">{fade(.08 + group_index * .1)}'
                     + label(group_x, 12, title, 9, "dim",
                             extra=' letter-spacing="1.3"') + "</g>")
        if not data:
            continue
        maximum = max(value for _, value in data) or 1
        total = sum(value for _, value in data) or 1
        clip_id = f"languages-{group_index}"
        clip, cursor = wipe(clip_id, group_x + name_width, 20, bar_width,
                            rows * 22, .32 + group_index * .12, .9)
        parts.append(clip)
        for row, (name, value) in enumerate(data):
            y = 26 + row * 22
            shown = f"{value / total * 100:.0f}%" if percentage else str(value)
            parts.append(f'<g opacity="0">{fade(.22 + group_index * .1 + row * .05)}'
                         + label(group_x, y + 8, name.lower()[:12], 11, "data")
                         + label(group_x + column_width - 6, y + 8, shown, 11,
                                 "dim", "end") + "</g>")
            parts.append(f'<g clip-path="url(#{clip_id})">'
                         + rounded_bar(group_x + name_width, y,
                                       bar_width * value / maximum) + "</g>")
        parts.append(cursor)
    parts.append("</svg>")
    return "".join(parts)


def draw_year(summary: dict) -> str:
    font_size, line_height, columns_per_week = 9.2, 11.0, 2
    char_width = font_size * .6
    top = 44
    weeks = summary["weeks"]
    height = int(top + 7 * line_height + 26)
    parts = [svg_head(height)]
    parts.append(f'<g opacity="0">{fade(.08)}'
                 + label(LEFT, 16, "THE YEAR", 9, "dim",
                         extra=' letter-spacing="1.3"')
                 + label(LEFT, 32, f"{summary['active']} of "
                         f"{sum(len(week) for week in weeks)} days had a contribution",
                         11, "data") + "</g>")
    parts.append(f'<g opacity="0">{fade(1.15)}'
                 + label(WIDTH - 84, 32, "less", 9, "dim", "end")
                 + f'<text xml:space="preserve" x="{WIDTH - 78}" y="32" '
                   f'class="data" font-size="{font_size}">{" ".join(RAMP[1:])}</text>'
                 + label(WIDTH - 6, 32, "more", 9, "dim", "end") + "</g>")

    def intensity(value: int) -> int:
        for index, cutoff in enumerate((0, 2, 5, 9)):
            if value <= cutoff:
                return index
        return 4

    for weekday in range(7):
        chars = []
        for week in weeks:
            day = next((item for item in week if item.get("weekday") == weekday), None)
            count = day["contributionCount"] if day else 0
            chars.append(RAMP[intensity(count)] * columns_per_week)
        line = "".join(chars).rstrip()
        if not line:
            continue
        y = top + weekday * line_height
        width = max(len(line), 1) * char_width
        clip_id = f"year-{weekday}"
        delay = .28 + weekday * .07
        safe = line.replace("&", "&amp;").replace("<", "&lt;")
        parts.append(f'<clipPath id="{clip_id}"><rect x="{LEFT}" y="{y}" '
                     f'height="{line_height}" width="0"><animate attributeName="width" '
                     f'from="0" to="{width:.1f}" begin="{delay:.2f}s" dur=".4s" '
                     f'fill="freeze"/></rect></clipPath><g clip-path="url(#{clip_id})">'
                     f'<text xml:space="preserve" x="{LEFT}" y="{y + font_size - .6:.1f}" '
                     f'class="data" font-size="{font_size}">{safe}</text></g>')
    for weekday, caption in ((1, "mon"), (3, "wed"), (5, "fri")):
        parts.append(label(LEFT - 7, top + weekday * line_height + font_size - .6,
                           caption, 9, "dim", "end"))
    last_month, last_x = None, -999.0
    label_y = top + 7 * line_height + 13
    for index, week in enumerate(weeks):
        month = int(week[0]["date"][5:7])
        x = LEFT + index * columns_per_week * char_width
        if month != last_month and index < len(weeks) - 1 and x - last_x >= 34:
            parts.append(label(x, label_y, MONTHS[month - 1], 9))
            last_x = x
        last_month = month
    parts.append("</svg>")
    return "".join(parts)


def draw_heading(title: str) -> str:
    font_size, height = 16, 26
    text_width = len(title) * font_size * .6
    rule_start = text_width + 18
    return (svg_head(height)
            + label(0, 18, title, font_size, "emph", extra=' font-weight="700"')
            + f'<line x1="{rule_start:.0f}" y1="12.5" x2="{WIDTH}" y2="12.5" '
              f'class="rule"/></svg>')


def generate(login: str, token: str) -> tuple[dict[str, str], dict]:
    summary = summarise(fetch(login, token))
    files = {
        "assets/stats.svg": draw_stats(summary),
        "assets/streak.svg": draw_streak(summary),
        "assets/langs.svg": draw_languages(summary),
        "assets/year.svg": draw_year(summary),
    }
    for title in ("about", "stack", "projects", "stats", "about this page"):
        slug = title.replace(" ", "-")
        files[f"assets/hd-{slug}.svg"] = draw_heading(title)
    return files, summary


def write_files(files: dict[str, str]) -> list[str]:
    changed = []
    for relative, content in files.items():
        target = ROOT / relative
        content = content.rstrip("\n") + "\n"
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        if old != content:
            target.write_text(content, encoding="utf-8", newline="\n")
            changed.append(relative)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-json", action="store_true",
                        help="print generated files as JSON instead of writing them")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")
    login = os.environ.get("GH_LOGIN", "manvesh12")
    files, summary = generate(login, token)
    if args.emit_json:
        print(json.dumps(files, ensure_ascii=False))
        return
    changed = write_files(files)
    print(f"{summary['total']} contributions · {summary['active']} active days · "
          f"current streak {summary['current']['length']} · "
          f"updated {', '.join(changed) if changed else 'nothing'}")


if __name__ == "__main__":
    main()
