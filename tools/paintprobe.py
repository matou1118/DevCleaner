# -*- coding: utf-8 -*-
"""数扫描期间重绘了多少次 —— 闪屏的唯一硬指标。

背景：这窗口有 160+ 个带样式的子控件，任意一次重绘都是全窗。扫描线程每拿到
一个 GIL 时间片就会唤醒主线程去 processEvents，于是单次扫描能引发数百次全窗
重绘，屏幕上就是满屏闪、像有弹窗拖影。走马灯进度条只是替罪羊。

现在的做法是扫描期 setUpdatesEnabled(False)，结束时统一铺一次。基线：
关更新前 ~81+ 次（MainWindow 17 次），关更新后 ~10 次（MainWindow 1 次）。

    QT_QPA_PLATFORM=offscreen python tools/paintprobe.py

退出码 0 = 没闪；1 = 扫描期重绘超过 40 次，闪没解决。
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject      # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402
import gui                                       # noqa: E402

THRESHOLD = 40      # 扫描期重绘上限。0.6 次/秒，实际值 ~10


class Counter(QObject):
    def __init__(self):
        super().__init__()
        self.total = 0
        self.by_type = {}

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Paint:
            self.total += 1
            name = type(obj).__name__
            self.by_type[name] = self.by_type.get(name, 0) + 1
        return False


def main() -> int:
    qa = QApplication(sys.argv[:1])
    qa.setStyle("Fusion")
    w = gui.MainWindow()
    w.resize(1180, 900)
    w.show()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())
    QApplication.processEvents()      # 预热：主题应用和首帧不计入

    pc = Counter()
    qa.installEventFilter(pc)

    t0 = time.monotonic()
    w.start_scan()
    updates_off = not w.updatesEnabled()
    while w.thread and w.thread.isRunning():
        QApplication.processEvents()
        time.sleep(0.002)
    QApplication.processEvents()
    secs = time.monotonic() - t0

    main_paints = pc.by_type.get("MainWindow", 0)
    print(f"扫描耗时         : {secs:.1f}s")
    print(f"扫描期关掉了更新  : {updates_off}")
    print(f"扫描期 Paint 事件 : {pc.total}  (阈值 {THRESHOLD})")
    print(f"其中 MainWindow  : {main_paints}  <- 每次就是一次全窗重绘")
    print(f"每秒重绘          : {pc.total / max(secs, 0.01):.1f}")
    print(f"按控件分          : {pc.by_type}")
    w.close()

    problems = []
    if not updates_off:
        problems.append("扫描期没有关掉窗口更新")
    if main_paints > 3:
        problems.append(f"MainWindow 被重绘 {main_paints} 次，全窗闪就是它")
    if pc.total > THRESHOLD:
        problems.append(f"总重绘 {pc.total} 次，超过阈值 {THRESHOLD}")
    if problems:
        print("\n!! 闪没解决: " + "; ".join(problems))
        return 1
    print(f"\nOK 扫描期 {pc.total} 次重绘、MainWindow {main_paints} 次 —— 不会闪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
