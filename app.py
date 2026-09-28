"""
DevCleaner - 本地独立清理工具
扫描引擎：纯标准库 + psutil + PyYAML，不含任何界面代码（界面见 gui.py）。
"""
__version__ = "0.1.0"
APP_NAME = "DevCleaner"
REPO_OWNER = "matou1118"
REPO_NAME = "DevCleaner"
REPO = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
# 界面上显示的署名。GitHub 用户名是全小写的 matou1118，但署名字首大写好看。
OWNER = "Matou1118"
import ctypes
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import winreg

# 控制台编码兜底：GitHub runner 是 cp1252，中文机器是 GBK，都编不了中文。
# 扫描结果的分类名全是中文，不设这个会 UnicodeEncodeError。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil
import yaml

# ============================ 数据模型 ============================


@dataclass
class Item:
    name: str
    category: str
    path: str
    size: int
    risk: str            # safe | caution
    meta: str = ""
    note: str = ""
    icon: str = ""
    unit: str = "bytes"  # bytes | count —— count 表示 size 是「条目数」不是字节


@dataclass
class Note:
    """只读提示，不提供删除"""
    name: str
    path: str
    size: int
    meta: str = ""
    kind: str = ""


@dataclass
class ScanState:
    running: bool = False
    progress: float = 0.0
    stage: str = "待命"
    log: List[str] = field(default_factory=list)
    items: List[Item] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)
    finished_at: str = ""

    def say(self, msg: str) -> None:
        self.log.append(msg)
        del self.log[:-200]


STATE = ScanState()


# ============================ 工具函数 ============================


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def expand(s: str) -> str:
    return os.path.expandvars(s).replace("/", "\\")


