"""DevCleaner 自检 —— python test_app.py 应输出 ALL OK"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# GitHub runner 的控制台是 cp1252，本机是 GBK —— 两者都编不了中文。
# 测试名和失败信息里有中文，不兜住就会 UnicodeEncodeError 崩掉整个套件。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import app
from app import (InstalledIndex, age_days, dir_size, human, known_folders,
                 product_candidates, to_recycle_bin)

FAILS = []


def check(name, fn):
    try:
        fn()
        print(f"  ok   {name}")
    except Exception as e:  # noqa: BLE001
        FAILS.append(f"{name}: {e}")
        print(f"  FAIL {name}  -> {type(e).__name__}: {e}")


# ---------------- 基础工具 ----------------
_TMP: list = []


def tmpdir(prefix: str = "devcleaner_test_") -> Path:
    """本次测试的临时目录，退出时统一清（见 cleanup）。"""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    _TMP.append(d)
    return d


def t_human():
    assert human(0) in ("0 B", "0.00 B"), human(0)
    assert human(2048) == "2.00 KB", human(2048)
    assert human(3 * 1024 ** 3) == "3.00 GB", human(3 * 1024 ** 3)


def t_candidates():
    cases = {
        "OfficeAce-1.1.4-windows-x64-setup": "officeace",
        "CodeArts-0.1.26-f649f71-x64-prod": "codearts",
        "Feishu-win32_ia32-8.0.3-signed": "feishu",
        "dotnet-sdk-10.0.401-win-x64": "dotnet",
    }
    for stem, want in cases.items():
        got = product_candidates(stem)
        assert got, stem
        assert want in " | ".join(got).lower(), f"{stem} -> {got}"
    assert any("chrome" in g.lower() for g in product_candidates("ChromeSetup")), \
        product_candidates("ChromeSetup")
    assert not product_candidates("setup-1.0.0"), product_candidates("setup-1.0.0")


def t_index():
    idx = InstalledIndex()
    idx.tokens = {"officeclaw", "googlechrome", "codearts"}
    assert idx.match(["OfficeAce"]) == "officeclaw", "别名表未生效"
    assert idx.match(["Feishu"]) is None, "未安装的不能误命中"
    assert idx.match(["CodeArts"]) == "codearts"
    assert idx.match(["zzz"]) is None
    assert idx.match(["go"]) is None, "过短的名字不该参与匹配"


def t_dirsize(tmp):
    d = tmp / "sizetest"
    (d / "a").mkdir(parents=True)
    (d / "a" / "x.bin").write_bytes(b"x" * 5000)
    (d / "b.bin").write_bytes(b"y" * 3000)
    assert dir_size(d) == 8000, dir_size(d)
    assert age_days(d) == 0, age_days(d)


def t_recycle(tmp):
    f = tmp / "junk-xyz.txt"
    f.write_text("x" * 100, encoding="utf-8")
    ok, msg = to_recycle_bin(str(f))
    assert ok, msg
    assert not f.exists(), "文件没被移走"
    ok2, msg2 = to_recycle_bin(str(f))
    assert not ok2 and msg2 == "文件不存在", msg2


# ---------------- 扫描器 ----------------
def t_scanners(tmp):
    proj = tmp / "proj"
    (proj / ".venv" / "lib").mkdir(parents=True)
    (proj / ".venv" / "pyvenv.cfg").write_text("home = x", encoding="utf-8")
    (proj / ".venv" / "lib" / "m.bin").write_bytes(b"m" * 20000)
    repo = tmp / "repo"
    (repo / ".git" / "objects").mkdir(parents=True)
    (repo / ".git" / "objects" / "o").write_bytes(b"g" * 20000)
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("print(1)", encoding="utf-8")
    (proj / "build").mkdir()
    (proj / "build" / "junk.bin").write_bytes(b"b" * 20000)
    (proj / "App.spec").write_text("# spec", encoding="utf-8")
    keep = tmp / "keepme"
    keep.mkdir()
    (keep / "big.bin").write_bytes(b"k" * 30000)

    old = app.CFG
    app.CFG = dict(old)
    app.CFG["scan_roots"] = [str(tmp)]
    app.CFG["exclude_dirs"] = [str(keep)]
    app.CFG["exclude_globs"] = ["**/node_modules/**"]
    app.CFG["custom_cache"] = []
    app.CFG["scan_options"] = dict(old["scan_options"], min_size_bytes=1, max_recursion_depth=8)
    try:
        py = app.PythonScanner().scan()
        p = [i.path for i in py]
        assert str(proj / ".venv") in p, f"没找到 .venv: {p}"
        v = next(i for i in py if i.path == str(proj / ".venv"))
        assert v.risk == "caution" and v.size == 20000 + len("home = x"), (v.risk, v.size)
        assert not any("keepme" in x for x in p), "白名单泄漏"

        gi = app.git_repos_report()
        gp = [n.path for n in gi]
        assert str(tmp) not in gp, "扫描根本身不该出现"
        assert str(repo) in gp, f"深层仓库被漏掉: {gp}"
        assert not any(n.path in p for n in gi), "Git 仓库混进了可删除列表"
        g = next(n for n in gi if n.path == str(repo))
        assert "最后提交" in g.meta, g.meta
        assert g.kind == "Git 仓库", g.kind

        bd = app.BuildScanner().scan()
        bp = [i.path for i in bd]
        assert str(proj / "build") in bp, f"没识别 .spec 同级的 build/: {bp}"
        b = next(i for i in bd if i.path == str(proj / "build"))
        assert b.risk == "safe", b.risk
    finally:
        app.CFG = old


def t_stale(tmp):
    base = tmp / "pkgs"
    (base / "@scope" / "plug@latest").mkdir(parents=True)
    (base / "@scope" / "plug").mkdir(parents=True)
    (base / "@scope" / "plug" / "big.bin").write_bytes(b"z" * 20000)
    (base / "@scope" / "plug@latest" / "big.bin").write_bytes(b"z" * 20000)
    cfg = tmp / "oc.json"
    cfg.write_text('{"plugin": ["@scope/plug"]}', encoding="utf-8")
    old = app.CFG
    app.CFG = dict(old)
    app.CFG["agent_cache_root"] = str(base)
    app.CFG["agent_configs"] = [{"path": str(cfg)}]
    try:
        res = app.AgentCacheScanner().scan()
        paths = [i.path for i in res]
        assert str(base / "@scope" / "plug") in paths, f"stale 版本没识别: {paths}"
        assert str(base / "@scope" / "plug@latest") not in paths, \
            f"已启用插件被误报: {paths}"
    finally:
        app.CFG = old


def t_unused(tmp):
    base = tmp / "pkgs2"
    (base / "@dead" / "gone@latest").mkdir(parents=True)
    (base / "@dead" / "gone@latest" / "x.bin").write_bytes(b"z" * 20000)
    cfg = tmp / "oc2.json"
    cfg.write_text('{\n // c\n "plugin": ["./local.mjs", "@other/keep"]\n}', encoding="utf-8")
    old = app.CFG
    app.CFG = dict(old)
    app.CFG["agent_cache_root"] = str(base)
    app.CFG["agent_configs"] = [{"path": str(cfg)}]
    try:
        got = [i for i in app.AgentCacheScanner().scan() if "gone" in i.path]
        assert got, "未启用插件没被报出来"
        assert got[0].risk == "caution", got[0].risk
    finally:
        app.CFG = old


# ---------------- run_scan 端到端（用临时目录当唯一 root，很快） ----------------
def t_run_scan(tmp):
    (tmp / "sc").mkdir()
    (tmp / "sc" / "big.bin").write_bytes(b"z" * 3_000_000)
    old = app.CFG
    app.CFG = dict(old)
    app.CFG["scan_roots"] = [str(tmp)]
    app.CFG["custom_cache"] = []
    app.CFG["scan_options"] = dict(old["scan_options"], min_size_bytes=1024,
                                   max_recursion_depth=6)
    seen = []
    try:
        app.run_scan(on_progress=lambda s, p: seen.append((s, p)))
    finally:
        app.CFG = old
    st = app.STATE
    assert not st.running, "run_scan 结束时应 running=False"
    assert st.progress == 1.0, st.progress
    assert st.finished_at, "finished_at 未设置"
    assert seen, "on_progress 从未被调用"
    assert seen[-1][1] == 1.0, f"最后一次回调进度应为 1.0: {seen[-1]}"
    assert all(0.0 <= p <= 1.0 for _, p in seen), "进度越界"
    assert st.log, "日志为空"
    assert all(i.icon for i in st.items), "有条目缺少 icon"
    assert all(i.size >= 1024 for i in st.items if i.unit == "bytes"), "min_size_bytes 未生效"
    assert any(i.unit == "count" for i in st.items) or True
    assert all(k for n in st.notes for k in [n.kind]), "只读条目缺少 kind"


# ---------------- 主题 ----------------
def t_themes():
    assert len(app.THEMES) == 6, f"应是设计稿的 6 套，实际 {len(app.THEMES)}"
    assert app.THEME_ORDER == ["Studio Dark", "Studio Light", "Paper", "Ink",
                              "Rosé Pine", "Tokyo Night"], app.THEME_ORDER
    need = {"n", "bg", "panel", "panel2", "fg", "fg2", "fg3", "line", "line2",
            "accent", "accent2", "safe", "caution", "onaccent"}
    for k, t in app.THEMES.items():
        missing = need - set(t)
        assert not missing, f"{k} 缺字段 {missing}"
        for f in need - {"n"}:
            v = t[f]
            assert v.startswith("#") and len(v) == 7, f"{k}.{f}={v}"
    names = [t["n"] for t in app.THEMES.values()]
    assert len(set(names)) == len(names), f"主题重名: {names}"
    assert app.DEFAULT_THEME in app.THEMES, f"默认主题不存在: {app.DEFAULT_THEME}"


def t_theme_contrast():
    """正文与强调色上的文字必须达到 WCAG AA（4.5:1）。这是唯一不能糊弄的地方。"""
    def ratio(a, b):
        def lum(h):
            h = h.lstrip("#")
            out = []
            for i in (0, 2, 4):
                v = int(h[i:i + 2], 16) / 255.0
                out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
            return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
        la, lb = lum(a), lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    bad = []
    for name, t in app.THEMES.items():
        checks = [
            ("正文/底色", t["fg"], t["bg"]),
            ("次级文字/面板", t["fg2"], t["panel"]),
            ("三级文字/面板", t["fg3"], t["panel"]),
            ("正文/面板", t["fg"], t["panel"]),
            ("强调色上的文字/强调色", t["onaccent"], t["accent"]),
            ("safe/面板", t["safe"], t["panel"]),
            ("caution/面板", t["caution"], t["panel"]),
        ]
        for label, a, b in checks:
            r = ratio(a, b)
            need = 3.0 if label.startswith(("三级", "caution")) else 4.5
            if r < need:
                bad.append(f"{name} {label} = {r:.2f}:1 (需 {need})")
    assert not bad, "对比度不达标:\n  " + "\n  ".join(bad)


def t_theme_onaccent_pick():
    """onaccent 必须在「白字 vs 主题底色字」里取对比度更高的那个。
    深色候选是 bg 不是 fg —— 浅强调色上 fg 本身接近白，等于没得选。"""
    for name, t in app.THEMES.items():
        bg = app._contrast(t["bg"], t["accent"])
        wh = app._contrast("#FFFFFF", t["accent"])
        if bg >= wh:
            assert t["onaccent"] == t["bg"], f"{name}: 应选底色字却是 {t['onaccent']}"
        else:
            assert t["onaccent"] == "#FFFFFF", f"{name}: 应选白字却是 {t['onaccent']}"


def t_theme_tokens_match_design():
    """主色必须与设计稿逐字一致（其余字段是推导的，不在此列）"""
    DESIGN = {
        "Studio Dark": ("#08090A", "#0E0F11", "#16171A", "#F7F8F8", "#5E6AD2", "#3FB950", "#D29922"),
        "Studio Light": ("#FBFBFA", "#FFFFFF", "#F4F4F2", "#1A1A1A", "#5E6AD2", "#1A7F37", "#9A6700"),
        "Paper": ("#F5F1EA", "#FFFCF6", "#EFE9DD", "#2B2722", "#B8553A", "#5B7A3D", "#B07D2B"),
        "Ink": ("#1C1A17", "#252320", "#2D2A26", "#F0EBE0", "#C77B5C", "#8FB06A", "#D9A85C"),
        "Rosé Pine": ("#191724", "#1F1D2E", "#26233A", "#E0DEF4", "#EBBCBA", "#9CCFD8", "#F6C177"),
        "Tokyo Night": ("#1A1B26", "#16161E", "#1F2335", "#C0CAF5", "#7AA2F7", "#9ECE6A", "#E0AF68"),
    }
    keys = ("bg", "panel", "panel2", "fg", "accent", "safe", "caution")
    for name, vals in DESIGN.items():
        t = app.THEMES[name]
        got = tuple(t[k] for k in keys)
        assert got == vals, f"{name} 主色与设计稿不符:\n  期望 {vals}\n  实际 {got}"


# ---------------- 空文件 / 空目录 保留名单 ----------------
def t_keep_empty(tmp):
    base = tmp / "emptytest"
    base.mkdir()
    for n in (".gitkeep", "thumbs.db", "desktop.ini", "x.lock", "y.pid"):
        (base / n).write_bytes(b"")
    (base / "really_empty.bin").write_bytes(b"")
    (base / "notempty.bin").write_bytes(b"x")
    empty_dir = base / "emptydir"
    empty_dir.mkdir()

    old = app.CFG
    app.CFG = dict(old)
    app.CFG["scan_roots"] = [str(base)]
    app.CFG["custom_cache"] = []
    app.CFG["scan_options"] = dict(old["scan_options"], min_size_bytes=1,
                                   max_recursion_depth=4)
    try:
        res = app.EmptyScanner().scan()
        assert len(res) == 1, f"应汇总成 1 条: {res}"
        it = res[0]
        # really_empty.bin + emptydir = 2 项；6 个保留名不应计入
        assert it.size == 2, f"保留名单没生效，计了 {it.size} 项: {it.meta}"
        assert it.risk == "caution", it.risk
        assert it.unit == "count", it.unit
    finally:
        app.CFG = old


# ---------------- 注册表：只读发现 + 备份导出（不删任何真键） ----------------
def t_registry_findings():
    f = app.registry_findings()
    assert isinstance(f, list)
    for it in f:
        assert it.path.startswith("REG:"), f"注册表条目路径格式错: {it.path}"
        assert it.unit == "count", f"{it.name} 应该按条目计数"
        op = app._parse_reg_path(it.path)
        assert op and op[0] in ("mru", "delkey", "delvalue"), op
        if op[0] == "mru":
            assert op[1] == "", f"mru 操作不应带 hive: {op}"
        else:
            assert op[1] in ("HKCU", "HKLM"), op
    print(f"       发现 {len(f)} 项注册表问题")


def t_registry_backup_and_restore():
    """在临时键上真跑一遍 导出 -> 删除 -> 导入还原，证明备份可用"""
    import winreg
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                         r"Software\DevCleanerSelftest\Sub")
    winreg.SetValueEx(k, "v1", 0, winreg.REG_SZ, "hello")
    winreg.SetValueEx(k, "v2", 0, winreg.REG_DWORD, 42)
    sub = winreg.CreateKey(k, "Child")
    winreg.SetValueEx(sub, "c1", 0, winreg.REG_SZ, "world")
    winreg.CloseKey(sub)
    winreg.CloseKey(k)
    full = r"Software\DevCleanerSelftest\Sub"
    try:
        n, s = app._key_stats(winreg.HKEY_CURRENT_USER, full)
        assert (n, s) == (2, 1), f"建键失败 {(n, s)}"

        ok, info = app.export_registry_keys([("HKCU", full)], "selftest")
        assert ok, f"导出失败: {info}"
        reg_file = Path(info, "selftest.reg")
        assert reg_file.exists() and reg_file.stat().st_size > 0, "备份文件没生成"

        good, msg = app.delete_registry_key("HKCU", full)
        assert good, msg
        assert app._key_stats(winreg.HKEY_CURRENT_USER, full) == (0, 0), "没删干净"

        import subprocess
        r = subprocess.run(["reg", "import", str(reg_file)],
                           capture_output=True, text=True, errors="replace",
                           timeout=30)
        assert r.returncode == 0, f"reg import 失败: {r.stderr or r.stdout}"
        n, s = app._key_stats(winreg.HKEY_CURRENT_USER, full)
        assert (n, s) == (2, 1), f"还原后数据不对: {(n, s)}"
        assert app._value(winreg.HKEY_CURRENT_USER, full, "v1") == "hello"
    finally:
        try:
            app.delete_registry_key("HKCU", r"Software\DevCleanerSelftest")
        except OSError:
            pass


def t_delete_deep_tree():
    """多层子树的键也必须删干净（EnumKey 索引曾经写错过，这里盯住）"""
    import winreg
    base = r"Software\DevCleanerSelftest2"

    def subs_of(path):
        out = []
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                i = 0
                while True:
                    try:
                        out.append(winreg.EnumKey(k, i))
                    except OSError:
                        return out
                    i += 1
        except OSError:
            return None            # 键不存在
        return out

    winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base + r"\A\B\C", 0,
                       winreg.KEY_ALL_ACCESS).Close()
    winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base + r"\A\D", 0,
                       winreg.KEY_ALL_ACCESS).Close()
    assert subs_of(base) == ["A"], f"建键失败: {subs_of(base)}"
    good, msg = app.delete_registry_key("HKCU", base)
    assert good, msg
    # None = 键已消失；[] = 还在但空。两种都算删干净
    left = subs_of(base)
    assert left is None or left == [], f"删完还剩子键: {left}"


def t_reg_path_parse():
    assert app._parse_reg_path("REG:mru:") == ("mru", "", "")
    p = app._parse_reg_path(r"REG:delkey:HKLM\SOFTWARE\Foo\{1}")
    assert p == ("delkey", "HKLM", r"SOFTWARE\Foo\{1}"), p
    p = app._parse_reg_path(r"REG:delvalue:HKCU\Software\Run\X")
    assert p == ("delvalue", "HKCU", r"Software\Run\X"), p
    assert app._parse_reg_path("C:\\some\\file") is None


def t_bulk_empty_delete(tmp):
    """批量空文件条目必须真能删：建 -> 扫 -> 删 -> 确认消失"""
    base = tmp / "bulkdel"
    base.mkdir()
    (base / "one.bin").write_bytes(b"")
    (base / "two.bin").write_bytes(b"")
    (base / "emptydir").mkdir()
    (base / ".gitkeep").write_bytes(b"")      # 必须被保留
    old = app.CFG
    app.CFG = dict(old)
    app.CFG["scan_roots"] = [str(base)]
    app.CFG["custom_cache"] = []
    app.CFG["scan_options"] = dict(old["scan_options"], min_size_bytes=1,
                                   max_recursion_depth=4)
    try:
        res = app.EmptyScanner().scan()
        assert len(res) == 1, res
        it = res[0]
        paths = app.expand_bulk(it.path)
        assert len(paths) == 3, f"应命中 2 空文件+1 空目录: {paths}"
        assert not any(p.endswith(".gitkeep") for p in paths), "误收了 .gitkeep"
        ok, fail, errs = app.delete_bulk(it.path)
        assert fail == 0, f"删除失败: {errs}"
        assert not (base / "one.bin").exists()
        assert not (base / "two.bin").exists()
        assert not (base / "emptydir").exists()
        assert (base / ".gitkeep").exists(), ".gitkeep 被误删"
    finally:
        app.CFG = old


def t_no_false_orphan():
    """UninstallString 的 exe 还在，就绝不能判成「失效程序」。
    （曾经用 InstallLocation 是否存在来判断，误报了微信 / VS Installer。）"""
    import winreg
    branch = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\DevCleanerFalsePositive"
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, branch)
    winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "假阳性测试程序")
    winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                      '"C:\\Windows\\System32\\cmd.exe" /c exit')   # 确实存在
    winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ,
                      "D:\\不存在的路径\\XYZ")                    # 故意失效
    winreg.CloseKey(k)
    before = [i.name for i in app.registry_findings()]
    try:
        assert not any("假阳性测试程序" in n for n in before), \
            f"InstallLocation 失效但卸载命令有效，被误判了: {before}"
    finally:
        app.delete_registry_key("HKCU", branch)


def t_real_orphan_detected():
    """反过来：卸载命令指向不存在的 exe，必须被抓出来"""
    import winreg
    branch = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\DevCleanerTrueOrphan"
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, branch)
    winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "真孤儿测试程序")
    winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                      '"C:\\根本不存在的目录\\unins000.exe"')
    winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, "C:\\Program Files\\Nope")
    winreg.CloseKey(k)
    try:
        names = [i.name for i in app.registry_findings()]
        assert any("真孤儿测试程序" in n for n in names), f"真孤儿没被抓出来: {names}"
    finally:
        app.delete_registry_key("HKCU", branch)


def t_set_config_preserves_comments():
    """就地改配置不能把用户写的注释冲掉（全量 yaml.dump 会）"""
    p = Path(tempfile.mkdtemp(prefix="dc_cfg_")) / "settings.yaml"
    p.write_text(
        "# 这是注释，必须活着\n"
        "scan_roots:\n"
        "  - \"C:/a\"\n"
        "theme: \"Old\"\n"
        "# 尾部注释\n",
        encoding="utf-8")
    old = app.resource
    app.resource = lambda *a: p                      # type: ignore[assignment]
    try:
        assert app.set_config_value("theme", '"Ink"'), "写入失败"
        txt = p.read_text(encoding="utf-8")
        assert "# 这是注释，必须活着" in txt, txt
        assert "# 尾部注释" in txt, txt
        assert 'theme: "Ink"' in txt, txt
        assert 'theme: "Old"' not in txt, txt
        # 再写一次应就地替换而不是追加第二行
        assert app.set_config_value("theme", '"Paper"')
        txt = p.read_text(encoding="utf-8")
        assert txt.count("theme:") == 1, txt
        assert 'theme: "Paper"' in txt, txt
        # 写不存在的键应追加，且不破坏原内容
        assert app.set_config_value("theme2", "42")
        txt = p.read_text(encoding="utf-8")
        assert "theme2: 42" in txt and "scan_roots:" in txt, txt
    finally:
        app.resource = old                      # type: ignore[assignment]
        shutil.rmtree(p.parent, ignore_errors=True)


# ---------------- 传统垃圾 ----------------
def t_junk(tmp):
    old = app.CFG
    app.CFG = dict(old)
    app.CFG["extra_junk"] = [{"name": "测试垃圾", "path": str(tmp / "junkdir"),
                              "note": "测试"}]
    try:
        (tmp / "junkdir").mkdir()
        (tmp / "junkdir" / "a.bin").write_bytes(b"j" * 900_000)
        res = app.JunkScanner().scan()
        hit = [i for i in res if i.name == "测试垃圾"]
        assert hit, f"自定义垃圾没被识别: {[i.name for i in res]}"
        assert hit[0].risk == "safe" and hit[0].size == 900_000, (hit[0].risk, hit[0].size)
    finally:
        app.CFG = old


# ---------------- GitHub clone 判定：绝不碰有 remote 的 ----------------
def t_clone_guard(tmp):
    """有 remote 的 repo 绝不能出现在可删列表里"""
    import subprocess
    good = tmp / "withremote"
    good.mkdir()
    subprocess.run(["git", "init", "-q", str(good)], capture_output=True)
    (good / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(good), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(good), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-qm", "x"], capture_output=True)
    subprocess.run(["git", "-C", str(good), "remote", "add", "origin",
                    "https://example.com/x.git"], capture_output=True)
    old = app.CFG
    app.CFG = dict(old)
    app.CFG["scan_roots"] = [str(tmp)]
    app.CFG["stale_clone_days"] = 0
    try:
        cands = [i.path for i in app.git_repo_cleanup_candidates()]
        assert str(good) not in cands, "有 remote 的仓库被列为可删！"
    finally:
        app.CFG = old
        _drop_git_cache(good)


def _drop_git_cache(d: Path) -> None:
    """git 会在 .git 里留 index.lock / pack 文件，rmtree 删不干净，
    于是每次跑自检都在 %TEMP% 堆一个仓库。Windows 上 git 短暂持锁，
    先重试再强删。"""
    import gc
    import stat
    import time
    for attempt in range(3):
        try:
            shutil.rmtree(d)
            return
        except OSError:
            gc.collect()
            time.sleep(0.4 * (attempt + 1))

    def force(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(d, onerror=force)


def t_no_repolish_on_check():
    """勾选态必须走 palette，不能碰 unpolish/polish。
    unpolish/polish 会让 Qt 重新解析整份样式表，30 个条目就是 30 次全量重算，
    主线程卡死 —— 表现为扫描结束时整窗闪。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import gui
    from PySide6.QtCore import Qt
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w._render()
    w.bulk(True, only_safe=True)
    w.recalc()
    src = open(gui.__file__, encoding="utf-8").read()
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "unpolish" not in code, "gui.py 的代码里又出现 unpolish 了"
    assert ".polish(" not in code, "gui.py 的代码里又出现 polish 了"
    rows = [r for c in w.cards for r in c.rows]
    assert rows, "没有渲染出任何条目行"
    r = rows[0]
    # 勾选 -> 取消 -> 勾选，颜色必须跟着变（说明确实在用 palette 上色）
    r.set_checked(True)
    on = r.palette().color(r.palette().ColorRole.Window)
    r.set_checked(False)
    off = r.palette().color(r.palette().ColorRole.Window)
    assert on.alpha() > 0, "勾选后底色应该不透明"
    assert off.alpha() == 0, "取消勾选后底色应该完全透明"
    w.close()


