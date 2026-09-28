# -*- coding: utf-8 -*-
"""确认弹窗在各种屏幕高度下的实测数据。改完弹窗跑一遍看数字。

    python tools/dlgprobe.py
"""
import os
import sys
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QPushButton, QTextEdit  # noqa: E402
import gui                                                            # noqa: E402


def main() -> int:
    qa = QApplication(sys.argv[:1])
    w = gui.MainWindow()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())

    class F:
        """最坏情况：超长中文名 + 超长路径"""
        def __init__(self, n):
            self.name = f"条目 {n} " + "很长的名字" * 6
            self.path = "REG:" + "x" * 400
            self.size = 123456789
            self.unit = "bytes"
            self.risk = "safe"

    sel = [F(i) for i in range(60)]
    print(f"MAX_H = {gui.ConfirmDialog.MAX_H}")
    print()
    print(f"{'屏幕可用高':>10} {'对话框高':>9} {'明细区高':>9} {'按钮y':>10} "
          f"{'占屏':>6}  判定")
    bad = 0
    for avail in (1080, 1032, 900, 800, 728, 640, 560):
        geo = mock.Mock()
        geo.height.return_value = avail
        scr = mock.Mock()
        scr.availableGeometry.return_value = geo
        with mock.patch.object(QApplication, "primaryScreen",
                               staticmethod(lambda s=scr: s)):
            dlg = gui.ConfirmDialog(w, "确认清理", f"确认清理 {len(sel)} 项？",
                                    gui._confirm_details(sel),
                                    gui._confirm_risky(sel[:30]))
            h = dlg.sizeHint().height()
            view = dlg.findChild(QTextEdit)
            vh = view.height() if view else -1
            by = [b.mapTo(dlg, b.rect().center()).y()
                  for b in dlg.findChildren(QPushButton)]
        cap = int(avail * gui.ConfirmDialog.MAX_H)
        ok = (0 <= min(by) and max(by) <= h and h <= avail and vh <= cap
              and dlg.maximumHeight() <= cap + 96)
        if not ok:
            bad += 1
        print(f"{avail:>9}px {h:>8}px {vh:>8}px {str(by):>10} "
              f"{h / avail * 100:>5.0f}%  {'OK' if ok else '!! 按钮不可见'}")
        dlg.close()

    # 少量条目
    few = gui.ConfirmDialog(w, "确认清理", "确认清理 2 项？",
                            gui._confirm_details(sel[:2]))
    print()
    print(f"只有 2 条时: 对话框 {few.sizeHint().height()}px "
          f"（不该为了统一高度而空出一大片）")
    few.close()
    w.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
