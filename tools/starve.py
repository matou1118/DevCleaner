# -*- coding: utf-8 -*-
"""量主线程在扫描期间被饿死多少。

上次用 offscreen 平台数 Paint 事件，那个平台没有窗口合成，测出来的
"只重绘 10 次"根本没意义。Windows 上的"弹窗拖影"是主线程来不及处理
WM_PAINT，Windows 画一层幽灵副本盖上去 —— 那是主线程调度问题。

真的指标是主线程的心跳：一个 16ms 的 QTimer 在扫描期间应该触发
~N 次（N = 扫描秒数 * 60）。少多少就是饿死了多少。

必须用真窗口平台测。offscreen 只能验逻辑，不能验手感。

    python tools/starve.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if "--offscreen" not in sys.argv:
    os.environ.pop("QT_QPA_PLATFORM", None)   # 真窗口
else:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication                                  # noqa: E402
import app as engine                                                          # noqa: E402
import gui                                                                     # noqa: E402


class Heartbeat(QObject):
    """16ms 一次的 QTimer。它触发几次 = 主线程被调度进去几次。"""

    def __init__(self):
        super().__init__()
        self.ticks = 0
        self.gaps = []
        self._last = time.monotonic()
        self.timer = QTimer()
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.monotonic()
        self.gaps.append(now - self._last)
        self._last = now
        self.ticks += 1

    def start(self):
        self._last = time.monotonic()
        self.timer.start()

    def stop(self):
        self.timer.stop()


def run_once(label: str, switch_interval: float, w, hb):
    """跑一次扫描，返回 (心跳数, 预期数, 最坏卡顿ms, >50ms 卡顿次数)。"""
    sys.setswitchinterval(switch_interval)
    engine.STATE.items.clear()
    engine.STATE.notes.clear()
    w._clear_cards()
    hb.ticks, hb.gaps = 0, []
    hb.start()
    t0 = time.monotonic()
    w.start_scan()
    while w.thread and w.thread.isRunning():
        QCoreApplication.processEvents()
        time.sleep(0.001)
    QCoreApplication.processEvents()
    secs = time.monotonic() - t0
    hb.stop()
    expected = secs * 1000.0 / 16.0
    worst_ms = max(hb.gaps) * 1000 if hb.gaps else 0.0
    stall = sum(1 for g in hb.gaps if g > 0.050)
    print(f"  {label}")
    print(f"    扫描时长        : {secs:.1f}s")
    print(f"    心跳 {hb.ticks} 次 / 预期 {expected:.0f} 次 "
          f"-> 主线程拿到 {hb.ticks / max(expected, 1) * 100:.0f}% 时间片")
    print(f"    最坏一次卡顿    : {worst_ms:.0f} ms")
    print(f"    >50ms 的卡顿    : {stall} 次")
    return hb.ticks, expected, worst_ms, stall


def main() -> int:
    qa = QApplication(sys.argv[:1])
    qa.setStyle("Fusion")
    w = gui.MainWindow()
    w.resize(1180, 900)
    w.show()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())
    QCoreApplication.processEvents()

    hb = Heartbeat()
    print("平台:", os.environ.get("QT_QPA_PLATFORM", "windows (真窗口)"))
    print()
    print("对照组：不扫描，空转 3 秒")
    sys.setswitchinterval(0.005)
    hb.ticks, hb.gaps = 0, []
    hb.start()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3.0:
        QCoreApplication.processEvents()
        time.sleep(0.001)
    hb.stop()
    exp = 3.0 * 1000 / 16
    print(f"    心跳 {hb.ticks} / 预期 {exp:.0f} "
          f"-> {hb.ticks / exp * 100:.0f}%   最坏 {max(hb.gaps) * 1000:.0f}ms")
    print()

    for si in (0.025, 0.005, 0.001):
        run_once(f"扫描中，sys.setswitchinterval = {si}", si, w, hb)
        print()

    sys.setswitchinterval(0.005)
    w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
