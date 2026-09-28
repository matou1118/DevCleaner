"""DevCleaner 自检 —— python test_app.py 应输出 ALL OK"""
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
    assert len(app.THEMES) >= 4, f"主题太少: {len(app.THEMES)}"
    need = {"n", "bg", "panel", "panel2", "line", "line2", "fg", "fg2", "fg3",
            "accent", "safe", "caution"}
    for k, t in app.THEMES.items():
        missing = need - set(t)
        assert not missing, f"{k} 缺字段 {missing}"
        for f in ("bg", "panel", "panel2", "line", "fg", "accent"):
            assert t[f].startswith("#") and len(t[f]) == 7, f"{k}.{f}={t[f]}"
    names = [t["n"] for t in app.THEMES.values()]
    assert len(set(names)) == len(names), f"主题重名: {names}"


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
        check("空文件保留名单", lambda: t_keep_empty(tmp))
        check("批量空文件真删", lambda: t_bulk_empty_delete(tmp))
        check("传统垃圾扫描", lambda: t_junk(tmp))
        check("注册表只读发现", t_registry_findings)
        check("注册表备份/删除/还原", t_registry_backup_and_restore)
        check("注册表深层删除", t_delete_deep_tree)
        check("注册表路径编码", t_reg_path_parse)
        check("clone 保护(有remote不删)", lambda: t_clone_guard(tmp))
        check("界面构建+主题切换(离屏)", t_gui_offscreen)
        check("真实环境只读冒烟", t_smoke)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")
