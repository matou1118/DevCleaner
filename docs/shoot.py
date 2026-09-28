"""重拍 docs/ 下的界面截图。

离屏渲染真窗口，跑完真扫描再 grab —— 不用模拟数据，截图里的数字就是
本机实测。英文版靠 settings 里的 lang 切换。

    python docs/shoot.py            # 中文（默认主题）
    python docs/shoot.py en Ink     # 英文 + 指定主题
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 注意：别用 offscreen。离屏平台拿不到系统字体，每个字符都会画成豆腐块
# （方框），截图看着"布局对"其实是废图。要真窗口才有字。

import lang                                   # noqa: E402
import app as engine                          # noqa: E402
from PySide6.QtWidgets import QApplication   # noqa: E402
import gui                                    # noqa: E402


def shoot(win, name: str, settle: float = 0.45) -> Path:
    QApplication.processEvents()
    time.sleep(settle)
    QApplication.processEvents()
    out = ROOT / "docs" / f"{name}.png"
    win.grab().save(str(out))
    print(f"  {out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB")
    return out


def wait_scan(win, limit: float = 240.0) -> None:
    t0 = time.monotonic()
    while win.thread and win.thread.isRunning() and time.monotonic() - t0 < limit:
        QApplication.processEvents()
        time.sleep(0.05)
    QApplication.processEvents()
    time.sleep(0.3)


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else "zh"
    theme = sys.argv[2] if len(sys.argv) > 2 else engine.DEFAULT_THEME
    suffix = f".{code}" if code != "zh" else ""
    lang.set_lang(code)
    engine.set_config_value("lang", f'"{code}"')

    qa = QApplication(sys.argv[:1])
    qa.setStyle("Fusion")
    # 界面字体是 Microsoft YaHei UI；换语言时英文也走同一套 sans 兜底
    from PySide6.QtGui import QFont
    qa.setFont(QFont("Microsoft YaHei UI", 9))
    win = gui.MainWindow()
    win._remember = False
    win.apply_theme(win.cb_theme.currentIndex())
    win._remember = True
    win.resize(1180, 900)
    win.show()

    # 折叠态总览：10 个分类一屏放得下，是这版的卖点
    shoot(win, f"00-idle{suffix}")

    win.start_scan()
    wait_scan(win)
    if win.cards:
        win._set_all_expanded(False)
        shoot(win, f"01-overview{suffix}")
        win._set_all_expanded(True)
        shoot(win, f"02-expanded{suffix}")

    # 挑一个 caution 项弹确认框，让弹窗进截图
    risky = [i for i in engine.STATE.items if i.risk == "caution"] or engine.STATE.items
    if risky:
        win.bulk(False)
        for c in win.cards:
            for r in c.rows:
                if r.path == risky[0].path:
                    r.cb.setChecked(True)
        QApplication.processEvents()
        from PySide6.QtCore import QTimer
        box = None

        def grab_box():
            nonlocal box
            for w in qa.topLevelWidgets():
                if w.isVisible() and w.metaObject().className() == "QMessageBox":
                    box = w
                    break
            if box is not None:
                shoot(win, f"03-confirm{suffix}")
                box.reject()

        QTimer.singleShot(700, grab_box)
        win.do_clean()
    return 0


if __name__ == "__main__":
    sys.exit(main())
