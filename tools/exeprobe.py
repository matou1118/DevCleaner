# -*- coding: utf-8 -*-
"""直接测打包后的 dist\\DevCleaner.exe —— 前两次诊断就是漏了这一步。

screenprobe.py / starve.py 跑的是 `python gui.py`，而用户跑的是 exe。
onefile 打包后多了一层 bootloader 进程、DPI 感知可能不同、依赖被 excludes
裁过。源码里量到的结论不一定在 exe 上成立，所以必须单独测 exe。

    python tools/exeprobe.py
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXE = ROOT / "dist" / "DevCleaner.exe"
if not EXE.is_file():
    print("!! dist/DevCleaner.exe 不存在，先跑 build.bat")
    sys.exit(1)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BI(ctypes.Structure):
    _fields_ = [("bmiHeader", BIH), ("bmiColors", wt.DWORD * 3)]


def find(title_part: str) -> int:
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, b, n + 1)
            if title_part in b.value:
                hits.append(h)
        return True

    user32.EnumWindows(cb, 0)
    return hits[0] if hits else 0


def grab(hwnd: int):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None, 0, 0
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)
    bi = BI()
    bi.bmiHeader.biSize = ctypes.sizeof(BIH)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    a = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
    return a[:, :, :3].copy(), w, h


def main() -> int:
    print(f"exe: {EXE}  ({EXE.stat().st_size / 1048576:.1f} MB)")
    print(f"built: {EXE.stat().st_mtime}")
    print()

    r = subprocess.run([str(EXE), "--version"], capture_output=True,
                       text=True, errors="replace", timeout=300)
    out = (r.stdout or "") + (r.stderr or "")
    print(f"--version: rc={r.returncode}  out={out.strip()!r}")
    if r.returncode != 0:
        print("!! exe 起不来")
        return 1
    print()

    p = subprocess.Popen([str(EXE)], cwd=str(ROOT))
    hwnd = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 60:
        hwnd = find("DevCleaner")
        if hwnd:
            break
        time.sleep(0.3)
    if not hwnd:
        print("!! 60 秒内没出现窗口")
        p.kill()
        return 1

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ww, wh = rect.right - rect.left, rect.bottom - rect.top
    print(f"窗口 {ww}x{wh}  hwnd={hwnd}")
    print("等它自动扫完第一轮，同时抓帧…")

    frames, boxes = [], []
    last = None
    last_shape = None
    resized = 0
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        f, _, _ = grab(hwnd)
        if f is None:
            break
        # 窗口尺寸会变（扫描时布局调整/最小化恢复）。只跟同尺寸的上一帧比，
        # 否则 numpy 广播不上。而且尺寸变化本身就是一次全窗重绘，得单独记。
        if last is not None and f.shape == last.shape:
            d = np.abs(f.astype(np.int16) - last.astype(np.int16)).sum(axis=2)
            ch = int((d > 24).sum())
            frames.append(ch)
            if ch > 40:
                ys, xs = np.where(d > 24)
                boxes.append((len(frames), ch, int(xs.min()), int(ys.min()),
                              int(xs.max()), int(ys.max())))
        elif last is not None:
            resized += 1
            print(f"  [窗口尺寸变了 {last.shape} -> {f.shape}]")
        last = f
        if p.poll() is not None:
            break
        time.sleep(0.012)

    try:
        p.kill()
    except Exception:
        pass

    if not frames:
        print(f"!! 同尺寸的帧太少（尺寸变了 {resized} 次），测不出来")
        return 1
    ch = np.array(frames)
    tot = ww * wh
    print(f"抓到 {len(frames)} 帧同尺寸对比（另有 {resized} 次尺寸变化）")
    print(f"每帧变化像素: 中位 {int(np.median(ch))}  最大 {int(ch.max())}  "
          f"(全窗 {tot} = {ch.max() / tot * 100:.1f}%)")
    still = int((ch <= 40).sum())
    print(f"几乎不变的帧: {still}/{len(frames)} ({still / len(frames) * 100:.0f}%)")
    if boxes:
        print(f"有明显变化的帧: {len(boxes)}")
        for n, c, x0, y0, x1, y1 in boxes[:16]:
            print(f"  帧{n:4} {c:8}px  {x0},{y0} -> {x1},{y1}")
        ys0 = min(b[3] for b in boxes)
        ys1 = max(b[5] for b in boxes)
        print(f"变化纵向范围 y {ys0}..{ys1}  (进度条那行大约 y=117..175)")
        # 全窗范围内变化 = 闪；只在进度条行 = 正常推进
        if ys0 < 100 or ys1 > 200:
            print("\n!! 变化超出进度条那一行 —— 全窗在重绘，这就是闪")
            return 1
    print("\nOK 变化只在进度条那一行，没有全窗重绘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