def app_dir() -> Path:
    """exe 所在目录（打包后）或脚本所在目录"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def resource(*parts: str) -> Path:
    """用户可改的文件优先取 exe 旁边的（便于改配置），没有就用打包内置的副本"""
    p = app_dir().joinpath(*parts)
    if p.exists():
        return p
    return Path(getattr(sys, "_MEIPASS", app_dir())).joinpath(*parts)


def load_settings() -> dict:
    p = resource("settings.yaml")
    if not p.exists():
        raise SystemExit(f"缺少配置文件: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw.setdefault("scan_roots", [])
    raw.setdefault("exclude_dirs", [])
    raw.setdefault("exclude_globs", [])
    raw.setdefault("custom_cache", [])
    raw.setdefault("scan_options", {})
    raw.setdefault("installed_aliases", {})
    raw.setdefault("folder_roots", [])
    raw.setdefault("min_installer_age_days", 14)
    return raw


CFG = load_settings()


def _in_dir(p: Path, parent: Path) -> bool:
    try:
        return os.path.normcase(str(p)).startswith(os.path.normcase(str(parent)) + os.sep)
    except (TypeError, ValueError):
        return False


_EXCL_CACHE: Tuple[Any, List[Path]] = (None, [])


def _excludes() -> List[Path]:
    """exclude_dirs 只解析一次 —— 每个目录都 Path.resolve() 是扫描慢的头号原因。
    缓存以配置内容为 key，配置一改就自动失效。"""
    global _EXCL_CACHE
    raw = CFG["exclude_dirs"]
    key = tuple(raw)
    if _EXCL_CACHE[0] != key:
        out = []
        for e in raw:
            p = Path(expand(e))
            try:
                p = p.resolve()
            except OSError:
                pass
            out.append(p)
        _EXCL_CACHE = (key, out)
    return _EXCL_CACHE[1]


def excluded(p: Path) -> bool:
    bases = _excludes()
    if any(_in_dir(p, b) for b in bases):
        return True
    for g in CFG["exclude_globs"]:
        core = g.replace("**/", "").replace("/**", "").strip("*")
        if core and (core in p.parts or fnmatch.fnmatch(p.name, core)):
            return True
    return False


def dir_size(path: Path) -> int:
    total = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def mtime(p: Path) -> str:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return "unknown"


def age_days(p: Path) -> int:
    try:
        return int((time.time() - p.stat().st_mtime) / 86400)
    except OSError:
        return 0


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(s: str) -> "_GUID":
    import uuid
    u = uuid.UUID(s)
    return _GUID(u.time_low, u.time_mid, u.time_hi_version,
                 (ctypes.c_ubyte * 8)(*u.bytes[8:]))


FOLDERID = {
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
}

# 已知文件夹可能压根没建过（Windows 返回 FILE_NOT_FOUND），也可能被人挪走。
# 以 "~" 开头的项表示「先解析出该角色的真实目录，再拼子目录」—— 因为
# Documents/Desktop 常被重定向到别的盘，直接用 %USERPROFILE%\Documents 会找不到。
FALLBACKS = {
    "Downloads": ["~Documents/Downloads", "%USERPROFILE%/Downloads"],
    "Desktop": ["%USERPROFILE%/Desktop", "~Documents/Desktop"],
    "Documents": ["%USERPROFILE%/Documents"],
}
_RESOLVED: Dict[str, List[Path]] = {}


def known_folders(role: str) -> List[Path]:
    """返回该角色下实际存在的目录；原生 API 优先（能正确解析重定向）"""
    if role in _RESOLVED:
        return list(_RESOLVED[role])
    out: List[Path] = []
    guid = FOLDERID.get(role)
    if guid:
        buf = ctypes.c_wchar_p()
        try:
            rc = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(_guid(guid)), 0, None, ctypes.byref(buf))
            if rc == 0 and buf.value:
                p = Path(expand(buf.value))
                if p.is_dir():
                    out.append(p)
        except (OSError, ValueError):
            pass
        finally:
            if buf:
                try:
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                except OSError:
                    pass
    for fb in FALLBACKS.get(role, []):
        if fb.startswith("~"):
            parent_role, _, sub = fb[1:].partition("/")
            for base in known_folders(parent_role):
                p = base / sub
                if p.is_dir() and p not in out:
                    out.append(p)
        else:
            p = Path(expand(fb))
            if p.is_dir() and p not in out:
                out.append(p)
    _RESOLVED[role] = out
    return list(out)


def file_locked(p: Path) -> bool:
    """psutil 判断文件/目录是否被进程占用"""
    try:
        for proc in psutil.process_iter(["pid"]):
            try:
                for f in proc.open_files():
                    if os.path.normcase(f.path) == os.path.normcase(str(p)):
                        return True
            except (psutil.Error, OSError):
                continue
    except psutil.Error:
        return False
    return False


def locked_set(paths) -> set:
    """一次性收集被进程占用的路径集合（normcase 后）。

    file_locked 每调一次就遍历所有进程，N 个文件 × M 个进程开销爆炸，
    且 proc.open_files() 在某些系统进程上会无限阻塞。这里只遍历一次进程
    列表，把命中目标路径的收集起来，供清理线程批量查询。
    """
    targets = {os.path.normcase(str(p)) for p in paths}
    if not targets:
        return set()
    found: set = set()
    try:
        for proc in psutil.process_iter(["pid"]):
            try:
                for f in proc.open_files():
                    nf = os.path.normcase(f.path)
                    if nf in targets:
                        found.add(nf)
            except (psutil.Error, OSError):
                continue
    except psutil.Error:
        pass
    return found


# ============================ 回收站删除 ============================


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION = 3, 0x0004, 0x0010
FOF_ALLOWUNDO, FOF_NOERRORUI = 0x0040, 0x0400


def to_recycle_bin(path_str: str) -> Tuple[bool, str]:
    p = Path(path_str)
    if not p.exists():
        return False, "文件不存在"
    ops = _SHFILEOPSTRUCTW()
    ops.hwnd = 0
    ops.wFunc = FO_DELETE
    ops.pFrom = str(p) + "\0\0"
    ops.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    try:
        err = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(ops))
    except OSError as e:
        return False, str(e)
    if err:
        return False, f"SHFileOperation 错误码 {err}"
    if p.exists():
        return False, "删除失败（文件仍在）"
    return True, "已移入回收站"


# ============================ 已安装软件证据索引 ============================

_VERSION = re.compile(r"^v?\d+([._]\d+)*$")
_HASHY = re.compile(r"^[0-9a-f]{7,}$", re.I)
_JUNK_TOKEN = re.compile(
    r"^(?:win(?:dows|dows32|32)?|ia32|x64|x86|amd64|arm64|setup|inst|install|installer|"
    r"full|offline|online|portable|stable|beta|prod|signed|unsigned|web|multi|free|"
    r"zh[_-]?cn|ch[sm]|en[_-]?us|bits?|\d+bit|final|release|setup|next|canary|"
    r"alpha|user|setup|update|updater)$",
    re.I,
)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_INSTALL_BASE = (
    r"%LOCALAPPDATA%\Programs",
    r"%LOCALAPPDATA%",
    r"%APPDATA%",
    r"%ProgramFiles%",
    r"%ProgramFiles(x86)%",
    r"%ProgramData%",
)


class InstalledIndex:
    """一次性收集进程名 / 安装目录名 / 卸载注册表 DisplayName，做归一化子串匹配"""

    def __init__(self) -> None:
        self.tokens: set = set()
        self.aliases: Dict[str, List[str]] = CFG.get("installed_aliases", {}) or {}

    @staticmethod
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    def _add(self, s: str) -> None:
        n = self.norm(s)
        if len(n) >= 3:
            self.tokens.add(n)

    def build(self) -> None:
        for p in psutil.process_iter(["name", "exe"]):
            try:
                if p.info.get("name"):
                    self._add(Path(p.info["name"]).stem)
                if p.info.get("exe"):
                    self._add(Path(p.info["exe"]).stem)
            except (psutil.Error, OSError):
                continue

        roots = set()
        for key in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(k, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(k, sub) as sk:
                                dn, _ = winreg.QueryValueEx(sk, "DisplayName")
                                if dn:
                                    self._add(dn)
                        except OSError:
                            continue
            except OSError:
                continue
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            ) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(k, sub) as sk:
                            dn, _ = winreg.QueryValueEx(sk, "DisplayName")
                            if dn:
                                self._add(dn)
                    except OSError:
                        continue
        except OSError:
            pass

        for base in _INSTALL_BASE:
            cand = Path(expand(base))
            if not cand.is_dir():
                continue
            try:
                for e in os.scandir(cand):
                    if e.is_dir(follow_symlinks=False):
                        self._add(e.name)
            except OSError:
                continue

    def expand_aliases(self, name: str) -> List[str]:
        n = self.norm(name)
        out = [name]
        for k, vs in self.aliases.items():
            if self.norm(k) == n:
                out.extend(vs)
        return out

    def match(self, candidates: List[str]) -> Optional[str]:
        """返回命中的证据名，取最长匹配以降低误报"""
        best: Optional[str] = None
        for c in candidates:
            for probe in self.expand_aliases(c):
                n = self.norm(probe)
                if len(n) < 4:
                    continue
                for t in self.tokens:
                    if t == n or (len(n) >= 5 and (t.startswith(n) or n.startswith(t))):
                        if best is None or len(t) > len(best):
                            best = t
        return best


# ============================ 扫描器 ============================


class Scanner:
    category = "未分类"
    icon = "\u2022"

    def scan(self) -> List[Item]:
        raise NotImplementedError


def mk(cat: str, p: Path, name: str, risk: str, meta: str = "", note: str = "") -> Item:
    return Item(name, cat, str(p), dir_size(p), risk, meta, note)


class PythonScanner(Scanner):
    category, icon = "Python 环境与缓存", "\U0001f40d"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        depth = CFG["scan_options"].get("max_recursion_depth", 10)
        for root in CFG["scan_roots"]:
            r = Path(expand(root))
            if not r.is_dir():
                continue
            for dirpath, dirs, _ in os.walk(r):
                p = Path(dirpath)
                if excluded(p):
                    dirs[:] = []
                    continue
                try:
                    if len(p.relative_to(r).parts) >= depth:
                        dirs[:] = []
                except ValueError:
                    pass
                if p.name == ".venv" and (p / "pyvenv.cfg").is_file():
                    out.append(mk(self.category, p, "Python 虚拟环境 (.venv)", "caution",
                                  f"最后修改 {mtime(p)}",
                                  "项目虚拟环境。删掉源码仍在，但 pip 依赖要重装。"))
                    dirs[:] = []
        for cc in CFG["custom_cache"]:
            p = Path(expand(cc["path"]))
            if p.exists() and not excluded(p):
                out.append(mk(self.category, p, cc["name"], cc.get("risk", "safe"),
                              f"最后修改 {mtime(p)}", cc.get("note", "缓存目录")))
        return out


def _no_window() -> int:
    """Windows: 拉起子进程时别给它分配控制台。

    本程序打包成 console=False（GUI 子系统），自己没有控制台。Windows 的规则是
    控制台程序继承父进程的控制台，GUI 程序没有 -> 系统必须**新建**一个控制台
    窗口给子进程。于是每跑一次 git，屏幕上就闪一个黑框出来再消失 —— 扫描时
    每个 git 仓库闪一次，就是用户看到的"弹窗拖影"和"吓一跳"。

    CREATE_NO_WINDOW 正好解决这个：创建子进程但不分配控制台。
    """
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _hidden_startupinfo():
    """再兜一层：明确让子进程窗口不可见。"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0          # SW_HIDE
    return si


def _git_meta(git_root: str) -> Tuple[Optional[str], Optional[str]]:
    """(最后提交日期, remote 地址) —— 有 origin 基本就是正经项目，没有的多半是临时 clone"""
    def run(args: List[str]) -> Optional[str]:
        try:
            res = subprocess.run(["git", "-C", git_root] + args,
                                 capture_output=True, text=True, errors="replace",
                                 timeout=8, creationflags=_no_window(),
                                 startupinfo=_hidden_startupinfo())
            if res.returncode == 0:
                v = res.stdout.strip()
                return v or None
        except (OSError, subprocess.SubprocessError):
            pass
        return None
    return (run(["log", "-1", "--date=short", "--pretty=%cd"]),
            run(["remote", "get-url", "origin"]))