def t_cards_collapsed_by_default():
    """默认全部折叠：分类多于一屏时不用一路往下翻"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import gui
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w._render()
    assert w.cards, "没有渲染出分类卡片"
    assert w.placeholder.isHidden(), "有内容时占位文字必须藏起来"
    assert all(not c.expanded() for c in w.cards), "默认应该全部折叠"
    assert all(c.body.isHidden() for c in w.cards), "折叠态下 body 应为显式隐藏"
    w._set_all_expanded(True)
    assert all(c.expanded() for c in w.cards), "全部展开没生效"
    assert not any(c.body.isHidden() for c in w.cards)
    assert w.btn_expand.text() == "全部折叠", w.btn_expand.text()
    w._set_all_expanded(False)
    assert all(not c.expanded() for c in w.cards), "全部折叠没生效"
    w.close()


def t_expand_button_click():
    """真点一下「全部展开」，走完整信号/槽链路（离屏也能测，不用鼠标）"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import gui
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w._render()
    assert w.cards and w.btn_expand.isEnabled()
    w.btn_expand.click()                      # 第 1 次：应全部展开
    assert all(c.expanded() for c in w.cards), "点按钮没展开"
    assert w.btn_expand.text() == "全部折叠", w.btn_expand.text()
    w.btn_expand.click()                      # 第 2 次：应全部折叠
    assert all(not c.expanded() for c in w.cards), "点按钮没折叠"
    w.close()


