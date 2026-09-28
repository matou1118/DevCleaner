# -*- coding: utf-8 -*-
"""扫一次真实数据，把统计数字写进 web/stats.json 供网页引用。

页面上写死 "2.02 GB" 的话，明天机器上多删一个缓存就对不上了 —— 数字必须
来自真实扫描。跑完这个脚本把 json 拷进 web/ 就行。

    python web/gen_stats.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as engine   # noqa: E402

SCAN_CN = {
    "已安装软件的安装包": ("Installers of already-installed software", "📦"),
    "传统垃圾文件": ("Traditional junk files", "🧹"),
    "过期临时文件": ("Stale temp files", "⏳"),
    "GitHub 残留": ("GitHub leftovers", "⚑"),
    "AI Agent / Skill 缓存": ("AI agent / skill caches", "🧰"),
    "更新器残留": ("Updater leftovers", "🔄"),
    "构建产物 / 开发垃圾": ("Build output / dev junk", "🧹"),
    "Python 环境与缓存": ("Python envs and caches", "🐍"),
    "空文件 / 空目录 / 断链": ("Empty files / empty dirs / broken links", "∅"),
    "未分类": ("Uncategorised", "●"),
}


def main() -> int:
    engine.run_scan()
    items = engine.STATE.items

    total = sum(i.size for i in items if getattr(i, "unit", "bytes") != "count")
    safe = sum(i.size for i in items
               if i.risk == "safe" and getattr(i, "unit", "bytes") != "count")
    caution = sum(i.size for i in items
                  if i.risk == "caution" and getattr(i, "unit", "bytes") != "count")
    n_count = sum(1 for i in items if getattr(i, "unit", "bytes") == "count")

    cats = []
    for cat, (en, icon) in SCAN_CN.items():
        rows = [i for i in items if i.category == cat]
        if not rows:
            continue
        b = sum(i.size for i in rows if getattr(i, "unit", "bytes") != "count")
        c = sum(1 for i in rows if getattr(i, "unit", "bytes") == "count")
        cats.append({
            "icon": icon,
            "zh": cat,
            "en": en,
            "count": len(rows),
            "bytes": b,
            "size_human": engine.human(b),
            "count_extra": c,
        })
    cats.sort(key=lambda d: -d["bytes"])

    data = {
        "version": engine.__version__,
        "scanned_at": engine.STATE.finished_at,
        "total": total,
        "total_human": engine.human(total),
        "safe_human": engine.human(safe),
        "caution_human": engine.human(caution),
        "scanners": len(engine.SCANNERS),
        "extra_by_count": n_count,
        "categories": cats,
    }
    out = ROOT / "web" / "stats.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"  total  {data['total_human']}  ({n_count} items counted per entry)")
    print(f"  cats   {len(cats)} with findings, {len(engine.SCANNERS)} scanners")
    for c in cats:
        print(f"    {c['icon']} {c['size_human']:>10}  {c['zh']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