def git_repos_report() -> List[Note]:
    """只读清单。刻意不提供删除：无法区分临时 clone 与在用项目，代价太大。"""
    out: List[Note] = []
    depth = CFG["scan_options"].get("max_recursion_depth", 10)
    for root in CFG["scan_roots"]:
        r = Path(expand(root))
        if not r.is_dir():
            continue
        for dirpath, dirs, _ in os.walk(r):
            p = Path(dirpath)
            if excluded(p):
                dirs[:] = []
                continue
            try:
                if len(p.relative_to(r).parts) >= depth:
                    dirs[:] = []
            except ValueError:
                pass
            if not (p / ".git").is_dir():
                continue
            if p != r:
                last, remote = _git_meta(str(p))
                out.append(Note(
                    p.name, str(p), dir_size(p),
                    f"最后提交 {last or '未知'} · "
                    + (f"远程 {remote}" if remote else "无远程仓库（多半是临时 clone）"),
                    kind="Git 仓库"))
                dirs[:] = []
    return out


# ---- 安装包（GitHub Release / 官网下载的 exe、msi） ----


def product_candidates(stem: str) -> List[str]:
    """从安装包文件名里剥离版本号、平台、角色后缀，得到产品名候选"""
    parts = [x for x in re.split(r"[-_\s.]+", stem) if x]

    def keep(tok: str) -> bool:
        if _VERSION.match(tok) or _HASHY.match(tok):
            return False
        if _JUNK_TOKEN.match(tok):
            return False
        return True

    kept = [t for t in parts if keep(t)]
    cands: List[str] = []
    if kept:
        full = " ".join(kept).strip()
        if full:
            cands.append(full)
        for i in range(len(kept)):
            for j in range(len(kept), i, -1):
                seg = " ".join(kept[i:j])
                if seg and seg not in cands:
                    cands.append(seg)
    # 兜底：CamelCase 拆分（ChromeSetup -> Chrome）
    if not cands:
        for t in parts:
            for w in _CAMEL.split(t):
                if keep(w) and len(w) > 3 and w not in cands:
                    cands.append(w)
    out, seen = [], set()
    for c in cands:
        n = InstalledIndex.norm(c)
        if len(n) < 4 or n in seen:
            continue
        seen.add(n)
        out.append(c)
    return out[:5]


class InstallerScanner(Scanner):
    category, icon = "已安装软件的安装包", "\U0001f4e6"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        roots: List[Path] = []
        for role in ("Downloads", "Desktop"):
            for p in known_folders(role):
                if p not in roots:
                    roots.append(p)
        for extra in CFG.get("installer_roots", []) or []:
            p = Path(expand(extra))
            if p.is_dir() and p not in roots:
                roots.append(p)
        if not roots:
            return out

        idx = InstalledIndex()
        idx.build()
        min_age = int(CFG.get("min_installer_age_days", 14))
        min_size = int(CFG.get("min_installer_size_bytes", 8 * 1024 * 1024))

        for root in roots:
            try:
                entries = list(os.scandir(root))
            except OSError:
                continue
            for e in entries:
                if not e.is_file(follow_symlinks=False):
                    continue
                if Path(e.name).suffix.lower() not in (".exe", ".msi", ".zip", ".7z"):
                    continue
                p = Path(e.path)
                if excluded(p):
                    continue
                age = age_days(p)
                size = p.stat().st_size
                if size < min_size:
                    continue
                cands = product_candidates(Path(e.name).stem)
                hit = idx.match(cands) if cands else None
                if hit:
                    # 已装 = 铁证，与下载时间无关
                    out.append(Item(
                        Path(e.name).name, self.category, str(p), size, "safe",
                        f"{age} 天前下载 · 已装: {hit}",
                        "检测到该产品已安装，安装包可删。"))
                elif age < min_age:
                    continue          # 没证据又很新，先别烦用户
                else:
                    out.append(Item(
                        Path(e.name).name, self.category, str(p), size, "caution",
                        f"{age} 天前下载 · 未确认已安装",
                        "没检测到已安装证据。若你还要用这个安装包重装，请勿勾选。"))
        return out


# ---- 更新器残留 ----

UPDATER_GLOBS = (
    r"*\@*-updater\pending",
    r"*\updates\executors",
    r"*\updates\pending",
    r"*\update\downloads",
)


class UpdaterScanner(Scanner):
    category, icon = "更新器残留", "\U0001f504"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        for base in CFG.get("folder_roots", []) or []:
            b = Path(expand(base))
            if not b.is_dir():
                continue
            for g in UPDATER_GLOBS:
                for d in b.glob(g):
                    if not d.is_dir() or excluded(d):
                        continue
                    files = [f for f in d.rglob("*") if f.is_file()]
                    if not files:
                        continue
                    out.append(mk(self.category, d, f"更新包残留 · {d.name}", "safe",
                                  f"{len(files)} 个文件 · 最后修改 {mtime(d)}",
                                  "软件更新完留下的安装载荷，删除不影响已装版本。"))
        return out


# ---- Agent / skill 插件缓存 ----


class AgentCacheScanner(Scanner):
    category, icon = "AI Agent / Skill 缓存", "\U0001f9f0"

    def _active_plugins(self) -> List[str]:
        names: List[str] = []
        for cfg in CFG.get("agent_configs", []) or []:
            p = Path(expand(cfg["path"]))
            if not p.exists():
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
            txt = re.sub(r"^\s*//.*$", "", txt, flags=re.M)
            try:
                data = json.loads(txt)
            except json.JSONDecodeError:
                continue
            for pl in data.get("plugin", []) or []:
                if isinstance(pl, str) and not pl.startswith("."):
                    names.append(pl.lower())
        return names

    def scan(self) -> List[Item]:
        out: List[Item] = []
        base = Path(expand(CFG.get("agent_cache_root", "%USERPROFILE%/.cache/opencode/packages")))
        if not base.is_dir():
            return out
        active = self._active_plugins()

        # 1) X 与 X@latest 并存 -> 非 @latest 是旧解析版本
        for scope in base.iterdir():
            if not scope.is_dir() or excluded(scope):
                continue
            if scope.name.startswith("@"):          # @scope/ 这一层下面才是包
                pkgs = [x for x in scope.iterdir() if x.is_dir()]
            else:
                pkgs = [scope]
            for pkg in pkgs:
                if excluded(pkg):
                    continue
                latest = pkg.with_name(pkg.name + "@latest")
                if not latest.is_dir() or latest == pkg or excluded(latest):
                    continue
                out.append(mk(self.category, pkg, f"旧版本缓存 · {pkg.name}", "safe",
                              f"最后修改 {mtime(pkg)}",
                              f"已存在 {latest.name}，此目录是上一次解析留下的旧副本。"))

        # 2) 未在配置里启用的插件缓存
        for d in base.rglob("*@latest"):
            if not d.is_dir() or excluded(d):
                continue
            pkg = d.parent.name
            full = f"{pkg}/{d.name}".lower()
            if not any(a in full for a in active):
                out.append(mk(self.category, d, f"未启用的插件缓存 · {pkg}", "caution",
                              f"最后修改 {mtime(d)}",
                              "opencode 配置的 plugin 列表里没有它。删掉不影响当前使用的插件。"))
        return out


# ---- 构建产物 / 开发者垃圾 ----

JUNK_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".ipynb_checkpoints", ".gradle", ".idea", ".vs",
}


