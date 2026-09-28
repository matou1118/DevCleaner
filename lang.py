"""界面文案英译。

键就是中文原文 —— 中文模式原样返回，英文模式查表做子串替换。

为什么用子串替换而不是精确匹配：界面上的句子大量是运行期拼出来的，
「扫描 已安装软件的安装包」「确认清理 12 项，其中 1 项是注册表修改？」
没法穷举进表。表里只放词组，组合句自动拼，不用每种排列手写一遍。

替换按 key 长度从长到短，避免「项」先把「项按条目计」啃掉一半。
"""
from typing import Dict
import re as _re

LANG = "zh"

_EN: Dict[str, str] = {
    # ---- 计数 / 单位 ----
    "项": "items",
    "个条目": "entries",
    "个空文件 / 空目录 / 断链（逐条删除）":
        " empty files / empty dirs / broken links under the scan roots",
    "扫描根目录下匹配的": "Matched under scan roots: ",
    "另有 ": "plus ",
    "项按条目计": " more, counted per entry",
    "共 ": "Total ",
    "已选 ": "Selected ",
    "成功 ": "Succeeded: ",
    "未处理 ": "Not processed: ",
    "（已不存在）": " (no longer exists)",
    "（被进程占用）": " (locked by a running process)",

    # ---- 风险等级 ----
    "安全": "Safe",
    "需确认": "Needs review",
    "只读": "Read-only",
    "（只读）": " (read-only)",
    "可回收": "reclaimable",
    "不提供删除": "no deletion offered",
    "· 安全 ": " · safe ",

    # ---- 按钮 / 标签 ----
    "开始扫描": "Start scan",
    "扫描中…": "Scanning…",
    "重新扫描": "Rescan",
    "全部展开": "Expand all",
    "全部折叠": "Collapse all",
    "全选本组": "Select all",
    "清空本组": "Clear",
    "全选安全项": "Select safe",
    "清空选择": "Clear selection",
    "移入回收站": "Move to Recycle Bin",
    "日志": "Log",
    "隐藏日志": "Hide log",
    "主题": "Theme",
    "配色主题": "Colour theme",
    "语言": "Language",
    "合计": "Total",
    "安全可清": "Safe to clear",
    "待命": "Ready",
    "准备中": "Preparing",
    "正在扫描…": "Scanning…",
    "确认清理": "Clean up",
    "清理结果": "Cleanup result",
    "扫描": "Scan",
    "完成 · ": "Done · ",
    "完成": "Done",

    # ---- 标题 / 说明 ----
    "本地清理": "Local cleaner",
    "本地独立清理 · 所有条目移入 Windows 回收站，可恢复":
        "Standalone local cleaner · everything goes to the Recycle Bin, restorable",
    "点击「开始扫描」查找可清理项":
        "Click Start scan to find reclaimable items",
    "HKCU 下 10 个「资源管理器使用记录」键":
        "10 Explorer usage-history keys under HKCU",

    # ---- 确认框 ----
    "项，其中": " items, of which",
    "项是注册表修改？": " are registry changes?",
    "个条目，合计 ": " entries, totalling ",
    "是注册表修改": " are registry changes",
    "其中包含批量删除，请注意条目数。":
        " This includes bulk deletion - mind the entry count.",
    "文件类会移入回收站（可还原）。":
        "Files go to the Recycle Bin (restorable).\n",
    "注册表类会先备份 .reg 到": "Registry entries are backed up to",
    "再删除，导出失败则不会删除。还原方式：对备份目录里的 .reg 执行 reg import。":
        "before deletion; nothing is deleted if the export fails. "
        "To restore: run reg import on the .reg files in that folder.",
    "将移入 Windows 回收站，可在「回收站」中还原。":
        "These go to the Windows Recycle Bin; restore them from there.",
    "其中 ": "of which ",
    "项标记为「需确认」：": " flagged Needs review:",
    "注册表备份位置：": "Registry backups:",
    "文件已进入回收站，清空回收站后才会真正释放空间。":
        "Files are in the Recycle Bin - empty it to actually free disk space.",

    # ---- 扫描分类（app.py 的 Scanner.category）----
    "已安装软件的安装包": "Installers of already-installed software",
    "传统垃圾文件": "Traditional junk files",
    "过期临时文件": "Stale temp files",
    "GitHub 残留": "GitHub leftovers",
    "AI Agent / Skill 缓存": "AI agent / skill caches",
    "更新器残留": "Updater leftovers",
    "构建产物 / 开发垃圾": "Build output / dev junk",
    "Python 环境与缓存": "Python envs and caches",
    "未分类": "Uncategorised",
    "空文件 / 空目录 / 断链": "Empty files / empty dirs / broken links",
    "全局 npm 垃圾": "Global npm junk",
    "全局 npm 包": "Global npm packages",
    "Git 仓库": "Git repos",
    "注册表": "Registry",
    "可安全重置": "safe to reset",

    # ---- 全角标点 ----
    "，": ", ",
    "：": ": ",
    "？": "?",
    "（": " (",
    "）": ")",
    "、": ", ",
    "「": "",
    "」": "",
    "…": "...",
}

# 长 key 优先，否则「项」会先把「项按条目计」啃掉
_ORDERED = sorted(_EN, key=len, reverse=True)


def set_lang(code: str) -> None:
    global LANG
    LANG = code if code in ("zh", "en") else "zh"


def T(s: str) -> str:
    """把一段中文里的词组换成英文。中文模式下是恒等函数。"""
    if LANG != "en" or not s:
        return s
    for k in _ORDERED:
        if k in s:
            s = s.replace(k, _EN[k])
    # 「，」等标点译文自带空格，和原文残留的空格会叠成 "12  items"。
    # 合并多余空格，但别动换行（对话框要靠 \n 分段）。
    s = _re.sub(r"[ \t]{2,}", " ", s)
    return s


def missing() -> list:
    """表里用得上的词条（供自检核对覆盖情况）"""
    return [k for k, v in _EN.items() if not v.strip() or T(k) == k]
