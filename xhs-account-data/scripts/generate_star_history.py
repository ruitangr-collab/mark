#!/usr/bin/env python3
"""Generate a self-hosted SVG stargazer history chart from GitHub."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPOSITORY = "white0dew/XiaohongshuSkills"
DEFAULT_OUTPUT = Path("assets/star-history.svg")
GITHUB_API_VERSION = "2022-11-28"
CHART_WIDTH = 960
CHART_HEIGHT = 360
CHART_LEFT = 76
CHART_RIGHT = 30
CHART_TOP = 58
CHART_BOTTOM = 62


def fetch_stargazers(repository: str, token: str) -> list[dict[str, object]]:
    """Return all stargazer events, including their timestamps."""
    events: list[dict[str, object]] = []
    page = 1

    while True:
        url = (
            f"https://api.github.com/repos/{repository}/stargazers"
            f"?per_page=100&page={page}"
        )
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github.star+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": "XiaohongshuSkills-star-history",
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub returned HTTP {error.code} while reading stargazers: {detail}"
            ) from error
        except URLError as error:
            raise RuntimeError(f"Could not reach the GitHub API: {error.reason}") from error

        if not isinstance(payload, list):
            raise RuntimeError("GitHub returned an unexpected stargazer response.")

        events.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            return events
        page += 1


def star_counts_by_day(events: list[dict[str, object]]) -> Counter[date]:
    """Collect stargazer events by their UTC calendar day."""
    counts: Counter[date] = Counter()
    for event in events:
        starred_at = event.get("starred_at")
        if not isinstance(starred_at, str):
            raise RuntimeError("GitHub did not provide a stargazer timestamp.")
        timestamp = datetime.fromisoformat(starred_at.replace("Z", "+00:00"))
        counts[timestamp.astimezone(timezone.utc).date()] += 1
    return counts


def cumulative_series(counts: Counter[date]) -> list[tuple[date, int]]:
    """Fill days without new stars so the graph renders as a continuous line."""
    if not counts:
        return [(date.today(), 0)]

    current_day = min(counts)
    final_day = max(date.today(), max(counts))
    total = 0
    series: list[tuple[date, int]] = []
    while current_day <= final_day:
        total += counts[current_day]
        series.append((current_day, total))
        current_day += timedelta(days=1)
    return series


def _svg_number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def render_svg(repository: str, series: list[tuple[date, int]]) -> str:
    """Render a compact, dependency-free line chart as an accessible SVG."""
    plot_width = CHART_WIDTH - CHART_LEFT - CHART_RIGHT
    plot_height = CHART_HEIGHT - CHART_TOP - CHART_BOTTOM
    total_stars = series[-1][1]
    max_stars = max(1, total_stars)

    def x_for(index: int) -> float:
        if len(series) == 1:
            return CHART_LEFT + plot_width / 2
        return CHART_LEFT + plot_width * index / (len(series) - 1)

    def y_for(value: int) -> float:
        return CHART_TOP + plot_height * (1 - value / max_stars)

    points = " ".join(
        f"{_svg_number(x_for(index))},{_svg_number(y_for(value))}"
        for index, (_, value) in enumerate(series)
    )
    first_x = _svg_number(x_for(0))
    last_x = _svg_number(x_for(len(series) - 1))
    baseline = _svg_number(CHART_TOP + plot_height)
    area_path = f"M {first_x} {baseline} L {points} L {last_x} {baseline} Z"

    grid_lines: list[str] = []
    for step in range(5):
        value = round(max_stars * step / 4)
        y = _svg_number(y_for(value))
        grid_lines.append(
            f'<line class="grid" x1="{CHART_LEFT}" y1="{y}" '
            f'x2="{CHART_WIDTH - CHART_RIGHT}" y2="{y}" />'
        )
        grid_lines.append(
            f'<text class="axis-label" x="{CHART_LEFT - 12}" y="{y}" '
            f'text-anchor="end" dominant-baseline="middle">{value}</text>'
        )

    date_labels: list[str] = []
    last_index = len(series) - 1
    for step in range(5):
        index = round(last_index * step / 4)
        day = series[index][0]
        date_labels.append(
            f'<text class="axis-label" x="{_svg_number(x_for(index))}" '
            f'y="{CHART_HEIGHT - 24}" text-anchor="middle">{day:%Y-%m}</text>'
        )

    safe_repository = escape(repository)
    generated_at = datetime.now(timezone.utc).date().isoformat()
    final_x = _svg_number(x_for(last_index))
    final_y = _svg_number(y_for(total_stars))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CHART_WIDTH}" height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" aria-labelledby="title description">
  <title id="title">Star history for {safe_repository}</title>
  <desc id="description">{total_stars} GitHub stars as of {generated_at}.</desc>
  <style>
    .title {{ fill: #111827; font: 600 20px system-ui, sans-serif; }}
    .subtitle {{ fill: #6b7280; font: 13px system-ui, sans-serif; }}
    .axis-label {{ fill: #6b7280; font: 12px system-ui, sans-serif; }}
    .grid {{ stroke: #e5e7eb; stroke-width: 1; }}
  </style>
  <rect width="100%" height="100%" fill="#ffffff" rx="8" />
  <text class="title" x="{CHART_LEFT}" y="30">Star history</text>
  <text class="subtitle" x="{CHART_WIDTH - CHART_RIGHT}" y="30" text-anchor="end">{total_stars} stars</text>
  {''.join(grid_lines)}
  <path d="{area_path}" fill="#fecdd3" opacity="0.65" />
  <polyline points="{points}" fill="none" stroke="#e11d48" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="{final_x}" cy="{final_y}" r="4.5" fill="#e11d48" />
  {''.join(date_labels)}
  <text class="subtitle" x="{CHART_WIDTH - CHART_RIGHT}" y="{CHART_HEIGHT - 7}" text-anchor="end">Updated {generated_at} UTC</text>
</svg>
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the repository's self-hosted star history SVG."
    )
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help="GitHub owner/repository")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output SVG path (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required to read dated stargazer events.")

    events = fetch_stargazers(args.repo, token)
    counts = star_counts_by_day(events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_svg(args.repo, cumulative_series(counts)), encoding="utf-8")
    print(f"Wrote {args.output} from {len(events)} stargazer events.")


if __name__ == "__main__":
    main()