class BuildScanner(Scanner):
    category, icon = "构建产物 / 开发垃圾", "\U0001f9f9"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        depth = CFG["scan_options"].get("max_recursion_depth", 10)
        for root in CFG["scan_roots"]:
            r = Path(expand(root))
            if not r.is_dir():
                continue
            for dirpath, dirs, _ in os.walk(r):
                p = Path(dirpath)
                if excluded(p):
                    dirs[:] = []
                    continue
                try:
                    if len(p.relative_to(r).parts) >= depth:
                        dirs[:] = []
                except ValueError:
                    pass
                if p.name == "node_modules":
                    dirs[:] = []
                    continue
                if p.name in JUNK_DIR_NAMES:
                    out.append(mk(self.category, p, f"缓存目录 · {p.name}", "safe",
                                  f"最后修改 {mtime(p)}",
                                  "可重新生成的工具缓存。"))
                    dirs[:] = []
                    continue
                specs = list(p.glob("*.spec"))
                if specs:
                    for sub in ("build", "dist"):
                        d = p / sub
                        if d.is_dir() and not excluded(d):
                            label = "PyInstaller 构建缓存" if sub == "build" else "PyInstaller 产物"
                            risk = "safe" if sub == "build" else "caution"
                            note = ("打包中间文件，删了下次重新 build 即可。" if sub == "build"
                                    else "打包好的 exe。确认已安装/已分发再删。")
                            out.append(mk(self.category, d, f"{label} · {p.name}", risk,
                                          f"最后修改 {mtime(d)}", note))
                            dirs[:] = []
        return out


# ---- 只读：全局 npm 包（不提供删除） ----


def global_npm_report() -> List[Note]:
    out: List[Note] = []
    base = Path(expand(CFG.get("global_npm_root", "%APPDATA%/npm/node_modules")))
    if not base.is_dir():
        return out
    # 只应用 exclude_dirs；exclude_globs 里的 node_modules 是给递归扫描用的，
    # 在这里会把这个目录自己排除掉。
    banned = [Path(expand(e)).resolve() for e in CFG["exclude_dirs"]]
    for d in base.iterdir():
        if not d.is_dir():
            continue
        pkgs = [d] if d.name.startswith("@") else [d]
        for pkg in pkgs:
            try:
                rp = pkg.resolve()
                if any(rp.is_relative_to(b) for b in banned):
                    continue
            except (OSError, ValueError):
                pass
            ver = ""
            pj = pkg / "package.json"
            if pj.is_file():
                try:
                    ver = json.loads(pj.read_text(encoding="utf-8", errors="ignore")).get("version", "")
                except json.JSONDecodeError:
                    pass
            out.append(Note(f"npm -g {pkg.name}" + (f"@{ver}" if ver else ""),
                            str(pkg), dir_size(pkg),
                            "全局安装包，不是缓存，删了要重新 npm i -g", kind="全局 npm 包"))
    return out


# ============================ 传统垃圾文件 ============================


def _junk_targets() -> List[Tuple[str, str, str]]:
    """(显示名, 路径, 说明) —— 只列 Windows/浏览器/应用自己会重建的缓存"""
    T = [
        ("资源管理器缩略图缓存", "%LOCALAPPDATA%/Microsoft/Windows/Explorer", "thumbcache_*.db，会自动重建"),
        ("最近使用跳转列表", "%APPDATA%/Microsoft/Windows/Recent/CustomDestinations", "任务栏/资源管理器跳转列表"),
        ("最近使用自动目标", "%APPDATA%/Microsoft/Windows/Recent/AutomaticDestinations", "同上"),
        ("DirectX 着色器缓存", "%LOCALAPPDATA%/D3DSCache", "DirectX 着色器，自动重建"),
        ("崩溃转储", "%LOCALAPPDATA%/CrashDumps", "程序崩溃转储"),
        ("Windows 错误报告", "%LOCALAPPDATA%/Microsoft/Windows/WER", "错误报告队列"),
        ("图标缓存", "%LOCALAPPDATA%/IconCache", "自动重建"),
        ("Edge 浏览器缓存", "%LOCALAPPDATA%/Microsoft/Edge/User Data/Default/Cache", "上网缓存"),
        ("Edge Service Worker 缓存", "%LOCALAPPDATA%/Microsoft/Edge/User Data/Default/Service Worker/CacheStorage",
         "离线网页缓存，网页首次打开会重新下载"),
        ("Edge 代码缓存", "%LOCALAPPDATA%/Microsoft/Edge/User Data/Default/Code Cache", "V8 编译缓存"),
        ("Windows 更新缓存", "C:/Windows/SoftwareDistribution/Download", "已安装更新的安装包"),
        ("Windows 临时文件", "C:/Windows/Temp", "系统临时文件"),
        ("CBS 日志", "C:/Windows/Logs/CBS", "系统组件日志"),
    ]
    for p in CFG.get("extra_junk", []) or []:
        T.append((p["name"], p["path"], p.get("note", "自定义垃圾目录")))
    return T


class JunkScanner(Scanner):
    category, icon = "传统垃圾文件", "\U0001f9f9"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        for name, raw, note in _junk_targets():
            p = Path(expand(raw))
            if not p.is_dir() or excluded(p):
                continue
            # Explorer 目录下只清 thumbcache_*.db，别把别的系统文件带走
            if p.name == "Explorer":
                subs = list(p.glob("thumbcache_*.db")) + list(p.glob("iconcache_*.db"))
                if not subs:
                    continue
                sz = sum(f.stat().st_size for f in subs if f.is_file())
                if sz < 256 * 1024:
                    continue
                out.append(Item(f"{name} ({len(subs)} 个文件)", self.category, str(p),
                                sz, "safe", f"最后修改 {mtime(p)}", note))
                continue
            if p.is_symlink():
                continue
            sz = dir_size(p)
            if sz < 256 * 1024:
                continue
            out.append(Item(name, self.category, str(p), sz, "safe",
                            f"最后修改 {mtime(p)}", note))
        return out


# ============================ 过期临时文件 ============================


class OldTempScanner(Scanner):
    category, icon = "过期临时文件", "\u23f3"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        days = int(CFG.get("temp_min_age_days", 7))
        roots = [Path(expand(r)) for r in
                 (CFG.get("temp_roots") or ["%LOCALAPPDATA%/Temp"])]
        for root in roots:
            if not root.is_dir():
                continue
            try:
                entries = list(os.scandir(root))
            except OSError:
                continue
            for e in entries:
                p = Path(e.path)
                if excluded(p):
                    continue
                if age_days(p) < days:
                    continue
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if age_days(p) < days:
                        continue
                    sz = dir_size(p)
                    if sz < 1024 * 1024:
                        continue
                    risk = "caution" if _is_running_dir(p) else "safe"
                elif e.is_file(follow_symlinks=False):
                    sz = e.stat(follow_symlinks=False).st_size
                    if sz < 1024 * 1024:
                        continue
                    risk = "safe"
                else:
                    continue
                out.append(Item(e.name, self.category, str(p), sz, risk,
                                f"{age_days(p)} 天未动", 
                                "超过阈值的临时项。若某程序正在用它，重启后再清。"))
        return out


def _is_running_dir(p: Path) -> bool:
    """目录里有 exe 在跑就别动（PyInstaller 的 _MEIxxxx 之类）"""
    try:
        for f in p.iterdir():
            if f.suffix.lower() in (".exe", ".dll") and file_locked(f):
                return True
            if _is_running_dir(f) if f.is_dir(follow_symlinks=False) else False:
                return True
    except OSError:
        return False
    return False


# ============================ 空文件 / 空目录 / 断链 ============================

