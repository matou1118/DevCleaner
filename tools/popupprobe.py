# -*- coding: utf-8 -*-
"""扫描期间监视屏幕上有没有「新窗口」冒出来。

前三次诊断都抓错了东西：offscreen 平台没窗口合成、心跳显示主线程没被饿死、
抓屏抓到了 160x28 的工具提示窗（不是主窗口）。真正的元凶是：GUI 子系统程序
拉起控制台子进程时，Windows 会给它新建一个控制台窗口，屏幕上就闪一个黑框。

这个探针不问"主窗口像素变没变"，而是枚举所有顶层可见窗口，看有没有**之前
不存在的新窗口**（控制台窗口的类名是 ConsoleWindowClass / CASCADIA_HOSTING）。

    python tools/popupprobe.py
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXE = ROOT / "dist" / "DevCleaner.exe"
if not EXE.is_file():
    print("!! dist/DevCleaner.exe 不存在，先跑 build.bat")
    sys.exit(1)

user32 = ctypes.windll.user32

IGNORE = {"Progman", "Shell_TrayWnd", "Windows.UI.Core.CoreWindow",
          "ApplicationFrameWindow", "Button", "SysShadow", "tooltips_class32",
          "TaskListThumbnailWnd", "ForegroundStaging", "MultitaskingViewFrame"}


def snapshot():
    """当前所有可见顶层窗口: {hwnd: (类名, 标题, 面积)}"""
    out = {}

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, buf, 256)
        cls = buf.value
        if cls in IGNORE:
            return True
        n = user32.GetWindowTextLengthW(h)
        tb = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, tb, n + 1)
        r = wt.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
        if area > 0:
            out[h] = (cls, tb.value, area)
        return True

    user32.EnumWindows(cb, 0)
    return out


def main() -> int:
    print(f"exe: {EXE.name}  {EXE.stat().st_size / 1048576:.1f} MB")
    before = snapshot()
    print(f"启动前可见顶层窗口: {len(before)} 个")
    print(f"  {Counter(c for c, _t, _a in before.values()).most_common(6)}")
    print()

    p = subprocess.Popen([str(EXE)], cwd=str(ROOT))
    time.sleep(3)          # 等窗口起来，把主窗口算进基线
    base = snapshot()
    print(f"主窗口出现后: {len(base)} 个")
    print("开始监视新窗口…（扫描约 30 秒）\n")

    seen = Counter()
    samples = []
    t0 = time.monotonic()
    n = 0
    while time.monotonic() - t0 < 75:
        cur = snapshot()
        new = {h: v for h, v in cur.items() if h not in base}
        for h, (cls, title, area) in new.items():
            seen[cls] += 1
            if len(samples) < 12:
                samples.append((round(time.monotonic() - t0, 1), cls, title[:40], area))
        n += 1
        if p.poll() is not None:
            break
        time.sleep(0.02)    # 50Hz 采样，控制台窗口通常显示几十~几百毫秒

    try:
        p.kill()
    except Exception:
        pass

    print(f"采样 {n} 次 / {time.monotonic() - t0:.1f}s")
    if not seen:
        print("\nOK 扫描期间没有任何新窗口冒出来")
        return 0
    print(f"\n!! 扫描期间出现的新窗口类型: {dict(seen)}")
    for t, cls, title, area in samples:
        print(f"   t={t:5.1f}s  {cls:28} {area:8}px  {title!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
