#!/usr/bin/env python3
"""更新 README.md 里的 PRLIST 标记区：已合并的公开 PR 列表。

用法：
    python scripts/generate_prlist.py Luckyou-d
    python scripts/generate_prlist.py Luckyou-d --out .
    GH_TOKEN=... python scripts/generate_prlist.py Luckyou-d

设计原则：
- 只替换 <!-- PRLIST:BEGIN --> 和 <!-- PRLIST:END --> 之间的内容；
- 找不到标记时直接跳过（exit 0），这样以后删掉文字列表不会弄坏 workflow；
- 网络/API 出错时退出码非 0，不修改 README，workflow 不会提交半截数据；
- 内容没变化时不写文件，避免每天产生空提交。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com/search/issues"
BEGIN = "<!-- PRLIST:BEGIN -->"
END = "<!-- PRLIST:END -->"


def gh_get(url: str, token: str | None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-profile-polish-prlist",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"GitHub API HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"GitHub API 连接失败: {e.reason}") from e


def fetch_merged_prs(user: str, token: str | None, max_pages: int) -> list[dict]:
    # 只统计提给他人的公开仓库，排除账号名下仓库，和贡献卡口径一致
    query = f"is:pr is:merged author:{user} is:public -user:{user}"
    items: list[dict] = []
    total = None
    for page in range(1, max_pages + 1):
        url = (
            f"{API}?q={urllib.parse.quote(query)}"
            f"&per_page=100&page={page}"
        )
        data = gh_get(url, token)
        total = data.get("total_count", 0)
        batch = data.get("items", [])
        items.extend(batch)
        if len(batch) < 100 or len(items) >= total:
            break
    if total is not None and len(items) < total:
        print(
            f"警告：API 返回 {len(items)} 条，少于 total_count={total}；"
            "可能触发分页上限，列表可能不完整。",
            file=sys.stderr,
        )
    return items


def render_list(items: list[dict]) -> str:
    if not items:
        return "- 暂无已合并的公开 PR。"

    def merged_at(item: dict) -> str:
        pr = item.get("pull_request") or {}
        return pr.get("merged_at") or item.get("closed_at") or ""

    items = sorted(items, key=merged_at, reverse=True)
    lines: list[str] = []
    for item in items:
        repo = (item.get("repository_url") or "").split("/repos/")[-1]
        number = item.get("number")
        title = (item.get("title") or "").replace("[", "\\[").replace("]", "\\]")
        url = item.get("html_url") or ""
        lines.append(f"- [{repo}#{number}]({url})：{title}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="更新 README 的 PRLIST 标记区")
    parser.add_argument("user", help="GitHub 用户名")
    parser.add_argument("--out", default=".", help="README.md 所在目录")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--token", help="GitHub token；默认读 GH_TOKEN / GITHUB_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = args.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    readme = Path(args.out) / "README.md"
    if not readme.exists():
        print(f"找不到 {readme}", file=sys.stderr)
        return 1

    text = readme.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print("未找到 PRLIST 标记，跳过（文字列表已关闭）。")
        return 0

    if text.count(BEGIN) != 1 or text.count(END) != 1:
        print("PRLIST 标记重复，拒绝猜测替换位置。", file=sys.stderr)
        return 1

    try:
        items = fetch_merged_prs(args.user, token, args.max_pages)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    block = render_list(items)
    new_text, count = re.subn(
        re.escape(BEGIN) + r".*?" + re.escape(END),
        BEGIN + "\n" + block + "\n" + END,
        text,
        flags=re.S,
    )
    if count != 1:
        print("替换 PRLIST 标记区失败。", file=sys.stderr)
        return 1

    if new_text == text:
        print(f"PRLIST 无变化（{len(items)} 个 PR）。")
        return 0

    if args.dry_run:
        print(new_text)
        return 0

    readme.write_text(new_text, encoding="utf-8")
    print(f"PRLIST 已更新：{len(items)} 个已合并 PR。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
