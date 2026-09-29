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

    # ---- 确认对话框 ----
    "取消": "Cancel",
    "… 另有": "... plus",

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
    "移入备份目录": "Move to backup",
    "日志": "Log",
    "隐藏日志": "Hide log",
    "历史": "History",
    "清理历史（最近 200 行）": "Clean history (last 200 lines)",
    "暂无清理历史": "No clean history yet",
    "回滚": "Rollback",
    "暂无可回滚的备份": "No rollback backups available",
    "回滚选中会话": "Restore selected session",
    "回滚完成": "Rollback complete",
    "回滚结果": "Rollback result",
    "成功": "Success",
    "失败": "Failed",
    "清理预览": "Clean preview",
    "安全": "Safe",
    "需确认": "Caution",
    "回滚": "Rollback",
    "暂无可回滚的备份": "No rollback backups available",
    "回滚选中会话": "Restore selected session",
    "回滚完成": "Rollback complete",
    "回滚结果": "Rollback result",
    "成功": "Success",
    "失败": "Failed",
    "清理预览": "Clean preview",
    "安全": "Safe",
    "需确认": "Caution",
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
    "关闭": "Close",
    "扫描": "Scan",
    "完成 · ": "Done · ",
    "完成": "Done",

    # ---- 软件卸载 ----
    "软件卸载": "Uninstall",
    "搜索软件名称…": "Search software…",
    "软件名称": "Name",
    "发布者": "Publisher",
    "版本": "Version",
    "大小(MB)": "Size(MB)",
    "正在读取已安装软件列表…": "Reading installed software list…",
    "共": "Total",
    "款软件": "apps",
    "刷新列表": "Refresh",
    "运行卸载程序": "Run uninstaller",
    "提示": "Notice",
    "请先选择要卸载的软件": "Please select a software to uninstall first",
    "确认卸载": "Confirm uninstall",
    "即将运行卸载程序": "About to run the uninstaller for",
    "卸载完成后将自动扫描残留文件和注册表":
        "After uninstall, leftover files and registry entries will be scanned",
    "是否继续": "Continue?",
    "正在运行卸载程序，请等待完成…":
        "Running uninstaller, please wait until it finishes…",
    "卸载失败": "Uninstall failed",
    "正在扫描残留…": "Scanning for leftovers…",
    "卸载完成": "Uninstall complete",
    "卸载完成，无残留": "Uninstall complete, nothing left behind",
    "已删除项已备份，可通过「回滚」恢复":
        "Deleted items are backed up — restore them from Rollback.",
    "清理中…": "Cleaning…",
    "清选本组": "Clear selection in this group",
    "已卸载": "uninstalled",
    "未发现残留": "No leftovers found",
    "残留清理": "Leftover cleanup",
    "注册表残留": "Registry leftovers",
    "文件夹残留": "Folder leftovers",
    "快捷方式残留": "Shortcut leftovers",
    "文件夹和快捷方式可安全清理（已备份，可回滚）":
        "Folders and shortcuts can be safely cleaned (backed up, rollback available)",
    "注册表残留需手动确认，不会自动删除":
        "Registry leftovers require manual confirmation, not auto-deleted",
    "清理残留": "Clean leftovers",
    "跳过": "Skip",
    "正在清理…": "Cleaning…",
    "清理完成": "Cleanup complete",
    "已删除": "Deleted",
    "项需手动处理": " need manual handling",
    "残留清理结果": "Leftover cleanup result",
    "正在刷新…": "Refreshing…",
    "等": "etc.",
    "上次使用": "Last used",
    "闲置天数": "Idle days",
    "按闲置排序": "Sort by idle",
    "按名称排序": "Sort by name",
    "今天": "today",
    "天": " days",
    "未知": "unknown",

    # ---- 软件卸载 ----
    "软件卸载": "Uninstall",
    "搜索软件名称…": "Search software…",
    "软件名称": "Name",
    "发布者": "Publisher",
    "版本": "Version",
    "大小(MB)": "Size(MB)",
    "正在读取已安装软件列表…": "Reading installed software list…",
    "共": "Total",
    "款软件": "apps",
    "刷新列表": "Refresh",
    "运行卸载程序": "Run uninstaller",
    "提示": "Notice",
    "请先选择要卸载的软件": "Please select a software to uninstall first",
    "确认卸载": "Confirm uninstall",
    "即将运行卸载程序": "About to run the uninstaller for",
    "卸载完成后将自动扫描残留文件和注册表":
        "After uninstall, leftover files and registry entries will be scanned",
    "是否继续": "Continue?",
    "正在运行卸载程序，请等待完成…":
        "Running uninstaller, please wait until it finishes…",
    "卸载失败": "Uninstall failed",
    "正在扫描残留…": "Scanning for leftovers…",
    "卸载完成": "Uninstall complete",
    "已卸载": "uninstalled",
    "未发现残留": "No leftovers found",
    "残留清理": "Leftover cleanup",
    "注册表残留": "Registry leftovers",
    "文件夹残留": "Folder leftovers",
    "快捷方式残留": "Shortcut leftovers",
    "文件夹和快捷方式可安全清理（已备份，可回滚）":
        "Folders and shortcuts can be safely cleaned (backed up, rollback available)",
    "注册表残留需手动确认，不会自动删除":
        "Registry leftovers require manual confirmation, not auto-deleted",
    "清理残留": "Clean leftovers",
    "跳过": "Skip",
    "正在清理…": "Cleaning…",
    "清理完成": "Cleanup complete",
    "已删除": "Deleted",
    "项需手动处理": " need manual handling",
    "残留清理结果": "Leftover cleanup result",
    "正在刷新…": "Refreshing…",
    "等": "etc.",

    # ---- 标题 / 说明 ----
    "本地清理": "Local cleaner",
    "本地独立清理 · 文件先备份，7 天内可回滚":
        "Standalone cleaner · backed up, 7-day rollback",
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
    "文件类会先移入本地备份目录，7 天内可在「回滚」里还原。":
        "Files are moved to a local backup directory and can be restored from Rollback for 7 days.\n",
    "注册表类会先备份 .reg 到": "Registry entries are backed up to",
    "再删除，导出失败则不会删除。还原方式：对备份目录里的 .reg 执行 reg import。":
        "before deletion; nothing is deleted if the export fails. "
        "To restore: run reg import on the .reg files in that folder.",
    "将移入本地备份目录，可在「回滚」里还原。":
        "These are moved to a local backup directory; restore them from Rollback.",
    "其中 ": "of which ",
    "项标记为「需确认」：": " flagged Needs review:",
    "注册表备份位置：": "Registry backups:",
    "文件已移入备份目录，7 天后过期备份会自动清理。":
        "Files are in the backup directory; expired backups are purged after 7 days.",

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

    # ---- 署名 ----
    "GitHub": "GitHub",

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