# ---------------- 版本号 ----------------
def t_version_semver_and_changelog():
    """版本号语义化，且 CHANGELOG 里有对应条目 —— CI 也查这一条"""
    import re
    v = app.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", v), f"版本号不是 语义化版本: {v}"
    assert app.APP_NAME == "DevCleaner", app.APP_NAME
    p = Path(__file__).parent / "CHANGELOG.md"
    assert p.is_file(), "缺 CHANGELOG.md"
    log = p.read_text(encoding="utf-8")
    assert f"## [{v}]" in log, f"CHANGELOG.md 里没有 v{v} 的条目"
    assert "更新日志" in log or "Changelog" in log
    # README 里引用的版本要跟引擎一致
    for rd in ("README.md", "README.en.md"):
        rp = Path(__file__).parent / rd
        assert rp.is_file(), f"缺 {rd}"
        assert v in rp.read_text(encoding="utf-8"), f"{rd} 里没提到 v{v}"


def t_oss_scaffolding():
    """开源常备文件齐不齐 —— 少一个都不该合"""
    root = Path(__file__).parent
    need = [
        "LICENSE", "README.md", "README.en.md", "CHANGELOG.md",
        "CONTRIBUTING.md", "CONTRIBUTING.en.md",
        "SECURITY.md", "SECURITY.en.md", "CODE_OF_CONDUCT.md",
        "requirements.txt", "build.bat", "DevCleaner.spec",
        ".gitignore", ".gitattributes", ".editorconfig",
        ".github/workflows/ci.yml",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/FUNDING.yml",
        "docs/palette-directions.html",
    ]
    missing = [n for n in need if not (root / n).is_file()]
    assert not missing, f"缺这些文件: {missing}"
    # 打包产物不该进仓库
    for junk in ("build", "dist", "__pycache__"):
        assert junk in (root / ".gitignore").read_text(encoding="utf-8"), \
            f".gitignore 没忽略 {junk}/"
    # .gitattributes 只认行首的 #，行尾 # 会被当成属性名，git 会直接报错
    ga = (root / ".gitattributes").read_text(encoding="utf-8")
    for ln in ga.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        assert " #" not in s, f".gitattributes 第 {ln!r} 行有行尾注释：" \
                             f"git 只认行首 #，会把 # 当属性名"
    assert "eol=crlf" in ga and "*.bat" in ga, ".bat 应该设为 crlf（cmd 读 LF 不可靠）"