# 这些名字的空文件是"有意留着的"，删了会坏事
KEEP_EMPTY_NAMES = {
    ".gitkeep", ".keep", ".gitignore", "thumbs.db", "desktop.ini", "readme",
    ".ds_store", ".nojekyll", "license", "notice", ".gitattributes",
}
KEEP_EMPTY_EXT = {".lock", ".lck", ".pid", ".info", ".keep"}

# 一对多条目的载荷：Item.path 形如 "BULK:empty"，真正的路径列表存在这里
BULK: Dict[str, Dict[str, List[str]]] = {}


def expand_bulk(path: str) -> List[str]:
    payload = BULK.get(path.split(":", 1)[1]) if path.startswith("BULK:") else None
    if not payload:
        return []
    return payload.get("files", []) + payload.get("dirs", []) + payload.get("links", [])


def delete_bulk(path: str) -> Tuple[int, int, List[str]]:
    """返回 (成功数, 失败数, 失败样例)。断链用 os.rmdir/unlink（它没有内容，
    SHFileOperation 对断链行为不确定）；空文件/空目录照常进回收站。"""
    payload = BULK.get(path.split(":", 1)[1]) if path.startswith("BULK:") else None
    if not payload:
        return 0, 0, ["无效的批量条目"]
    ok = fail = 0
    errs: List[str] = []
    for f in payload.get("links", []):
        p = Path(f)
        try:
            (os.rmdir if p.is_dir() else os.unlink)(p)   # 只删链接本身
            ok += 1
        except OSError as e:
            fail += 1
            if len(errs) < 8:
                errs.append(f"{p.name}（{e.strerror or e}）")
    for f in payload.get("files", []) + payload.get("dirs", []):
        if not Path(f).exists():
            continue
        good, msg = to_recycle_bin(f)
        if good:
            ok += 1
        else:
            fail += 1
            if len(errs) < 8:
                errs.append(f"{Path(f).name}（{msg}）")
    BULK.pop(path.split(":", 1)[1], None)
    return ok, fail, errs


class EmptyScanner(Scanner):
    category, icon = "空文件 / 空目录 / 断链", "\u2205"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        depth = CFG["scan_options"].get("max_recursion_depth", 10)
        only_empty_dirs = bool(CFG.get("empty_scan_dirs", True))
        files: List[str] = []
        dirs: List[str] = []
        links: List[str] = []
        for root in CFG["scan_roots"]:
            r = Path(expand(root))
            if not r.is_dir():
                continue
            for dirpath, _dirs, fnames in os.walk(r):
                p = Path(dirpath)
                if excluded(p):
                    _dirs[:] = []
                    continue
                try:
                    if len(p.relative_to(r).parts) >= depth:
                        _dirs[:] = []
                except ValueError:
                    pass
                for name in _dirs:
                    d = p / name
                    if d.is_symlink() and not d.exists():
                        links.append(str(d))
                        _dirs.remove(name)
                for f in fnames:
                    fp = p / f
                    if fp.is_symlink():
                        if not fp.exists():
                            links.append(str(fp))
                        continue
                    if f.lower() in KEEP_EMPTY_NAMES or Path(f).suffix.lower() in KEEP_EMPTY_EXT:
                        continue
                    try:
                        if fp.stat().st_size:
                            continue
                    except OSError:
                        continue
                    files.append(str(fp))
                if only_empty_dirs and p != r:
                    try:
                        if not any(p.iterdir()):
                            dirs.append(str(p))
                    except OSError:
                        pass
        n = len(files) + len(dirs) + len(links)
        if n:
            BULK["empty"] = {"files": files, "dirs": dirs, "links": links}
            out.append(Item(
                f"空文件 {len(files)} · 空目录 {len(dirs)} · 断链 {len(links)}",
                self.category, "BULK:empty", n, "caution",
                f"合计 {n} 项，均为 0 字节，不占空间",
                "删除前请确认没有程序依赖这些空目录。已自动跳过 .gitkeep/.lock/desktop.ini 等。",
                unit="count"))
        return out


# ============================ GitHub 相关 ============================


class GitHubScanner(Scanner):
    category, icon = "GitHub 残留", "\u2691"

    def scan(self) -> List[Item]:
        out: List[Item] = []
        for name, raw, note in [
            ("gh CLI 缓存", "%USERPROFILE%/.cache/gh", "GitHub CLI 的 API 缓存"),
            ("GitHub Desktop 缓存", "%LOCALAPPDATA%/GitHubDesktop/app-*", "GitHub 桌面版应用缓存"),
            ("Copilot 缓存", "%LOCALAPPDATA%/GitHubCopilot", "Copilot 下载的模型/资源"),
        ]:
            p = Path(expand(raw))
            if not p.is_dir() or excluded(p):
                continue
            sz = dir_size(p)
            if sz < 256 * 1024:
                continue
            out.append(Item(name, self.category, str(p), sz, "safe",
                            f"最后修改 {mtime(p)}", note))
        return out


def git_repo_cleanup_candidates() -> List[Item]:
    """可以安全删掉的 clone：有明确信号 —— 无远程仓库 + 长期未动 + 无未推送提交"""
    out: List[Item] = []
    days = int(CFG.get("stale_clone_days", 60))
    depth = CFG["scan_options"].get("max_recursion_depth", 10)
    for root in CFG["scan_roots"]:
        r = Path(expand(root))
        if not r.is_dir():
            continue
        for dirpath, dirs, _ in os.walk(r):
            p = Path(dirpath)
            if excluded(p):
                dirs[:] = []
                continue
            try:
                if len(p.relative_to(r).parts) >= depth:
                    dirs[:] = []
            except ValueError:
                pass
            if p == r or not (p / ".git").is_dir():
                continue
            dirs[:] = []
            last, remote = _git_meta(str(p))
            if remote:
                continue                      # 有远程 = 你的正经项目，绝不动
            idle = age_days(p)
            if idle < days:
                continue
            gitdir = p / ".git"
            gsz = dir_size(gitdir)
            if _has_unpushed(p):
                continue
            out.append(Item(
                f"无远程的本地 clone · {p.name}", GitHubScanner.category, str(p),
                dir_size(p), "caution",
                f"{idle} 天未动 · {human(gsz)} 是 .git 内部数据",
                "没有配置远程仓库，确认不需要了再删。"))
    return out


def _has_unpushed(git_root: str) -> bool:
    try:
        r = subprocess.run(["git", "-C", git_root, "status", "--porcelain"],
                           capture_output=True, text=True, errors="replace",
                           timeout=10, creationflags=_no_window(),
                           startupinfo=_hidden_startupinfo())
        return bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


# ============================ 注册表清理 ============================

# 只碰 HKCU 下 Windows 自己会重建的 MRU 键，绝不碰系统/驱动/服务类键
MRU_KEYS: List[Tuple[str, str]] = [
    (r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
     "程序名使用记录"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage\AppSwitched",
     "程序切换记录"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage\ShowJumpView",
     "跳转视图记录"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\WordWheelQuery",
     "资源管理器搜索记录"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU", "运行历史"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths", "地址栏历史"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist", "用户操作记录"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs", "最近文档"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU",
     "打开/保存历史"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\CIDSizeMRU",
     "对话框尺寸记录"),
]

