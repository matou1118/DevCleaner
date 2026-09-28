# -*- coding: utf-8 -*-
"""本地验证：点「确认清理」到底删没删。

之前那次回归（缩进多一层）之所以漏过去，就是因为没有任何检查碰过
「点确认之后到底发生了什么」—— 弹窗能开、按钮能点、界面不闪，
唯独没人看文件有没有消失。

    python tools/cleantest.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QMessageBox   # noqa: E402
import app as engine                                       # noqa: E402
import gui                                                 # noqa: E402


class Fake:
    """do_clean 用得到的最小条目字段集。"""
    def __init__(self, p: Path):
        self.name = p.name
        self.path = str(p)
        self.size = p.stat().st_size
        self.unit = "bytes"
        self.risk = "safe"
        self.state = "pending"
        self.category = "T"
        self.note = ""
        self.meta = ""
        self.out_path = ""
        self.out_size = 0
        self.icon = "\U0001f4e6"
        self.title = ""


def main() -> int:
    qa = QApplication(sys.argv[:1])
    w = gui.MainWindow()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())

    d = Path(tempfile.mkdtemp(prefix="dcclean_"))
    victims = []
    for n in range(3):
        p = d / f"victim{n}.txt"
        p.write_text("x" * 1000, encoding="utf-8")
        victims.append(p)

    tracks = [Fake(p) for p in victims]
    engine.STATE.items = list(tracks)
    w.pick = {t.path for t in tracks}
    w.recalc()

    print(f"  清理前: {sum(p.exists() for p in victims)}/3 个文件存在")
    for p in victims:
        print(f"    {p.name}  {p.stat().st_size} bytes")

    # 确认按钮自动接受。do_clean 是异步的（清理跑在 CleanThread 里，靠 done
    # 信号回调），所以必须转事件循环等它完成 —— 同步调用只会看到 0 个文件被删，
    # 那是我这个测试过时了，不是代码坏了。
    real_info = QMessageBox.information
    QMessageBox.information = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok)

    real_exec = gui.ConfirmDialog.exec

    def auto_accept(self):
        gui.ConfirmDialog.exec = real_exec      # 先还原，避免递归
        self.accept()
        return 1                                # QDialog.Accepted

    gui.ConfirmDialog.exec = auto_accept
    try:
        w.do_clean()
        # 等清理线程收工
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            qa.processEvents()
            th = getattr(w, "clean_thread", None)
            if th is None or not th.isRunning():
                break
            time.sleep(0.02)
        # 再多转几圈，让 done 回调（_on_clean_done）跑完
        for _ in range(80):
            qa.processEvents()
            time.sleep(0.01)
    finally:
        gui.ConfirmDialog.exec = real_exec
        QMessageBox.information = real_info

    left = [p for p in victims if p.exists()]
    print(f"  清理后: {len(left)}/3 个文件仍存在")
    for t in tracks:
        print(f"    {Path(t.path).name}: state={t.state}")

    ok = not left and all(t.state == "done" for t in tracks)
    print()
    print("  PASS 点确认后文件真的消失了" if ok
          else f"  FAIL 还没删干净: {[p.name for p in left]}")
    engine.STATE.items = []
    w.pick = set()
    w.close()
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