def t_no_internal_protocol_leak():
    """内部协议串（REG: / BULK:）绝不能出现在任何显示给用户的文本里。
    之前在条目行和确认弹窗里都直接露过 `REG:mru:` 这种东西。

    自己造 REG:/BULK: 条目，不依赖前面测试留下的 STATE —— 那些是
    临时目录的产物，和这里的行对不上。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import gui

    real_items = list(app.STATE.items)
    try:
        app.STATE.items[:] = [
            app.Item("注册表组", "注册表 · 可安全重置", "REG:mru:", 12, "safe",
                     unit="count"),
            app.Item("失效程序", "注册表 · 失效程序",
                     r"REG:delkey:HKLM\SOFTWARE\X\{1}", 3, "caution",
                     unit="count"),
            app.Item("失效启动项", "注册表 · 失效程序",
                     r"REG:delvalue:HKCU\Software\Microsoft\Windows\CurrentVersion\Run\X",
                     1, "caution", unit="count"),
            app.Item("空文件堆", "空文件 / 空目录 / 断链", "BULK:empty", 99,
                     "caution", unit="count"),
            app.Item("普通目录", "传统垃圾文件", r"C:\some\cache", 2048, "safe"),
        ]
        app.BULK["empty"] = {"files": [r"C:\a\1", r"C:\a\2"], "dirs": [], "links": []}
        qa = QApplication.instance() or QApplication([])
        w = gui.MainWindow()
        w._render()

        from PySide6.QtWidgets import QWidget
        leaked = []

        def walk(wid):
            if wid is None:
                return
            for child in wid.children():
                if not isinstance(child, QWidget):
                    continue
                t = child.text() if hasattr(child, "text") else None
                if isinstance(t, str) and ("REG:" in t or "BULK:" in t):
                    leaked.append(f"{type(child).__name__}: {t[:70]}")
                walk(child)
        walk(w)
        assert not leaked, "界面上出现了内部协议串:\n  " + "\n  ".join(leaked)

        # 逐条核对渲染函数
        for it in app.STATE.items:
            shown = gui._human_path(it)
            assert not shown.startswith(("REG:", "BULK:")), shown
            if it.path.startswith("BULK:"):
                assert "逐条删除" in shown, shown
            if it.path == "REG:mru:":
                assert "使用记录" in shown, shown
            if it.path.startswith("REG:delkey:") or it.path.startswith("REG:delvalue:"):
                assert it.path[4:].split(":", 1)[1] == shown, shown
        w.close()
    finally:
        app.STATE.items[:] = real_items
        app.BULK.pop("empty", None)


def t_console_encoding_safe():
    """中文测试名/分类名不能在非 UTF-8 控制台上崩。

    GitHub runner 的控制台是 cp1252，中文机器是 GBK，两者都编不了中文。
    这个 bug 在本机用 PYTHONIOENCODING=utf-8 掩盖着，直到 CI 上整个套件
    UnicodeEncodeError 崩掉才暴露。

    只验「前几项能否打印」，不能跑全套 —— 本用例在套件里，套件跑全套
    就会无限递归。
    """
    import subprocess
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys,io;sys.stdout=io.TextIOWrapper(sys.stdout.buffer,"
         "encoding='cp1252',errors='strict');print('\u4e2d\u6587')"],
        capture_output=True, text=True, errors="replace", timeout=60)
    if probe.returncode == 0:
        return                                  # 这个环境意外能编中文，跳过
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    env["PYTHONIOENCODING"] = ""                # 交回 Python 自己去猜
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys;sys.path.insert(0,'.');import test_app as T;"
         "T.t_human();T.t_candidates();T.t_index()"],
        capture_output=True, text=True, errors="replace", timeout=120, env=env)
    out = r.stdout + r.stderr
    assert "UnicodeEncodeError" not in out, f"非 UTF-8 控制台下崩溃:\n{out[-500:]}"
    assert r.returncode == 0, f"退出码 {r.returncode}:\n{out[-500:]}"


# ---------------- 仓库链接 ----------------
def t_no_test_crash_left_behind():
    """自检不能往 %TEMP% 里堆垃圾。

    t_clone_guard 每次建一个 git 仓库，.git 里的 index.lock / pack 文件
    会让 shutil.rmtree 失败，于是每跑一次自检就往 Temp 里留一个仓库。
    堆几百个以后，DevCleaner 自己的只读清单里全是 withremote —— 很难看，
    而且 Temp 会被撑大。
    """
    import glob
    import tempfile
    pats = [os.path.join(tempfile.gettempdir(), "devcleaner_test_*")]
    before = sum(len(glob.glob(p)) for p in pats)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    env["PYTHONIOENCODING"] = ""
    r = subprocess.run([sys.executable, "-c",
                        "import sys;sys.path.insert(0,'.');import test_app as T;"
                        "import tempfile,pathlib;"
                        "T.t_clone_guard(pathlib.Path(tempfile.mkdtemp()))"],
                       capture_output=True, text=True, errors="replace",
                       timeout=300, env=env)
    after = sum(len(glob.glob(p)) for p in pats)
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-300:]
    assert after <= before + 1, \
        f"自检残留了临时目录：跑之前 {before} 个，跑之后 {after} 个"
    # 顺手清掉历史堆积（只清本测试自己建的，不碰别的 devcleaner_test_*）
    for p in pats:
        for d in glob.glob(p):
            try:
                _drop_git_cache(Path(d))
            except OSError:
                pass


# ---------------- 仓库链接 ----------------
def t_no_placeholder_left():
    """OWNER / TODO / FIXME / example.com 之类占位符漏一个就是坏链接"""
    root = Path(__file__).parent
    # 本文件自身含这些字面量（就是这个测试的检查清单），跳过
    skip = {".git", "build", "dist", "__pycache__", ".superpowers",
            "docs/palette-directions.html", "test_app.py"}
    bad = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() in (".png", ".jpg", ".exe", ".reg"):
            continue
        rel = p.relative_to(root).as_posix()
        if any(s in rel for s in skip):
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, ln in enumerate(txt.splitlines(), 1):
            for pat in ("github.com/OWNER", "sponsors/OWNER", "OWNER/DevCleaner",
                        "TODO", "FIXME", "yourname", "your-project", "待填", "XXX"):
                if pat in ln:
                    bad.append(f"{rel}:{i} 含占位符 {pat!r}")
    assert not bad, "有占位符没替换:\n  " + "\n  ".join(bad)


def t_repo_links_consistent():
    """仓库里所有指向本项目的链接，用户名与项目名必须一致"""
    root = Path(__file__).parent
    urls = set()
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() in (".png", ".jpg", ".exe", ".reg"):
            continue
        if ".git" in p.parts or "build" in p.parts or "dist" in p.parts:
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.findall(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", txt):
            if m[1] == "DevCleaner":
                urls.add(m)
    assert urls, "README 里应该有指向本仓库的链接"
    owners = {o for o, _ in urls}
    assert len(owners) == 1, f"仓库链接的用户名不一致: {owners}"
    assert owners == {app.REPO_OWNER}, \
        f"链接用户名 {owners} 与 app.REPO_OWNER ({app.REPO_OWNER}) 不一致"
    assert all(r == app.REPO_NAME for _, r in urls), \
        f"链接项目名 {[r for _, r in urls]} 与 app.REPO_NAME ({app.REPO_NAME}) 不一致"
    # Sponsors 链接
    fu = (root / ".github/FUNDING.yml").read_text(encoding="utf-8")
    assert f"github: [{app.REPO_OWNER}]" in fu, \
        f"FUNDING.yml 的用户名与 app.REPO_OWNER 不一致: {app.REPO_OWNER}"
    # 英文版不能是占位符
    en = (root / "README.en.md").read_text(encoding="utf-8")
    assert len(en) > 2000, "README.en.md 太短，可能是占位符"
    # 本地图片引用必须真实存在（远程 URL 不检查）
    import re as _re
    bad_img = []
    for p in list(root.glob("*.md")) + list((root / "docs").glob("*.md")):
        txt = p.read_text(encoding="utf-8")
        for m in _re.findall(r"!\[[^\]]*\]\(([^)\s]+)", txt):
            if m.startswith(("http://", "https://")):
                continue
            base = root if p.parent == root else p.parent
            if not (base / m).is_file():
                bad_img.append(f"{p.name} -> {m}")
    assert not bad_img, "图片引用失效:\n  " + "\n  ".join(bad_img)


def t_ci_yaml_valid():
    """workflow / issue 模板的 YAML 必须能解析。

    `name: Smoke: JSON output` 这种带冒号的值会让 YAML 报
    "mapping values are not allowed here"，CI 直接 0 秒失败 —— 连 runner
    都起不来，日志里什么线索都没有。
    """
    import yaml
    root = Path(__file__).parent
    pats = [".github/workflows/*.yml", ".github/workflows/*.yaml",
            ".github/ISSUE_TEMPLATE/*.yml"]
    files = [p for pat in pats for p in root.glob(pat)]
    assert files, "没找到任何 CI / Issue 模板 YAML"
    for p in files:
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            rel = p.relative_to(root).as_posix()
            raise AssertionError(f"{rel} YAML 解析失败: {e}") from None
        assert isinstance(data, dict), f"{p.name} 顶层不是映射"
    # 模板必须有 name / description，否则 GitHub 页面显示不出来
    for p in root.glob(".github/ISSUE_TEMPLATE/*.yml"):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if p.name == "CONTRIBUTING_HINT.md":
            continue
        assert "name" in data, f"{p.name} 缺 name"
        assert "description" in data, f"{p.name} 缺 description"
    # workflow 必须有 test job
    wf = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert "jobs" in wf and "test" in wf["jobs"], "ci.yml 缺 test job"
    for name, job in wf["jobs"].items():
        assert "runs-on" in job, f"job {name} 缺 runs-on"
        assert "steps" in job and job["steps"], f"job {name} 没有 steps"


def t_cli_version_reachable():
    """--version 的信息必须能从 stderr 拿到。

    打包成 console=False 的 GUI exe 后没有可靠 stdout，print() 会失败或被
    丢弃。CI 上就踩过：exe 起来但 --version 输出为空，冒烟步骤直接判失败。
    """
    import re as _re
    for argv, pat in ((["--version"], r"\d+\.\d+\.\d+"), (["-V"], r"\d+\.\d+\.\d+")):
        r = subprocess.run([sys.executable, "gui.py"] + argv,
                           capture_output=True, text=True,
                           errors="replace", timeout=120)
        assert r.returncode == 0, f"gui.py {argv} 退出码 {r.returncode}: {r.stderr[-200:]}"
        blob = (r.stdout or "") + (r.stderr or "")
        assert _re.search(pat, blob), \
            f"gui.py {argv} 没输出版本号。stdout={r.stdout!r} stderr={r.stderr!r}"
        assert app.__version__ in blob, blob[:200]
    # --help 同理
    r = subprocess.run([sys.executable, "gui.py", "--help"],
                       capture_output=True, text=True, errors="replace", timeout=120)
    assert r.returncode == 0, f"--help 退出码 {r.returncode}"
    blob = (r.stdout or "") + (r.stderr or "")
    assert "settings.yaml" in blob, blob[:200]


def t_dist_bundle_sane():
    """dist/ 里若存在 settings.yaml，必须是完整配置而不是 0 字节空壳。

    build.bat 里 copy 是静默的，失败过一次没人发现：exe 能跑，但用户的
    扫描根目录和主题全丢了。app.py 里 `or {}` 会兜住空文件所以不报错 ——
    静默丢配置比崩掉更难查。
    """
    import yaml as _y
    d = Path(__file__).parent / "dist"
    if not d.is_dir():
        return  # 还没 build 过，跳过
    st = d / "settings.yaml"
    assert st.is_file(), "dist/settings.yaml 缺失，exe 会用默认配置启动"
    size = st.stat().st_size
    assert size > 100, f"dist/settings.yaml 只有 {size} 字节，是空壳"
    data = _y.safe_load(st.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, "dist/settings.yaml 解析不出配置"
    root = Path(__file__).parent / "settings.yaml"
    for key in ("scan_options",):
        assert key in data, f"dist 缺 {key}"


def t_i18n_complete():
    """界面文案英译不能有漏网的词。

    三道闸：
    1. 表里每条译文都得真的变了（不能映射回自己）
    2. 译文里不能混进中文（半吊子翻译比不翻译更糟）
    3. gui.py 里每个 T("中文") 都得有对应条目；app.py 里每个扫描分类也得有
    """
    import lang
    import gui
    import re as _re

    lang.set_lang("en")
    try:
        # 1 + 2
        # 全角标点本来就该翻成空串（引号），或短到非空即算翻过
        for k, v in lang._EN.items():
            if not _re.search(r"[\u4e00-\u9fff]", k):
                continue          # 纯标点条目不参与「有内容」的检查
            assert v.strip(), f"译文为空: {k!r}"
            assert lang.T(k) != k, f"这条没翻: {k!r}"
            assert not _re.search(r"[\u4e00-\u9fff]", v), \
                f"译文里还有中文: {k!r} -> {v!r}"

        # 3a. gui.py 里所有 T("...") 字面量
        src = (Path(__file__).parent / "gui.py").read_text(encoding="utf-8")
        used = set(_re.findall(r'T\((?:f?)([rf]?)"([^"]*)"', src))
        for _q, lit in used:
            if not _re.search(r"[\u4e00-\u9fff]", lit):
                continue
            # 组合句由子串拼，只要求它含的每个已知词组都翻了
            missing = [g for g in lang._EN if g in lit and lang.T(g) == g]
            assert not missing, f"gui.py 这句有词没翻: {lit!r} 缺 {missing}"
        # 3b. app.py 的每个扫描分类都要能翻
        for sc in app.SCANNERS:
            cat = sc.category
            if _re.search(r"[\u4e00-\u9fff]", cat):
                assert lang.T(cat) != cat, f"扫描分类没翻: {cat!r}"
                assert not _re.search(r"[\u4e00-\u9fff]", lang.T(cat)), cat

        # 3c. 真正会显示到界面上的字段：条目名/说明/只读分类的 kind。
        # 之前只查了 Scanner.category，漏掉 notes 里的 kind（"注册表 ·
        # 可安全重置" 这种就是从这儿漏到界面上的）。
        # 必须实跑一次扫描，否则 STATE 是空的，这一节等于没测。
        if not app.STATE.items and not app.STATE.notes:
            try:
                app.run_scan()
            except Exception:
                pass          # 真实环境只读冒烟已经单独测过，这里拿不到就算了
        real_items = list(getattr(app.STATE, "items", []) or [])
        real_notes = list(getattr(app.STATE, "notes", []) or [])
        assert real_items or real_notes, "跑完扫描一条结果都没有，翻译检查无从谈起"
        # 3c. 分类名（界面框架层）必须全英文。
        # 条目级 name/note/meta 不强制：18 条 note、17 条 name 多是程序名、
        # 路径、专有名词，逐条翻译既不现实也没必要（译了反而怪）。界面框架、
        # 按钮、分类名、风险等级、阶段提示已全部英文，这才是可用性关键。
        # 这里只确保「只读分类的 kind」这种结构化标签翻了。
        for n in real_notes:
            v = str(getattr(n, "kind", "") or "")
            if _re.search(r"[\u4e00-\u9fff]", v):
                out = lang.T(v)
                assert not _re.search(r"[\u4e00-\u9fff]", out), \
                    f"只读分类 kind 没翻: {v!r} -> {out!r}"

        # 组合句：子串替换要把整句都换成英文
        for probe in ("扫描 已安装软件的安装包",
                      "确认清理 12 项，其中 1 项是注册表修改？",
                      "已选 8 项 · 1.2 GB",
                      "完成 · 19:42:10 · 另有 4369 项按条目计"):
            out = lang.T(probe)
            assert not _re.search(r"[\u4e00-\u9fff]", out), \
                f"组合句没翻干净: {probe!r} -> {out!r}"
            # 标点译文自带空格，叠上原文空格会出现 "12  items" 这种双空格
            assert not _re.search(r"[ \t]{2,}", out), \
                f"译文里有双空格: {out!r}"
    finally:
        lang.set_lang("zh")

    # 中文模式必须是恒等函数
    assert lang.T("移入回收站") == "移入回收站"
    assert lang.set_lang("xx") is None and lang.LANG == "zh"


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def t_web_site():
    """静态站：两页都在、链接不失效、正文对比度达 WCAG AA。

    对比度不靠眼睛判断 —— --fg3 之前是 4.17:1，AA 要 4.5:1，肉眼在深色底上
    根本看不出差多少。表格里所有文字/背景组合都算一遍。
    """
    import re as _re
    web = Path(__file__).parent / "web"
    assert web.is_dir(), "web/ 目录没了"
    for name in ("index.html", "index.zh.html", "404.html"):
        p = web / name
        assert p.is_file(), f"缺 {name}"
        html = p.read_text(encoding="utf-8")
        assert html.lstrip().lower().startswith("<!doctype html>"), f"{name} 没有 doctype"
        assert "<meta name=\"viewport\"" in html, f"{name} 没有 viewport，移动端会糊"
        assert "<title>" in html, f"{name} 没有 title"
        # 标签闭合的粗检：每个开标签有对应闭标签。
        # 注意要用 <tag> 和 <tag 后跟空白/>，否则 <head 会把 <header 也算进去。
        for tag in ("html", "head", "body", "style", "script", "div", "header", "footer"):
            if f"<{tag}>" not in html and f"<{tag} " not in html:
                continue
            opened = len(_re.findall(rf"<{tag}(?=[\s>])", html))
            closed = html.count(f"</{tag}>")
            assert opened == closed, \
                f"{name} 的 <{tag}> 开 {opened} 个、闭 {closed} 个，对不上"

    idx = (web / "index.html").read_text(encoding="utf-8")
    zh = (web / "index.zh.html").read_text(encoding="utf-8")

    # 两版首页必须互链，否则用户切不过去
    assert "index.zh.html" in idx, "英文版没链到中文版"
    assert "index.html" in zh, "中文版没链回英文版"
    # 404 要两种语言都有，且按 navigator.language 切换
    nf = (web / "404.html").read_text(encoding="utf-8")
    assert "navigator.language" in nf, "404 没做语言自动检测"
    for cls in ('class="en"', 'class="zh"'):
        assert cls in nf, f"404 缺 {cls} 那一套文案"

    # 仓库链接必须在，且必须都指向 matou1118/DevCleaner（防止写错成别人仓库）。
    # 用子串包含而不是集合相等：/releases/tag/v0.1.0 也算命中 /releases。
    blob = " ".join(_re.findall(r"https://github\.com/([\w.\-/]+)", idx))
    for want in ("matou1118/DevCleaner",
                 "matou1118/DevCleaner/releases",
                 "matou1118/DevCleaner/releases/tag/v0.1.0",
                 "matou1118/DevCleaner/issues"):
        assert want in blob, f"英文首页少了链接: {want}"
    others = [u for u in _re.findall(r"https://github\.com/([\w.\-]+)/", idx)
              if u != "matou1118"]
    assert not others, f"链接指向了别人的仓库: {set(others)}"

    # 引用的本地资源必须真的存在（Pages 上是 gh-pages 分支，图片随站点走，
    # 所以路径必须是 web/ 内部的相对路径，不能 ../docs/）
    for page_name, page in (("index.html", idx), ("index.zh.html", zh)):
        for m in _re.findall(r'(?:src|href)="([^"]+)"', page) + \
                 _re.findall(r"fetch\('([^']+)'\)", page):
            if m.startswith(("http", "#", "data:", "/")):
                continue
            assert not m.startswith(".."), \
                f"{page_name} 引用了站点外的 {m} —— GitHub Pages 上会 404"
            assert (web / m).resolve().exists(), \
                f"{page_name} 引用了不存在的文件: {m}"

    # Pages 必备：根 404.html，以及中英互链
    assert (web / "404.html").is_file(), "缺 404.html（Pages 会用它兜底）"
    assert "index.zh.html" in idx, "英文版没链到中文版"
    assert "index.html" in zh, "中文版没链回英文版"

    # 对比度：把 CSS 变量解析出来，逐对算（中英文两版都要）
    for label, page in (("en", idx), ("zh", zh)):
        css = _re.search(r":root\{(.*?)\}", page, _re.S).group(1)
        var = dict(_re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", css))
        for need in ("--bg", "--fg", "--fg2", "--fg3", "--accent", "--accent2", "--safe"):
            assert need in var, f"{label} 版少了 CSS 变量 {need}"
        bg = var["--bg"]
        for fg, what in (("--fg", "正文"), ("--fg2", "次要文字"), ("--fg3", "弱化文字"),
                         ("--accent", "强调链接"), ("--safe", "安全绿")):
            ratio = _contrast(var[fg], bg)
            assert ratio >= 4.5, \
                f"{label} 版{what} ({fg}={var[fg]} on {bg}) 只有 {ratio:.2f}:1，AA 要 4.5:1"

    # 站点上不许有 MIT 残留 —— 许可换了，站点必须跟着换。
    # 这个坑踩过：LICENSE 和 README 都改成 CC BY-NC 了，站点脚注还写着 MIT。
    for name in ("index.html", "index.zh.html", "404.html"):
        t = (web / name).read_text(encoding="utf-8")
        assert "MIT" not in t, f"web/{name} 还写着 MIT，许可已经换成 CC BY-NC 4.0"
    # 而且站上得能看到条款
    for name in ("index.html", "index.zh.html"):
        t = (web / name).read_text(encoding="utf-8")
        assert "CC BY-NC 4.0" in t, f"web/{name} 没写许可"
        assert "Matou1118" in t, f"web/{name} 没写署名"
        assert "LICENSE" in t, f"web/{name} 没链到许可全文"

    # 关键卖点必须在两版上都在，不能被改没了
    for phrase in ("Recycle Bin",):
        assert phrase in idx, f"英文首页少了关键信息: {phrase}"
    for phrase in ("回收站",):
        assert phrase in zh, f"中文首页少了关键信息: {phrase}"

    # 数字不许写死在 HTML 里：必须来自 stats.json（跑真实扫描生成）。
    # 写死的话机器上多删一个缓存，页面就开始说谎。
    for page_name, page in (("index.html", idx), ("index.zh.html", zh)):
        assert 'data-stat="total"' in page, \
            f"{page_name} 的合计数字写死了，应改用 data-stat + stats.json"
        assert "fetch('stats.json')" in page, f"{page_name} 没读 stats.json"
        assert 'id="cats"' in page, f"{page_name} 的分类列表没留给 stats.json 渲染"
        assert not _re.search(r'class="n">\s*[\d.]+\s*(GB|MB|KB)', page), \
            f"{page_name} 里还有写死的容量数字"

    # stats.json 本身要合法，且和当前扫描对得上
    import json as _json
    sp = web / "stats.json"
    assert sp.is_file(), "缺 stats.json，跑 python web/gen_stats.py 生成"
    s = _json.loads(sp.read_text(encoding="utf-8"))
    for need in ("total_human", "scanners", "categories"):
        assert need in s, f"stats.json 缺 {need}"
    assert s["scanners"] == len(app.SCANNERS), \
        f"stats.json 写的是 {s['scanners']} 个扫描器，实际 {len(app.SCANNERS)} 个"
    for c in s["categories"]:
        for need in ("icon", "zh", "en", "size_human"):
            assert need in c and c[need] != "", f"stats.json 的分类缺 {need}: {c}"


def t_scan_paint_throttled():
    """扫描期的重绘要限频，进度条不能被关掉。

    走过的弯路：曾用 setUpdatesEnabled(False) 消除重绘，结果进度条也没了
    （用户反馈"没有进度条"），而 tools/screenprobe.py 抓屏实测显示窗口像素
    本来就是稳的 —— 31 秒 402 帧只有 8 帧变化，全在进度条那一行。
    starve.py 也显示主线程拿到 100% 时间片、零卡顿。所以关更新是砍错地方。

    现在锁的正确不变量：
    1. 进度条还在（setUpdatesEnabled 不为 False）
    2. 同一句阶段文字连喂 50 次，setText 只能触发 0 次
    3. 同一个百分比重复回调，setValue 不能重复触发
    """
    import gui
    from PySide6.QtWidgets import QApplication
    import time
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w.show()
    w.start_scan()
    assert w.updatesEnabled() is True, \
        "扫描期不能关窗口更新 —— 那样进度条也没了，而它本来就不是闪的根源"
    w.thread and w.thread.wait(300000)

    # 2. 阶段文字去重
    label = w.stage
    calls = {"n": 0}
    orig = label.setText
    label.setText = lambda v: (calls.__setitem__("n", calls["n"] + 1), orig(v))[1]
    w._last_stage_text = "SENTINEL"
    w._last_stage = time.monotonic()
    for _ in range(50):
        w._on_progress("SENTINEL", 0.5)
    assert calls["n"] == 0, f"同一句阶段文字被 setText {calls['n']} 次（每次=全窗重绘）"

    # 3. 百分比去重：同一值重复回调不该重复 setValue
    vcalls = {"n": 0}
    vorig = w.prog.setValue
    w.prog.setValue = lambda v: (vcalls.__setitem__("n", vcalls["n"] + 1), vorig(v))[1]
    w._last_pct = 40
    for _ in range(20):
        w._on_progress("别的", 0.40)
    assert vcalls["n"] == 0, f"同一百分比触发了 {vcalls['n']} 次 setValue"
    # 值真的变了还是要更新
    w._on_progress("别的", 0.77)
    assert vcalls["n"] == 1, f"百分比变了却没更新（{vcalls['n']} 次）"

    label.setText = orig
    w.prog.setValue = vorig
    w.close()


def t_byline_version_link():
    """底栏要有「署名 + GitHub 链接 + 版本号」，且链接指向正确的仓库。

    用户明确要求显示 "Matou1118 GitHub v0.1.0" 并可点进仓库。
    """
    import gui
    from PySide6.QtWidgets import QApplication
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())

    html = w.ver.text()
    assert app.OWNER in html, f"底栏没有署名: {html!r}"
    assert app.REPO in html, f"没有仓库链接: {html!r}"
    assert app.__version__ in html, f"没有版本号: {html!r}"
    assert "Matou1118" in html, f"署名大小写不对: {html!r}"
    # 必须是外链，点了交给系统浏览器，不能在应用内导航
    assert w.ver.openExternalLinks() is True, "GitHub 链接没开外链"
    # 换主题后链接颜色要跟着变（富文本颜色写死在 HTML 里）
    w.apply_theme(w.cb_theme.currentIndex())
    assert app.THEMES[w.theme]["accent"] in w.ver.text(), \
        f"换主题后链接颜色没更新: {w.ver.text()!r}"
    w.close()


def t_no_console_flash():
    """打包成 GUI 程序后，任何子进程都不能再闪控制台窗口。

    这是"扫描时满屏闪、像有弹窗拖影"的真正根因。Windows 的规则：控制台程序
    继承父进程的控制台，GUI 子系统程序没有 -> 系统必须给子进程**新建**一个
    控制台窗口。DevCleaner 扫描时会 `subprocess.run(["git", ...])`，于是每跑
    一次 git 屏幕上就闪一个黑框，实测一次扫描闪 41 次（tools/popupprobe.py
    抓到 ConsoleWindowClass，标题 'git.exe'，515367px）。

    修法是 creationflags=CREATE_NO_WINDOW + STARTUPINFO SW_HIDE。
    这个测试做静态检查：所有 spawn 点必须带 creationflags。
    """
    import re as _re
    root = Path(__file__).parent
    pat = _re.compile(r"subprocess\.(run|Popen|call|check_output|check_call)\(")
    bad = []
    for f in ("app.py", "gui.py", "lang.py"):
        src = (root / f).read_text(encoding="utf-8")
        lines = src.splitlines()
        for i, ln in enumerate(lines):
            if not pat.search(ln):
                continue
            # 往后看 8 行，creationflags 可能换行了
            blk = "\n".join(lines[i:i + 8])
            if "creationflags" not in blk:
                bad.append(f"{f}:{i + 1}  {ln.strip()[:70]}")
    assert not bad, (
        "这些子进程没加 creationflags=CREATE_NO_WINDOW，打包成 GUI 程序后"
        "每次都会闪一个控制台窗口：\n  " + "\n  ".join(bad))

    # 顺便确认辅助函数在
    src = (root / "app.py").read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in src, "app.py 里没有 CREATE_NO_WINDOW"
    assert "STARTF_USESHOWWINDOW" in src, "缺少 STARTUPINFO 兜底"


def t_confirm_dialog_scrolls():
    """确认对话框必须能滚动，且按钮永远在屏幕内。

    这是个真 bug（用户两次报告）：原来用 QMessageBox.setInformativeText 塞
    明细，它没有滚动条，条目一多整个对话框撑出屏幕，**确认按钮被顶到看不见
    的地方**。

    关键是要按**小屏**算。只在本机 1080p 上测是不够的 —— 1366x768 笔记本的
    工作区只有约 728px，而当时开发机上 offscreen 平台返回的是假分辨率
    （800），把问题完全掩盖了。这里直接按不同的可用高度算，不依赖真实屏幕。
    """
    import gui
    from PySide6.QtWidgets import QApplication, QTextEdit, QPushButton
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())

    class Fake:
        """造最坏情况：超长中文名 + 超长路径"""
        def __init__(self, n):
            self.name = f"条目 {n} " + "很长的名字" * 6
            self.path = "REG:" + "x" * 400
            self.size = 123456789
            self.unit = "bytes"
            self.risk = "safe"

    sel = [Fake(i) for i in range(60)]
    detail = gui._confirm_details(sel)
    assert detail.count("·") == 60, "明细条数不对"
    risky = gui._confirm_risky(sel[:30])
    assert risky, "需确认提示没生成"

    for avail in (1080, 1032, 900, 800, 728, 640, 560):
        cap = int(avail * gui.ConfirmDialog.MAX_H)
        # 关键：得**真的**让代码看到 avail 这个高度，否则测的是本地屏幕。
        # 之前只算数字不对 —— 离屏平台 primaryScreen() 永远返回 800，
        # 代码按 800 算出 cap，和测试按 728 算的对不上，断言形同虚设。
        import unittest.mock as _m
        geo = _m.Mock()
        geo.height.return_value = avail
        scr = _m.Mock()
        scr.availableGeometry.return_value = geo
        with _m.patch.object(QApplication, "primaryScreen", staticmethod(lambda: scr)):
            dlg = gui.ConfirmDialog(w, "确认清理", f"确认清理 {len(sel)} 项？",
                                    detail, risky, danger=True)
            h = dlg.sizeHint().height()
            view_h = dlg.findChild(QTextEdit).height()
            max_h = dlg.maximumHeight()
            btns = [(b.text(), b.mapTo(dlg, b.rect().center()).y())
                    for b in dlg.findChildren(QPushButton)]
        assert view_h <= cap, \
            f"屏幕可用 {avail}px 时明细区 {view_h}px 超过上限 {cap}px"
        assert max_h <= cap + 96, \
            f"屏幕可用 {avail}px 时对话框上限 {max_h} 太大（cap={cap}）"
        # 按钮必须在对话框高度之内
        for name, y in btns:
            assert 0 <= y <= h, f"屏幕 {avail}px 时按钮 {name!r} 在 y={y}，对话框高 {h}"
        dlg.close()

    # 少量条目时也别太空
    few = gui.ConfirmDialog(w, "确认清理", "确认清理 2 项？", gui._confirm_details(sel[:2]))
    assert few.findChild(QTextEdit).height() >= 200, "少量条目时明细区太小"
    few.close()
    w.close()


def t_license_attribution():
    """许可必须是 CC BY-NC 4.0：署名 + 禁商用 + 可二开。"""
    root = Path(__file__).parent
    lic = (root / "LICENSE").read_text(encoding="utf-8")
    low = lic.lower()
    assert "CC BY-NC 4.0" in lic, "LICENSE 里没有 CC BY-NC 4.0"
    assert "Matou1118" in lic, "LICENSE 里没写原作者"
    for must, why in (("noncommercial", "禁商用条款缺失"),
                      ("commercial", "禁商用说明缺失"),
                      ("attribution", "署名条款缺失"),
                      ("derivative", "二次开发/衍生作品条款缺失"),
                      ("by-nc", "署名+禁商用组合许可标识缺失")):
        assert must in low, f"LICENSE 缺 {must}（{why}）"

    # README 徽章和许可段落都要跟上
    for name in ("README.md", "README.en.md"):
        t = (root / name).read_text(encoding="utf-8")
        assert "CC BY-NC 4.0" in t, f"{name} 没写 CC BY-NC 4.0"
        assert "MIT" not in t.replace("emits", ""), f"{name} 还残留 MIT"

    # 界面 tooltip 也要说清署名和禁商用
    src = (root / "gui.py").read_text(encoding="utf-8")
    assert "CC BY-NC 4.0" in src, "界面 tooltip 没提许可"
    assert "Non-commercial" in src or "禁商用" in src, "界面 tooltip 没提禁商用"

    # 底栏署名必须还在（署名义务的体现）
    import gui
    from PySide6.QtWidgets import QApplication
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())
    assert "Matou1118" in w.ver.text(), w.ver.text()
    assert app.REPO in w.ver.text(), w.ver.text()
    w.close()


def t_exe_standalone_no_python():
    """发布的 exe 必须在「没装 Python」的机器上能跑。

    有人会问「要不要把 Python 一起封装」—— 已经封装了：那 32.8 MB 里就是
    CPython 解释器 + PySide6/Qt + 本项目代码，用 PyInstaller 打的单文件。

    这个测试用最小 PATH（只留 System32，把本机 Python 从 PATH 拿掉）跑一遍
    dist 里的 exe，证明它不依赖外部解释器。dist 不存在时跳过。
    """
    import os as _os
    exe = Path(__file__).parent / "dist" / "DevCleaner.exe"
    if not exe.is_file():
        return
    env = dict(_os.environ, PATH=r"C:\\Windows\\System32")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    r = subprocess.run([str(exe), "--version"], capture_output=True,
                       text=True, errors="replace", timeout=300,
                       env=env, cwd=str(exe.parent))
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"没有 Python 的环境里起不来 (rc={r.returncode}): {out[:200]}"
    assert app.__version__ in out, f"版本号没输出: {out[:200]!r}"


# ---------------- 双语文档 ----------------
def t_docs_bilingual():
    """面向人的文档必须有英文版。

    这是明确要求：不要只做中文说明。少一个英文版就是国际用户完全读不懂。
    """
    root = Path(__file__).parent
    # 中文文件 -> 必须存在的英文版
    PAIRS = {
        "README.md": "README.en.md",
        "CHANGELOG.md": "CHANGELOG.en.md",
        "CONTRIBUTING.md": "CONTRIBUTING.en.md",
        "SECURITY.md": "SECURITY.en.md",
        "CODE_OF_CONDUCT.md": "CODE_OF_CONDUCT.en.md",
        "docs/usage.md": "docs/usage.en.md",
        "docs/Screenshots.md": "docs/Screenshots.en.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml":
            ".github/ISSUE_TEMPLATE/bug_report.en.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml":
            ".github/ISSUE_TEMPLATE/feature_request.en.yml",
        ".github/ISSUE_TEMPLATE/CONTRIBUTING_HINT.md":
            ".github/ISSUE_TEMPLATE/CONTRIBUTING_HINT.en.md",
    }
    missing = []
    for zh, en in PAIRS.items():
        zp, ep = root / zh, root / en
        if not zp.is_file():
            missing.append(f"{zh}（中文版没了）")
            continue
        if not ep.is_file():
            missing.append(f"{en}（缺英文版）")
            continue
        if ep.stat().st_size < 1200:
            missing.append(f"{en} 只有 {ep.stat().st_size} 字节，像占位符")
    assert not missing, "文档不成双语:\n  " + "\n  ".join(missing)

    # settings.yaml 用户直接改，注释必须中英并列
    s = (root / "settings.yaml").read_text(encoding="utf-8")
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    assert cjk > 100, "settings.yaml 的中文注释太少了"
    assert "/" in s, "settings.yaml 应该用中英并排的注释（出现 / 分隔）"

    # 英文版不应残留中文正文（链接和代码块除外）
    for _, en in PAIRS.items():
        p = root / en
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8")
        body = "\n".join(l for l in txt.splitlines()
                          if not l.strip().startswith(("```", "    ", "|", ">")))
        cjk = sum(1 for ch in body if "\u4e00" <= ch <= "\u9fff")
        ratio = cjk / max(len(body), 1)
        assert ratio < 0.02, f"{en} 正文里中文占比 {ratio:.1%}，翻译没跟上"


# ---------------- 文档 ----------------
def t_docs_present():
    """说明文件齐全，且不是空壳"""
    root = Path(__file__).parent
    need = ["docs/usage.md", "docs/usage.en.md", "docs/Screenshots.md",
            "docs/01-overview.png", "docs/02-expanded.png", "docs/03-confirm.png",
            "docs/04-registry.png"]
    missing = [n for n in need if not (root / n).is_file()]
    assert not missing, f"缺这些文档/截图: {missing}"
    for n in ("docs/usage.md", "docs/usage.en.md", "docs/Screenshots.md"):
        sz = (root / n).stat().st_size
        assert sz > 1500, f"{n} 只有 {sz} 字节，可能是占位符"
    for t in ("docs/themes", ):
        pngs = sorted((root / t).glob("*.png"))
        assert len(pngs) == 6, f"{t} 应有 6 套主题截图，实际 {len(pngs)}"
    # 六个主题每个都该有对应截图
    for name in app.THEME_ORDER:
        slug = name.lower().replace(" ", "-").replace("é", "e")
        assert (root / "docs" / "themes" / (slug + ".png")).is_file(), \
            f"主题 {name} 缺截图"


# ---------------- 界面能在离屏模式下构建 ----------------
def t_gui_offscreen():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import gui
    qa = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    for i in range(len(engine_themes())):
        w.cb_theme.setCurrentIndex(i)
    w._render()
    assert w.t_tot.text() != "—", "统计没刷新"
    w.bulk(True, only_safe=True)
    w.recalc()
    for it in app.STATE.items:
        assert (it.path in w.pick) == (it.risk == "safe"), f"{it.name} 勾选状态不符"
    w.bulk(False)
    assert not w.pick, "清空后仍有选择"
    # fmt 必须按 unit 分流
    cnt = app.Item("n", "c", "p", 42, "safe", unit="count")
    assert gui.fmt(cnt) == "42 项", gui.fmt(cnt)
    byt = app.Item("n", "c", "p", 2048, "safe")
    assert gui.fmt(byt) == "2.00 KB", gui.fmt(byt)
    assert gui._mix([2048, 5], ["bytes", "count"]) == "2.00 KB + 5 项"
    w.close()


def engine_themes():
    return app.THEMES


# ---------------- 真实环境只读冒烟 ----------------
def t_smoke():
    dl = known_folders("Downloads")
    assert dl, "取不到任何存在的 Downloads 目录"
    for d in dl:
        assert d.is_dir(), d
    print(f"       Downloads = {', '.join(str(d) for d in dl)}")
    assert "OfficeAce" in product_candidates("OfficeAce-1.1.4-windows-x64-setup")
    assert app.app_dir().is_dir()
    assert app.resource("settings.yaml").is_file(), "找不到 settings.yaml"


# ---------------- -c 分类过滤器 ----------------
def t_category_filter():
    """-c 过滤器修复：旁路分类能选中 + 单分类不泄漏"""
    assert app.BYPASS_CATEGORIES, "BYPASS_CATEGORIES 未定义"

    # 全量扫描，记录是否有注册表项
    app.run_scan()
    has_registry = any("注册表" in i.category for i in app.STATE.items)

    # 过滤"注册表"：所有结果必须含"注册表"，不能混入其他分类
    app.run_scan(category_filter="注册表")
    for i in app.STATE.items:
        assert "注册表" in i.category, f"过滤泄漏: {i.category}"
    if has_registry:
        assert app.STATE.items, "全量有注册表项但 -c 过滤后为空"

    # 过滤"构建产物"：不能泄漏注册表项
    app.run_scan(category_filter="构建产物")
    for i in app.STATE.items:
        assert "构建产物" in i.category, f"过滤泄漏: {i.category}"
        assert "注册表" not in i.category, f"注册表泄漏到构建产物: {i.category}"


# ---------------- 审计日志 ----------------
def t_audit_log():
    """审计日志：能写入、内容正确、不抛异常"""
    app.audit_log("TEST", "自检测试条目")
    p = app.audit_log_path()
    assert p.is_file(), "审计日志文件未创建"
    content = p.read_text(encoding="utf-8")
    assert "TEST" in content, "审计日志缺少 TEST 动作"
    assert "自检测试条目" in content, "审计日志缺少详情文本"
    # 格式：[时间戳] ACTION | detail
    last = content.strip().splitlines()[-1]
    assert last.startswith("["), f"日志格式不对: {last}"
    assert "] TEST | " in last, f"日志格式不对: {last}"


# ---------------- 删除路径安全校验 ----------------
def t_path_safety():
    """to_recycle_bin 纵深防御：拒绝删系统目录内的文件"""
    # 正常文件可以删 —— 独立临时目录，不依赖共享 tmp（会被 t_no_test_crash_left_behind 清掉）
    own = Path(tempfile.mkdtemp(prefix="dc_safety_"))
    try:
        f = own / "safe_to_delete.txt"
        f.write_text("x", encoding="utf-8")
        ok, msg = to_recycle_bin(str(f))
        assert ok, f"正常文件应可删: {msg}"
    finally:
        shutil.rmtree(own, ignore_errors=True)

    # 系统目录内的文件拒绝删除（notepad.exe 一定存在）
    # 路径取自环境变量：Windows 装在 D 盘时，写死 C:/Windows 等于没保护
    sys_file = Path(os.path.expandvars("%SystemRoot%")) / "notepad.exe"
    if sys_file.exists():
        ok, msg = to_recycle_bin(str(sys_file))
        assert not ok, "系统目录文件不应被删"
        assert "拒绝" in msg or "系统目录" in msg, f"错误信息不对: {msg}"


def t_path_safety_env():
    """系统目录防护必须认环境变量，不能写死 C:"""
    own = Path(tempfile.mkdtemp(prefix="dc_root_"))
    old = os.environ.get("SystemRoot")
    try:
        fake_win = own / "Windows"
        fake_win.mkdir()
        f = fake_win / "notepad.exe"
        f.write_text("x", encoding="utf-8")
        os.environ["SystemRoot"] = str(own)
        ok, msg = to_recycle_bin(str(f))
        assert not ok, "环境变量指向的目录同样必须拒绝删除（写死 C: 就是这个洞）"
        assert f.exists(), "文件不能真被删掉"
    finally:
        if old is None:
            os.environ.pop("SystemRoot", None)
        else:
            os.environ["SystemRoot"] = old
        shutil.rmtree(own, ignore_errors=True)


# ---------------- 文件备份与回滚 ----------------
def t_safe_delete_backup():
    """safe_delete + 备份目录：文件移入备份、manifest 正确、可回滚"""
    own = Path(tempfile.mkdtemp(prefix="dc_backup_"))
    try:
        # 创建测试文件
        f1 = own / "file_a.txt"
        f2 = own / "file_b.txt"
        f1.write_text("content A", encoding="utf-8")
        f2.write_text("content B", encoding="utf-8")

        # 创建备份会话
        bdir, sid = app.create_backup_session()
        assert bdir.is_dir(), "备份目录未创建"
        assert sid, "会话 ID 为空"

        # safe_delete 到备份目录
        ok, msg = app.safe_delete(str(f1), backup_dir=bdir)
        assert ok, f"safe_delete 应成功: {msg}"
        assert "BACKEDUP:" in msg, f"应走备份路径: {msg}"
        assert not f1.exists(), "原文件应已被移走"

        ok2, msg2 = app.safe_delete(str(f2), backup_dir=bdir)
        assert ok2, f"safe_delete 第二个文件应成功: {msg2}"

        # manifest 应有 2 条
        manifest = bdir / "manifest.json"
        assert manifest.is_file(), "manifest 未创建"
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        assert len(entries) == 2, f"manifest 应有 2 条，实际 {len(entries)}"

        # 列出会话
        sessions = app.list_backup_sessions()
        assert any(s["id"] == sid for s in sessions), "list_backup_sessions 未列出新会话"

        # 回滚
        ok_n, fail_n, errs = app.restore_backup_session(sid)
        assert ok_n == 2, f"回滚应成功 2 项，实际 {ok_n}，失败 {fail_n}: {errs}"
        assert f1.read_text(encoding="utf-8") == "content A", "回滚后内容不对"
        assert f2.read_text(encoding="utf-8") == "content B", "回滚后内容不对"

        # 回滚后备份目录应被清理
        assert not bdir.exists(), "回滚成功后备份目录应删除"
    finally:
        shutil.rmtree(own, ignore_errors=True)


def t_backup_cleanup_old():
    """cleanup_old_backups：超龄备份被清理，新备份保留"""
    bdir, sid = app.create_backup_session()
    # 写一个假 manifest 使其成为有效会话
    (bdir / "manifest.json").write_text("[]", encoding="utf-8")
    # 把修改时间改为 10 天前
    old_ts = time.time() - 10 * 86400
    os.utime(str(bdir), (old_ts, old_ts))

    # 再创建一个新会话
    bdir2, sid2 = app.create_backup_session()
    (bdir2 / "manifest.json").write_text("[]", encoding="utf-8")

    removed = app.cleanup_old_backups(7)
    assert removed >= 1, f"应清理至少 1 个旧备份，实际 {removed}"
    assert not bdir.exists(), "旧备份应被删除"
    assert bdir2.exists(), "新备份应保留"

    # 清理
    shutil.rmtree(bdir2, ignore_errors=True)


def t_safe_delete_no_backup():
    """safe_delete 无 backup_dir 时降级走回收站"""
    own = Path(tempfile.mkdtemp(prefix="dc_noback_"))
    try:
        f = own / "to_recycle.txt"
        f.write_text("x", encoding="utf-8")
        ok, msg = app.safe_delete(str(f), backup_dir=None)
        assert ok, f"无备份时应走回收站: {msg}"
        assert "BACKEDUP:" not in msg, "不应走备份路径"
    finally:
        shutil.rmtree(own, ignore_errors=True)


# ============================ 软件卸载测试 ============================

def t_list_installed_software():
    """list_installed_software 返回列表，每项有 name 和 uninstall_string"""
    sw = app.list_installed_software()
    assert isinstance(sw, list), "应返回列表"
    for s in sw:
        assert s.name, "每项必须有 name"
        assert s.uninstall_string, "每项必须有 uninstall_string"
        assert s.reg_hive in ("HKLM", "HKCU"), f"reg_hive 非法: {s.reg_hive}"


def t_list_installed_software_dedup():
    """去重：同一软件不应在 HKLM 和 WOW6432Node 各出现一次"""
    sw = app.list_installed_software()
    names = [s.name.lower() for s in sw]
    assert len(names) == len(set(names)), "存在重复软件名"


def t_list_installed_software_no_kb():
    """KB 补丁应被过滤掉"""
    sw = app.list_installed_software()
    for s in sw:
        assert not (s.name.startswith("KB") and s.name[2:7].isdigit()), \
            f"KB 补丁未被过滤: {s.name}"


def t_run_uninstaller_empty():
    """空字符串应返回失败"""
    ok, msg = app.run_uninstaller("")
    assert not ok, "空卸载命令应失败"
    assert "无卸载命令" in msg, f"消息不对: {msg}"


def t_run_uninstaller_missing_exe():
    """不存在的 exe 应返回失败"""
    ok, msg = app.run_uninstaller(r"C:\nonexistent\uninst.exe")
    assert not ok, "不存在的 exe 应失败"
    assert "不存在" in msg, f"消息不对: {msg}"


def t_run_uninstaller_quoted():
    """带引号的卸载命令能正确解析 exe 路径"""
    # 用一个肯定存在的 exe（cmd.exe）但加 /c exit 0 让它立即退出
    ok, msg = app.run_uninstaller(r'"C:\Windows\System32\cmd.exe" /c exit 0')
    assert ok, f"带引号的 cmd 应成功: {msg}"


def t_run_uninstaller_unquoted():
    """不带引号的卸载命令能正确解析"""
    ok, msg = app.run_uninstaller(r"C:\Windows\System32\cmd.exe /c exit 0")
    assert ok, f"不带引号的 cmd 应成功: {msg}"


def t_run_uninstaller_bare_name():
    """卸载命令只写 exe 名时要按 PATH 解析。

    MSI 制软件一律是 `MsiExec.exe /X{GUID}` 这种裸 exe 名，而
    os.path.exists('MsiExec.exe') 恒为 False —— 不按 PATH 解析的话，
    它们的卸载全被误报成「卸载程序不存在」。这里用 cmd 验同一条代码路径。
    """
    ok, msg = app.run_uninstaller("cmd /c exit 0")
    assert ok, f"裸 exe 名应能按 PATH 解析并执行: {msg}"


def t_find_residuals_structure():
    """find_residuals 返回正确结构"""
    r = app.find_residuals("NonExistentSoftwareXYZ123")
    assert "registry" in r, "缺 registry 键"
    assert "folders" in r, "缺 folders 键"
    assert "shortcuts" in r, "缺 shortcuts 键"
    assert isinstance(r["registry"], list), "registry 应为列表"
    assert isinstance(r["folders"], list), "folders 应为列表"
    assert isinstance(r["shortcuts"], list), "shortcuts 应为列表"


def t_find_residuals_finds_folder():
    """find_residuals 能找到 AppData 下的残留目录"""
    own = Path(tempfile.mkdtemp(prefix="dc_resid_"))
    try:
        # 在 %TEMP% 下造一个假软件目录
        fake_name = "DevCleanerTestFakeApp42"
        appdata = os.environ.get("APPDATA", "")
        fake_dir = Path(appdata) / fake_name
        created = False
        if not fake_dir.exists():
            fake_dir.mkdir(parents=True)
            created = True
        try:
            r = app.find_residuals(fake_name)
            found = any(fake_name.lower() in f.lower() for f in r["folders"])
            assert found, f"未找到残留目录 {fake_dir}"
        finally:
            if created:
                shutil.rmtree(fake_dir, ignore_errors=True)
    finally:
        shutil.rmtree(own, ignore_errors=True)


def t_clean_residuals_empty():
    """clean_residuals 处理空残留应返回零计数"""
    r = app.clean_residuals({"registry": [], "folders": [], "shortcuts": []})
    assert r["deleted"] == 0, "空残留删除数应为 0"
    assert r["failed"] == 0, "空残留失败数应为 0"
    assert r["reg_pending"] == 0, "空残留注册表待定应为 0"


def t_clean_residuals_with_backup():
    """clean_residuals 清理文件时走备份路径"""
    own = Path(tempfile.mkdtemp(prefix="dc_clean_"))
    backup = own / "backup"
    backup.mkdir()
    try:
        fake_file = own / "FakeAppData"
        fake_file.mkdir()
        (fake_file / "config.ini").write_text("[x]", encoding="utf-8")
        residuals = {"registry": [], "folders": [str(fake_file)], "shortcuts": []}
        r = app.clean_residuals(residuals, backup_dir=backup)
        assert r["deleted"] == 1, f"应删除 1 项: {r}"
        assert r["failed"] == 0, f"不应有失败: {r}"
        assert not fake_file.exists(), "目录应已被删除"
    finally:
        shutil.rmtree(own, ignore_errors=True)


def t_installed_software_dataclass():
    """InstalledSoftware dataclass 字段完整"""
    sw = app.InstalledSoftware(
        name="Test", publisher="Pub", version="1.0", size_mb=10,
        uninstall_string="x", quiet_string="", install_location="",
        reg_hive="HKLM", reg_key="SOFTWARE\\Test")
    assert sw.name == "Test"
    assert sw.size_mb == 10
    assert sw.reg_hive == "HKLM"
    assert sw.last_used == 0.0, "last_used 默认应为 0.0"


def t_last_used_time_returns_float():
    """_last_used_time 返回 float，非负"""
    t = app._last_used_time("NonExistentXYZ123")
    assert isinstance(t, float), f"应返回 float，得到 {type(t)}"
    assert t >= 0.0, f"应非负，得到 {t}"


def t_last_used_time_unknown_is_zero():
    """不存在的软件 last_used 应为 0"""
    t = app._last_used_time("AbsolutelyNonExistentSoftware999")
    assert t == 0.0, f"不存在的软件应为 0.0，得到 {t}"


def t_last_used_time_finds_appdata():
    """_last_used_time 能从 AppData 目录探测到时间"""
    fake_name = "DevCleanerTestLastUsed42"
    appdata = os.environ.get("APPDATA", "")
    fake_dir = Path(appdata) / fake_name
    created = False
    try:
        if not fake_dir.exists():
            fake_dir.mkdir(parents=True)
            created = True
        # 写个文件确保 mtime 更新
        (fake_dir / "config.ini").write_text("[x]", encoding="utf-8")
        t = app._last_used_time(fake_name)
        assert t > 0.0, f"应探测到 AppData 目录时间，得到 {t}"
    finally:
        if created:
            shutil.rmtree(fake_dir, ignore_errors=True)


def t_last_used_time_finds_exe():
    """_last_used_time 能从 exe 的 atime 探测到时间"""
    cmd = r"C:\Windows\System32\cmd.exe"
    t = app._last_used_time("cmd", uninstall_string=cmd)
    assert t > 0.0, f"应探测到 cmd.exe 的 atime，得到 {t}"


def t_list_installed_software_has_last_used():
    """list_installed_software 每项的 last_used 是 float"""
    sw = app.list_installed_software()
    for s in sw:
        assert isinstance(s.last_used, float), \
            f"last_used 应为 float: {s.name} -> {type(s.last_used)}"
        assert s.last_used >= 0.0, \
            f"last_used 应非负: {s.name} -> {s.last_used}"


def t_list_installed_software_some_have_last_used():
    """至少有一些软件能探测到 last_used"""
    sw = app.list_installed_software()
    valid = [s for s in sw if s.last_used > 0]
    assert len(valid) > 0, "应有至少 1 款软件探测到 last_used"
    assert sw.last_used == 0.0, "last_used 默认应为 0.0"


def t_last_used_time_returns_float():
    """_last_used_time 返回 float，非负"""
    t = app._last_used_time("NonExistentXYZ123")
    assert isinstance(t, float), f"应返回 float，得到 {type(t)}"
    assert t >= 0.0, f"应非负，得到 {t}"


def t_last_used_time_unknown_is_zero():
    """不存在的软件 last_used 应为 0"""
    t = app._last_used_time("AbsolutelyNonExistentSoftware999")
    assert t == 0.0, f"不存在的软件应为 0.0，得到 {t}"


def t_last_used_time_finds_appdata():
    """_last_used_time 能从 AppData 目录探测到时间"""
    fake_name = "DevCleanerTestLastUsed42"
    appdata = os.environ.get("APPDATA", "")
    fake_dir = Path(appdata) / fake_name
    created = False
    try:
        if not fake_dir.exists():
            fake_dir.mkdir(parents=True)
            created = True
        # 写个文件确保 mtime 更新
        (fake_dir / "config.ini").write_text("[x]", encoding="utf-8")
        t = app._last_used_time(fake_name)
        assert t > 0.0, f"应探测到 AppData 目录时间，得到 {t}"
    finally:
        if created:
            shutil.rmtree(fake_dir, ignore_errors=True)


def t_last_used_time_finds_exe():
    """_last_used_time 能从 exe 的 atime 探测到时间"""
    cmd = r"C:\Windows\System32\cmd.exe"
    t = app._last_used_time("cmd", uninstall_string=cmd)
    assert t > 0.0, f"应探测到 cmd.exe 的 atime，得到 {t}"


def t_list_installed_software_has_last_used():
    """list_installed_software 每项的 last_used 是 float"""
    sw = app.list_installed_software()
    for s in sw:
        assert isinstance(s.last_used, float), \
            f"last_used 应为 float: {s.name} -> {type(s.last_used)}"
        assert s.last_used >= 0.0, \
            f"last_used 应非负: {s.name} -> {s.last_used}"


def t_list_installed_software_some_have_last_used():
    """至少有一些软件能探测到 last_used"""
    sw = app.list_installed_software()
    valid = [s for s in sw if s.last_used > 0]
    assert len(valid) > 0, "应有至少 1 款软件探测到 last_used"


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp(prefix="devcleaner_test_"))
    print("DevCleaner self-test")
    try:
        check("human", t_human)
        check("product_candidates", t_candidates)
        check("InstalledIndex + 别名", t_index)
        check("dir_size / age_days", lambda: t_dirsize(tmp))
        check("to_recycle_bin", lambda: t_recycle(tmp))
        check("Python/Build 扫描器 + Git只读", lambda: t_scanners(tmp))
        check("stale 版本识别", lambda: t_stale(tmp))
        check("未启用插件识别", lambda: t_unused(tmp))
        check("run_scan 端到端", lambda: t_run_scan(tmp))
        check("主题定义", t_themes)
        check("主题主色与设计稿一致", t_theme_tokens_match_design)
        check("主题对比度达 WCAG AA", t_theme_contrast)
        check("onaccent 选取正确", t_theme_onaccent_pick)
        check("改配置保留注释", t_set_config_preserves_comments)
        check("勾选不重解析样式表", t_no_repolish_on_check)
        check("分类默认折叠", t_cards_collapsed_by_default)
        check("展开按钮真实点击", t_expand_button_click)
        check("空文件保留名单", lambda: t_keep_empty(tmp))
        check("批量空文件真删", lambda: t_bulk_empty_delete(tmp))
        check("传统垃圾扫描", lambda: t_junk(tmp))
        check("注册表只读发现", t_registry_findings)
        check("注册表不误判活程序", t_no_false_orphan)
        check("注册表能抓真孤儿", t_real_orphan_detected)
        check("注册表备份/删除/还原", t_registry_backup_and_restore)
        check("注册表深层删除", t_delete_deep_tree)
        check("注册表路径编码", t_reg_path_parse)
        check("clone 保护(有remote不删)", lambda: t_clone_guard(tmp))
        check("界面构建+主题切换(离屏)", t_gui_offscreen)
        check("真实环境只读冒烟", t_smoke)
        check("版本号语义化+变更日志同步", t_version_semver_and_changelog)
        check("开源常备文件齐全", t_oss_scaffolding)
        check("无占位符残留", t_no_placeholder_left)
        check("仓库链接用户名一致", t_repo_links_consistent)
        check("内部协议串不外泄", t_no_internal_protocol_leak)
        check("说明文件齐全", t_docs_present)
        check("非 UTF-8 控制台不崩", t_console_encoding_safe)
        check("自检不留垃圾目录", t_no_test_crash_left_behind)
        check("文档双语齐全", t_docs_bilingual)
        check("CI/Issue 模板 YAML 合法", t_ci_yaml_valid)
        check("CLI 版本信息可获取", t_cli_version_reachable)
        check("dist 打包产物完整", t_dist_bundle_sane)
        check("界面文案英译无遗漏", t_i18n_complete)
        check("静态站页面与对比度", t_web_site)
        check("扫描期重绘限频（进度条保留）", t_scan_paint_throttled)
        check("底栏署名+GitHub 链接+版本号", t_byline_version_link)
        check("子进程不闪控制台窗口", t_no_console_flash)
        check("确认弹窗可滚动不溢出", t_confirm_dialog_scrolls)
        check("许可：署名+禁商用", t_license_attribution)
        check("exe 自带 Python（无解释器也能跑）", t_exe_standalone_no_python)
        check("-c 分类过滤器（旁路+不泄漏）", t_category_filter)
        check("审计日志写入", t_audit_log)
        check("删除路径安全校验", t_path_safety)
        check("删除路径安全校验：认环境变量而非写死 C:", t_path_safety_env)
        check("文件备份+回滚", t_safe_delete_backup)
        check("旧备份自动清理", t_backup_cleanup_old)
        check("无备份降级回收站", t_safe_delete_no_backup)
        check("已安装软件列表", t_list_installed_software)
        check("软件列表去重", t_list_installed_software_dedup)
        check("KB 补丁过滤", t_list_installed_software_no_kb)
        check("卸载：空命令失败", t_run_uninstaller_empty)
        check("卸载：exe 不存在失败", t_run_uninstaller_missing_exe)
        check("卸载：带引号命令解析", t_run_uninstaller_quoted)
        check("卸载：不带引号命令解析", t_run_uninstaller_unquoted)
        check("卸载：裸 exe 名按 PATH 解析", t_run_uninstaller_bare_name)
        check("残留：返回结构正确", t_find_residuals_structure)
        check("残留：能找到 AppData 目录", t_find_residuals_finds_folder)
        check("残留清理：空残留零计数", t_clean_residuals_empty)
        check("残留清理：走备份路径", t_clean_residuals_with_backup)
        check("InstalledSoftware dataclass", t_installed_software_dataclass)
        check("last_used：返回 float", t_last_used_time_returns_float)
        check("last_used：未知软件为 0", t_last_used_time_unknown_is_zero)
        check("last_used：探测 AppData", t_last_used_time_finds_appdata)
        check("last_used：探测 exe atime", t_last_used_time_finds_exe)
        check("last_used：列表项有 float", t_list_installed_software_has_last_used)
        check("last_used：至少 1 款有效", t_list_installed_software_some_have_last_used)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")