UNINSTALL_BRANCHES = [
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def _key_stats(hive, sub: str) -> Tuple[int, int]:
    """(值数量, 子键数量)"""
    n = s = 0
    try:
        with winreg.OpenKey(hive, sub) as k:
            i = 0
            while True:
                try:
                    winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                n += 1
            while True:
                try:
                    winreg.EnumKey(k, s)
                except OSError:
                    break
                s += 1
    except OSError:
        pass
    return n, s


def _value(hive, sub: str, name: str) -> Optional[str]:
    try:
        with winreg.OpenKey(hive, sub) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v if isinstance(v, str) else None
    except OSError:
        return None


def _exe_missing(cmd: Optional[str]) -> bool:
    if not cmd:
        return False
    m = re.search(r'"([^"]+\.exe)"', cmd) or re.search(r"([A-Za-z]:\\[^\s\"]+\.exe)", cmd)
    if not m:
        return False
    return not os.path.exists(m.group(1))


def _hname(hive: int) -> str:
    return "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"


def _parse_reg_path(p: str) -> Optional[Tuple[str, str, str]]:
    """REG:<op>:<arg> -> (op, hive_name, sub_or_value)"""
    if not p.startswith("REG:"):
        return None
    rest = p[4:]
    op, _, arg = rest.partition(":")
    hive_name, _, sub = arg.partition("\\")
    return op, hive_name, sub


def registry_findings() -> List[Item]:
    """可安全重置的 MRU 组 + 指向失效程序的卸载项/启动项。均需先导出 .reg 备份。"""
    out: List[Item] = []
    total = 0
    parts: List[str] = []
    for sub, desc in MRU_KEYS:
        n, s = _key_stats(winreg.HKEY_CURRENT_USER, sub)
        if n or s:
            total += n + s
            parts.append(f"{desc} {n + s}")
    if total:
        out.append(Item(
            f"Windows 使用记录 · {len(MRU_KEYS)} 个键 / {total} 项",
            "注册表 · 可安全重置", "REG:mru:", total, "safe",
            "；".join(parts[:4]),
            "资源管理器的 MRU 历史。删掉后 Windows 自动重建，不影响任何程序。",
            unit="count"))

    for hive, branch in UNINSTALL_BRANCHES:
        try:
            with winreg.OpenKey(hive, branch) as b:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(b, i)
                    except OSError:
                        break
                    i += 1
                    full = branch + "\\" + name
                    dn = _value(hive, full, "DisplayName")
                    if not dn:
                        continue
                    us = _value(hive, full, "UninstallString")
                    il = _value(hive, full, "InstallLocation")
                    # 只认「卸载命令里的 exe 不存在」这一个决定性信号。
                    # 曾经也用 InstallLocation 是否存在来判断，误报了一大片：
                    # 微信 / VS Installer 的 Uninstall.exe 明明在，只是
                    # InstallLocation 指向了旧路径。删掉活程序的卸载项 =
                    # 以后再也卸不掉它，代价远大于收益。
                    if not _exe_missing(us):
                        continue
                    n, s = _key_stats(hive, full)
                    out.append(Item(
                        f"失效的卸载项 · {dn}",
                        "注册表 · 失效程序",
                        f"REG:delkey:{_hname(hive)}\\{full}", n + s, "caution",
                        f"Uninstall={us or '(无)'}",
                        "卸载命令指向的 exe 已不存在。删除前自动备份 .reg。",
                        unit="count"))
        except OSError:
            continue

    for hive, branch, label in [
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "启动项"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "系统启动项"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", "一次性启动项"),
    ]:
        n, _s = _key_stats(hive, branch)
        if not n:
            continue
        try:
            with winreg.OpenKey(hive, branch) as k:
                i = 0
                while True:
                    try:
                        vname, vdata, _t = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if not _exe_missing(vdata if isinstance(vdata, str) else None):
                        continue
                    out.append(Item(
                        f"指向不存在程序的{label} · {vname}",
                        "注册表 · 失效程序",
                        f"REG:delvalue:{_hname(hive)}\\{branch}\\{vname}", 1, "caution",
                        (vdata or "")[:90],
                        "目标 exe 不存在。删除前自动备份。",
                        unit="count"))
        except OSError:
            continue
    return out


def backup_root() -> Path:
    d = Path(expand("%LOCALAPPDATA%/DevCleaner/registry_backups"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hive_root(hive: int) -> str:
    return {winreg.HKEY_CURRENT_USER: "HKEY_CURRENT_USER",
            winreg.HKEY_LOCAL_MACHINE: "HKEY_LOCAL_MACHINE",
            winreg.HKEY_CLASSES_ROOT: "HKEY_CLASSES_ROOT",
            winreg.HKEY_USERS: "HKEY_USERS",
            winreg.HKEY_CURRENT_CONFIG: "HKEY_CURRENT_CONFIG"}.get(hive, "HKEY_CURRENT_USER")


def _reg_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _reg_value_line(name: str, vdata, vtype: int) -> str:
    key = name or "@"
    if vtype == winreg.REG_SZ:
        return f'"{key}"="{_reg_escape(vdata)}"'
    if vtype == winreg.REG_EXPAND_SZ:
        return f'"{key}"=expand("{_reg_escape(vdata)}")'
    if vtype == winreg.REG_DWORD:
        return f'"{key}"=dword:{int(vdata) & 0xFFFFFFFF:08x}'
    if vtype == winreg.REG_QWORD:
        return f'"{key}"=qword:{int(vdata) & 0xFFFFFFFFFFFFFFFF:016x}'
    if vtype == winreg.REG_MULTI_SZ:
        joined = "\\0".join(_reg_escape(x) for x in vdata)
        return f'"{key}"=hex(7):{",".join(f"{b:02x}" for b in joined.encode("utf-16-le"))}'
    if vtype == winreg.REG_BINARY:
        return f'"{key}"=hex:{",".join(f"{b:02x}" for b in vdata)}'
    if vtype == winreg.REG_NONE:
        return f'"{key}"=hex(0):'
    return f'"{key}"=hex:{",".join(f"{b:02x}" for b in bytes(vdata))}'


def write_reg_file(hive: int, sub: str, out: Path) -> Tuple[bool, str]:
    """生成 regedit 能读的 .reg。reg.exe 的命令行引号规则太脆，这里直接生成。"""
    lines = ["Windows Registry Editor Version 5.00", ""]

    def walk(path: str) -> None:
        lines.append(f"[{_hive_root(hive)}\\{path}]")
        try:
            with winreg.OpenKey(hive, path) as k:
                i = 0
                while True:
                    try:
                        name, vdata, vtype = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if isinstance(vdata, bytes) and vtype == winreg.REG_BINARY:
                        lines.append(_reg_value_line(name, vdata, vtype))
                    else:
                        lines.append(_reg_value_line(name, vdata, vtype))
                subs = []
                j = 0
                while True:
                    try:
                        subs.append(winreg.EnumKey(k, j))
                    except OSError:
                        break
                    j += 1
        except OSError:
            return
        lines.append("")
        for s in subs:
            walk(path + "\\" + s)

    walk(sub)
    try:
        out.write_bytes(b"\xff\xfe" + "\r\n".join(lines).encode("utf-16-le"))
    except OSError as e:
        return False, f"写备份文件失败: {e}"
    return True, ""


def export_registry_keys(keys: List[Tuple[str, str]], tag: str) -> Tuple[bool, str]:
    """keys = [(hive_name, subpath)]。返回 (是否全部成功, 目录)"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = backup_root() / f"{stamp}_{tag}"
    outdir.mkdir(parents=True, exist_ok=True)
    combined = ["Windows Registry Editor Version 5.00", ""]
    for idx, (hname, sub) in enumerate(keys):
        hive = winreg.HKEY_CURRENT_USER if hname == "HKCU" else winreg.HKEY_LOCAL_MACHINE
        try:
            winreg.OpenKey(hive, sub).Close()
        except OSError:
            return False, f"键不存在，无法备份: {hname}\\{sub}"
        tmp = outdir / f".part{idx}.reg"
        ok, err = write_reg_file(hive, sub, tmp)
        if not ok:
            return False, err
        combined.append(f"; ---- {hname}\\{sub} ----")
        body = tmp.read_bytes()[2:].decode("utf-16-le")
        combined.append(body.replace("Windows Registry Editor Version 5.00", "").strip())
        tmp.unlink(missing_ok=True)
    combined.append("")
    final = outdir / f"{tag}.reg"
    final.write_bytes(b"\xff\xfe" + "\r\n".join(combined).encode("utf-16-le"))
    return True, str(outdir)


def delete_registry_key(hname: str, sub: str) -> Tuple[bool, str]:
    hive = winreg.HKEY_CURRENT_USER if hname == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    try:
        with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ) as k:
            subs = []
            i = 0
            while True:                    # 索引必须递增，否则永远拿到第一个
                try:
                    subs.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except FileNotFoundError:
        return True, "已不存在"
    except PermissionError:
        return False, "权限不足（该键需管理员权限）"
    except OSError:
        subs = []
    for s in subs:
        delete_registry_key(hname, sub + "\\" + s)
    try:
        winreg.DeleteKeyEx(hive, sub, winreg.KEY_WOW64_64KEY, 0)
        return True, "已删除"
    except FileNotFoundError:
        return True, "已不存在"
    except PermissionError:
        return False, "权限不足（该键需管理员权限）"
    except OSError as e:
        return False, f"删除失败: {e}"


def delete_registry_value(hname: str, sub: str, value: str) -> Tuple[bool, str]:
    hive = winreg.HKEY_CURRENT_USER if hname == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    try:
        with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, value)
        return True, "已删除"
    except FileNotFoundError:
        return True, "已不存在"
    except PermissionError:
        return False, "权限不足（需管理员）"
    except OSError as e:
        return False, f"删除失败: {e}"


def apply_registry_item(it: Item) -> Tuple[bool, str]:
    """执行一个注册表条目：先备份，再删。备份失败则拒绝删除。"""
    parsed = _parse_reg_path(it.path)
    if not parsed:
        return False, "不是注册表条目"
    op, hname, sub = parsed
    if op == "mru":
        keys = [("HKCU", s) for s, _ in MRU_KEYS]
        ok, info = export_registry_keys(keys, "MRU")
        if not ok:
            return False, info
        n = 0
        for _, s in keys:
            d, _ = delete_registry_key("HKCU", s)
            if d:
                n += 1
        return True, f"已重置 {n} 个键 · 备份 {info}"
    if op == "delkey":
        ok, info = export_registry_keys([(hname, sub)], "delkey")
        if not ok:
            return False, info
        d, msg = delete_registry_key(hname, sub)
        return d, f"{msg} · 备份 {info}"
    if op == "delvalue":
        parent, _, value = sub.rpartition("\\")
        ok, info = export_registry_keys([(hname, parent)], "delvalue")
        if not ok:
            return False, info
        d, msg = delete_registry_value(hname, parent, value)
        return d, f"{msg} · 备份 {info}"
    return False, f"未知操作 {op}"



# ============================ 主题 ============================
#
# 色值原样取自 docs/palette-directions.html（设计稿，勿手改这里，要改改设计稿）。
# 设计稿给了 7 个主色 + 从 mockup 边框反推出的分割线色；次级/三级文字色、
# 分割线亮度和「强调色上的文字色」由主色推导 —— 推导而不是手抄，是因为
# 用户改主色时这几项要跟着自动走，且对比度是算出来的不是猜的。


def _hx(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hs(r: int, g: int, b: int) -> str:
    return "#%02X%02X%02X" % (max(0, min(255, r)), max(0, min(255, g)),
                              max(0, min(255, b)))


def _mix(a: str, b: str, t: float) -> str:
    """t=0 取 a，t=1 取 b"""
    A, B = _hx(a), _hx(b)
    return _hs(*[round(A[i] + (B[i] - A[i]) * t) for i in range(3)])


def _lum(h: str) -> float:
    def ch(v: int) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _hx(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _theme(name: str, bg: str, panel: str, panel2: str, fg: str, accent: str,
           safe: str, caution: str, line: str) -> Dict[str, str]:
    # 强调色上的文字：在「白字 vs 主题底色字」里取对比度更高的那个。
    # 深色候选必须是 bg 而不是 fg —— 浅强调色（Rosé Pine 的 #EBBCBA、
    # Tokyo Night 的 #7AA2F7）上，fg 本身是近白色，等于没得选，只有 1.7:1。
    # 设计稿在这两套上用的正是各自的 bg。Ink 的强调色上白字只有 3.3:1，
    # 这里改用底色字（5.3:1）—— 唯一一处偏离设计稿，为了过 AA。
    on = bg if _contrast(bg, accent) >= _contrast("#FFFFFF", accent) else "#FFFFFF"
    return {
        "n": name,
        "bg": bg, "panel": panel, "panel2": panel2, "fg": fg,
        "accent": accent, "safe": safe, "caution": caution,
        "line": line,
        "line2": _mix(line, fg, 0.22),          # 底栏等需要更亮的分隔线
        "fg2": _mix(bg, fg, 0.66),              # 次级文字（路径、元信息）
        "fg3": _mix(bg, fg, 0.52),              # 三级文字（说明、标签）
        "onaccent": on,
        "accent2": _mix(accent, bg, 0.16),      # 主按钮 hover
        # 勾选行底色：强调色压到 10% 不透明度。写成 rgba() 是因为它是盖在
        # 面板色上的半透明层，用 palette 上色才不用重解析样式表。
        "sel": "rgba(%d,%d,%d,26)" % _hx(accent),
    }


# 三个方向，每个方向一深一浅，共 6 套。line 色从设计稿 mockup 的
# border-color / row border-color 反推。
_PALETTES = [
    # A. Studio —— Linear / Vercel / Raycast 那一脉
    _theme("Studio Dark", "#08090A", "#0E0F11", "#16171A", "#F7F8F8",
           "#5E6AD2", "#3FB950", "#D29922", "#1E1F22"),
    _theme("Studio Light", "#FBFBFA", "#FFFFFF", "#F4F4F2", "#1A1A1A",
           "#5E6AD2", "#1A7F37", "#9A6700", "#E5E5E3"),
    # B. Editorial —— 杂志/印刷质感，暖米白纸面 + 深墨字 + 单一赤陶强调色
    _theme("Paper", "#F5F1EA", "#FFFCF6", "#EFE9DD", "#2B2722",
           "#B8553A", "#5B7A3D", "#B07D2B", "#DDD5C7"),
    _theme("Ink", "#1C1A17", "#252320", "#2D2A26", "#F0EBE0",
           "#C77B5C", "#8FB06A", "#D9A85C", "#3A3631"),
    # C. Curated —— 社区打磨过的成熟色板
    _theme("Rosé Pine", "#191724", "#1F1D2E", "#26233A", "#E0DEF4",
           "#EBBCBA", "#9CCFD8", "#F6C177", "#403D52"),
    _theme("Tokyo Night", "#1A1B26", "#16161E", "#1F2335", "#C0CAF5",
           "#7AA2F7", "#9ECE6A", "#E0AF68", "#2D2F40"),
]

# 列表顺序 = 下拉框顺序，第一项为默认。改 DEFAULT_THEME 的名字即可换默认。
THEMES: Dict[str, Dict[str, str]] = {t["n"]: t for t in _PALETTES}
THEME_ORDER: List[str] = [t["n"] for t in _PALETTES]
DEFAULT_THEME = str(CFG.get("theme") or "Ink")


def set_config_value(key: str, value: str) -> bool:
    """就地改 settings.yaml 的一个标量键。
    刻意不用 yaml.safe_load + dump 全量重写 —— 那会把用户写的注释全冲掉。
    逐行处理：找到就替换，没有就追加到末尾。"""
    p = resource("settings.yaml")
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return False
    line = f"{key}: {value}"
    out: List[str] = []
    hit = False
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith(f"{key}:") and not s.startswith(f"# {key}:") \
                and not s.startswith("##"):
            out.append(line)
            hit = True
        else:
            out.append(ln)
    if not hit:
        if out and out[-1].strip():
            out.append("")
        out.append(line)
    try:
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


SCANNERS: List[Scanner] = [
    InstallerScanner(),
    GitHubScanner(),
    UpdaterScanner(),
    JunkScanner(),
    OldTempScanner(),
    AgentCacheScanner(),
    BuildScanner(),
    PythonScanner(),
    EmptyScanner(),
]


# ============================ 扫描调度 ============================


def run_scan(on_progress: Optional[Callable[[str, float], None]] = None) -> None:
    """on_progress(stage, 0..1) 供界面线程消费。本函数在扫描线程里跑。"""
    def emit(stage: str, p: float) -> None:
        STATE.stage = stage
        STATE.progress = p
        if on_progress:
            on_progress(stage, p)

    STATE.running = True
    STATE.progress = 0.0
    STATE.items.clear()
    STATE.notes.clear()
    STATE.log.clear()
    emit("准备中", 0.0)
    try:
        total = len(SCANNERS) + 1
        for i, sc in enumerate(SCANNERS):
            emit(f"扫描 {sc.category}", i / total)
            t0 = time.time()
            try:
                res = sc.scan()
            except Exception as err:                      # noqa: BLE001
                STATE.say(f"[失败] {sc.category}: {err}")
                res = []
            STATE.items.extend(res)
            for it in res:
                it.icon = sc.icon
            STATE.say(f"{sc.category}: {len(res)} 项 · {time.time() - t0:.1f}s")
        emit("汇总只读信息", len(SCANNERS) / total)
        STATE.notes.extend(global_npm_report())
        STATE.notes.extend(git_repos_report())
        emit("检查注册表", (len(SCANNERS) + 0.5) / total)
        for it in registry_findings():
            it.icon = "\U0001f5c4"
            STATE.items.append(it)
        emit("查找无远程的 clone", (len(SCANNERS) + 0.7) / total)
        for it in git_repo_cleanup_candidates():
            it.icon = GitHubScanner.icon
            STATE.items.append(it)
        minsz = int(CFG["scan_options"].get("min_size_bytes", 1048576))
        before = len(STATE.items)
        # 注册表/空文件类按条目数，不参与字节阈值过滤
        STATE.items[:] = [i for i in STATE.items
                          if i.unit != "bytes" or i.size >= minsz]
        dropped = before - len(STATE.items)
        if dropped:
            STATE.say(f"已忽略 {dropped} 个小于 {human(minsz)} 的条目")
        STATE.say(f"扫描完成，共 {len(STATE.items)} 个可清理项")
    except Exception as err:                              # noqa: BLE001
        STATE.say(f"[异常] {type(err).__name__}: {err}")
    finally:
        STATE.running = False
        STATE.progress = 1.0
        STATE.finished_at = datetime.now().strftime("%H:%M:%S")
        if on_progress:
            on_progress(STATE.stage, 1.0)


if __name__ == "__main__":
    import argparse

    _ap = argparse.ArgumentParser(
        prog=APP_NAME, description="本地清理工具的扫描引擎（无界面）")
    _ap.add_argument("--version", "-V", action="version",
                     version=f"{APP_NAME} {__version__}")
    _ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    _ap.add_argument("--category", "-c", help="只跑某个分类（含关键词即可）")
    _ap.add_argument("--min-age", type=int, help="覆盖 settings.yaml 里的天龄阈值")
    _ap.add_argument("--json-indent", type=int, default=2, help="JSON 缩进")
    _a = _ap.parse_args()

    def _say(msg: str) -> None:
        """--json 模式下不能往前置任何东西，否则输出就不是合法 JSON 了"""
        if not _a.json:
            print(msg)

    def _always(msg: str) -> None:
        """版本/帮助这类元信息走 stderr：console=False 的 exe 没有可靠 stdout"""
        for name in ("stderr", "stdout"):
            try:
                getattr(sys, name).write(msg + "\n")
                getattr(sys, name).flush()
            except (OSError, ValueError, AttributeError):
                pass

    _say(f"{APP_NAME} {__version__}  配置: {resource('settings.yaml')}")
    if _a.min_age is not None:
        CFG["temp_min_age_days"] = _a.min_age
        CFG["min_installer_age_days"] = _a.min_age
    _say(f"扫描根: {CFG['scan_roots']}")
    if not _a.json:
        print()

    if _a.category:
        keep = [s for s in SCANNERS if _a.category in s.category]
        if not keep:
            print(f"没有匹配 '{_a.category}' 的分类。可选：")
            for s in SCANNERS:
                print("  " + s.category)
            sys.exit(2)
        SCANNERS[:] = keep
    run_scan()

    if _a.json:
        import json as _json
        print(_json.dumps({
            "version": __version__,
            "log": STATE.log,
            "items": [
                {"name": i.name, "category": i.category, "path": i.path,
                 "size": i.size, "unit": i.unit, "risk": i.risk}
                for i in STATE.items],
            "notes": [
                {"name": n.name, "kind": n.kind, "path": n.path, "size": n.size}
                for n in STATE.notes],
        }, ensure_ascii=False, indent=_a.json_indent))
        sys.exit(0)

    print()
    for line in STATE.log:
        print("  " + line)
    print()
    groups: Dict[str, List[Item]] = {}
    for it in STATE.items:
        groups.setdefault(it.category, []).append(it)
    for cat, rows in groups.items():
        units = [r.unit for r in rows]
        b = sum(r.size for r in rows if r.unit != "count")
        c = sum(r.size for r in rows if r.unit == "count")
        tot = (human(b) if b else "") + (f" + {c} 项" if c else "")
        print(f"== {cat}  {len(rows)} 条  {tot}")
        for r in sorted(rows, key=lambda x: -x.size)[:10]:
            sz = human(r.size) if r.unit != "count" else f"{r.size} 项"
            print(f"   [{r.risk:7}] {sz:>12}  {r.name}")
    b = sum(i.size for i in STATE.items if i.unit != "count")
    print(f"\n可释放字节合计: {human(b)}")
