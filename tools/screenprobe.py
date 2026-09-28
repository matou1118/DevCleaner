# -*- coding: utf-8 -*-
"""抓真实屏幕帧，看扫描期间到底哪块在变。

前两次诊断都错了：一次用 offscreen 数 Paint（那平台没窗口合成，测不出），
一次量主线程心跳（显示没被饿死，也不成立）。这次不猜了，直接看像素。

用 GDI BitBlt 抓 DevCleaner 那个窗口的区域，逐帧和前一帧比，报出：
- 变了多少像素
- 变化区域的包围盒（哪块在闪）
- 完全没变的帧占多少（闪是间歇的还是持续的）

    python tools/screenprobe.py
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def find_window(title_part: str) -> int:
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_part in buf.value:
                hits.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return hits[0] if hits else 0


def grab(hwnd: int) -> np.ndarray:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return np.zeros((1, 1, 3), np.uint8)
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)   # SRCCOPY
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # 负数 = top-down，省一次翻转
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    a = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
    return a[:, :, :3].copy()


def main() -> int:
    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtWidgets import QApplication
    import app as engine
    import gui

    qa = QApplication(sys.argv[:1])
    qa.setStyle("Fusion")
    w = gui.MainWindow()
    w.resize(1180, 900)
    w.show()
    w._remember = False
    w.apply_theme(w.cb_theme.currentIndex())
    QCoreApplication.processEvents()
    time.sleep(0.4)

    hwnd = find_window("DevCleaner")
    if not hwnd:
        print("!! 找不到窗口")
        return 1
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    print(f"窗口 hwnd={hwnd}  {r.right - r.left}x{r.bottom - r.top}")
    print("热身后先抓 10 帧静止画面作基线…")

    base = None
    noise = 0
    for _ in range(10):
        f = grab(hwnd)
        if base is None:
            base = f
        else:
            d = np.abs(f.astype(np.int16) - base.astype(np.int16))
            noise = max(noise, int(d.max()))
            base = f
    print(f"静止基线噪声: {noise} (0 = 完全静止)")
    print()

    frames, boxes = [], []
    # 对照实验：扫描期间是否关掉窗口更新。
    #   off = 当前行为（setUpdatesEnabled(False)，无进度条，稳）
    #   on  = 旧行为（更新开着，进度条能动）—— 看它到底闪不闪
    mode = sys.argv[1] if len(sys.argv) > 1 else "off"
    t0 = time.monotonic()
    w.start_scan()
    if mode == "on":
        w.setUpdatesEnabled(True)     # 抢在扫描开始前把更新打开
    print(f"模式: {mode}  (扫描期间窗口更新 {'开着' if mode == 'on' else '关着'})")
    last = base
    while w.thread and w.thread.isRunning():
        f = grab(hwnd)
        d = np.abs(f.astype(np.int16) - last.astype(np.int16)).sum(axis=2)
        changed = int((d > 24).sum())
        frames.append((time.monotonic() - t0, changed))
        if changed > 40:
            ys, xs = np.where(d > 24)
            boxes.append((len(frames), changed,
                          int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
        last = f
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    secs = time.monotonic() - t0

    tot_px = (r.right - r.left) * (r.bottom - r.top)
    print(f"扫描 {secs:.1f}s，抓了 {len(frames)} 帧")
    ch = np.array([c for _t, c in frames])
    print(f"每帧变化像素: 中位 {int(np.median(ch))}  最大 {int(ch.max())}  "
          f"(全窗口 {tot_px} 像素 = {ch.max() / tot_px * 100:.1f}%)")
    still = int((ch <= 40).sum())
    print(f"几乎不变的帧: {still}/{len(frames)} ({still / max(len(frames), 1) * 100:.0f}%)")
    if boxes:
        print(f"有明显变化的帧: {len(boxes)}")
        print("  帧号   变化像素   包围盒 x0,y0,x1,y1")
        for n, c, x0, y0, x1, y1 in boxes[:14]:
            print(f"  {n:5}   {c:9}   {x0},{y0} -> {x1},{y1}")
        xs0 = min(b[2] for b in boxes); ys0 = min(b[3] for b in boxes)
        xs1 = max(b[4] for b in boxes); ys1 = max(b[5] for b in boxes)
        print(f"\n变化总区域: x {xs0}..{xs1}  y {ys0}..{ys1}  "
              f"(窗口 {r.right - r.left}x{r.bottom - r.top})")
    w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
