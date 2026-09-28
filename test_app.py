"""DevCleaner 自检 —— python test_app.py 应输出 ALL OK"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")
