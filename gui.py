"""DevCleaner 原生界面（PySide6）。扫描逻辑全在 app.py，这里只管显示。"""
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                                QFrame, QHBoxLayout, QHeaderView, QLabel,
                                QLineEdit, QMainWindow, QMessageBox, QPushButton,
                                QScrollArea, QSizePolicy, QTableWidget,
                                QTableWidgetItem, QTextEdit, QVBoxLayout,
                                QWidget, QProgressBar)

import app as engine
import lang
from lang import T, set_lang

# 勾选态底色，由 apply_theme 按当前主题算出（模块级，ItemRow 构造时用默认值）
SEL_TINT = "rgba(91,140,255,26)"


def fmt(it) -> str:
    """按条目单位显示：注册表/空文件这类是「条目数」，不是字节"""
    if getattr(it, "unit", "bytes") == "count":
        return f"{it.size} {T('项')}"
    return engine.human(it.size)


def _mix(sizes: List[int], units: List[str]) -> str:
    b = sum(s for s, u in zip(sizes, units) if u != "count")
    c = sum(s for s, u in zip(sizes, units) if u == "count")
    parts = []
    if b:
        parts.append(engine.human(b))
    if c:
        parts.append(f"{c} {T('项')}")
    return " + ".join(parts) or "0 B"


def build_qss(t: Dict[str, str]) -> str:
    return f"""
/* 背景只给窗口和卡片，中间层一律透明。
   之前是 `QWidget {{ background:... }}` 给每个控件都上底色，Qt 的重绘是从
   子控件往上传播的 —— 每层都有背景，脏区就一路涨到顶层，于是「改一个进度条
   = 全窗重绘」。实测 14 次进度回调引发 81 次 Paint、MainWindow 被重绘 17 次，
   扫描期肉眼就是满屏闪。底色只画一次，子控件透明，重绘就停在原地。 */
QMainWindow, QWidget#root {{ background:{t['bg']}; }}
QLabel, QCheckBox, QScrollArea, QTextEdit, QProgressBar {{
  color:{t['fg']}; font-family:"Microsoft YaHei UI","Segoe UI",sans-serif; font-size:13px;
  border:none; }}
QScrollArea > QWidget > QWidget {{ background:transparent; border:none; }}

#title    {{ font-size:20px; font-weight:600; color:{t['fg']}; }}
#subtitle {{ font-size:12px; color:{t['fg3']}; }}

#statK    {{ font-size:10px; color:{t['fg3']}; letter-spacing:1px; }}
#statV    {{ font-size:19px; font-weight:600; }}
#statOk   {{ font-size:19px; font-weight:600; color:{t['safe']}; }}
#statWarn {{ font-size:19px; font-weight:600; color:{t['caution']}; }}

QFrame#statTile {{ background:{t['panel2']}; border:1px solid {t['line']}; border-radius:9px; }}
QFrame#card     {{ background:{t['panel']};  border:1px solid {t['line']}; border-radius:10px; }}
QFrame#cardHead {{ background:transparent; border:none; }}
QFrame#row      {{ background:transparent; border:none;
                   border-bottom:1px solid {t['line']}; }}
QFrame#row:hover {{ background:{t['panel2']}; }}
QFrame#rowSel   {{ background:rgba(91,140,255,26); }}
QFrame#rowRo    {{ background:transparent; border:none;
                   border-bottom:1px solid {t['line']}; }}
QFrame#foot     {{ background:{t['bg']}; border-top:1px solid {t['line2']}; }}

QLabel#catName  {{ font-size:14px; font-weight:600; color:{t['fg']}; }}
QLabel#catCount {{ font-size:11px; color:{t['fg3']}; }}
QLabel#catSize  {{ font-size:14px; font-weight:600; color:{t['fg']}; }}
QLabel#catHint  {{ font-size:11px; color:{t['fg3']}; }}
QLabel#itemName {{ font-size:13px; font-weight:600; color:{t['fg']}; }}
QLabel#itemPath {{ font-size:10px; color:{t['fg3']}; font-family:Consolas,monospace; }}
QLabel#itemMeta {{ font-size:10px; color:{t['fg2']}; }}
QLabel#itemNote {{ font-size:10px; color:{t['fg3']}; font-style:italic; }}
QLabel#itemSize {{ font-size:13px; font-weight:600; color:{t['fg']}; }}
QLabel#badgeSafe    {{ font-size:10px; color:{t['safe']}; }}
QLabel#badgeCaution {{ font-size:10px; color:{t['caution']}; }}
QLabel#badgeNote    {{ font-size:10px; color:{t['fg3']}; }}
QLabel#stage    {{ font-size:12px; color:{t['fg2']}; }}
QLabel#footText {{ font-size:12px; color:{t['fg2']}; }}
QLabel#themeLbl {{ font-size:12px; color:{t['fg3']}; }}
QFrame#cardHead {{ cursor:pointer; }}

QPushButton {{ background:{t['panel2']}; border:1px solid {t['line2']}; border-radius:6px;
              padding:7px 15px; color:{t['fg']}; }}
QPushButton:hover   {{ background:{t['panel']}; border-color:{t['accent']}; }}
QPushButton:pressed {{ background:{t['bg']}; }}
QPushButton:disabled{{ color:{t['fg3']}; border-color:{t['line']}; background:{t['panel']}; }}
QPushButton#primary {{ background:{t['accent']}; border-color:{t['accent']};
                      color:{t['onaccent']}; font-weight:600; padding:8px 20px; }}
QPushButton#primary:hover    {{ background:{t['accent2']}; border-color:{t['accent2']}; }}
QPushButton#primary:disabled {{ background:{t['panel2']}; border-color:{t['line']};
                               color:{t['fg3']}; }}
QPushButton#head {{ background:transparent; border:none; text-align:left; padding:0; }}
QPushButton#small {{ padding:4px 11px; font-size:11px; }}

QComboBox {{ background:{t['panel2']}; border:1px solid {t['line2']}; border-radius:6px;
             padding:5px 10px; color:{t['fg']}; min-width:88px; }}
QComboBox:hover {{ border-color:{t['accent']}; }}
QComboBox::drop-down {{ border:none; width:20px; }}
QComboBox QAbstractItemView {{ background:{t['panel2']}; border:1px solid {t['line2']};
              selection-background-color:{t['accent']}; color:{t['fg']}; }}

QCheckBox {{ spacing:8px; }}
QCheckBox::indicator {{ width:16px; height:16px; border:1px solid {t['line2']};
                       border-radius:4px; background:{t['bg']}; }}
QCheckBox::indicator:hover {{ border-color:{t['accent']}; }}
QCheckBox::indicator:checked {{ background:{t['accent']}; border-color:{t['accent']};
                                image:url("__CHECK__"); }}

QProgressBar {{ background:{t['panel']}; border:1px solid {t['line']}; border-radius:4px;
                height:6px; text-align:center; }}
QProgressBar::chunk {{ background:{t['accent']}; border-radius:4px; }}

QTextEdit {{ background:{t['panel']}; border:1px solid {t['line']}; border-radius:8px;
             color:{t['fg2']}; font-family:Consolas,monospace; font-size:11px; }}
/* 确认对话框的明细区：要比正文大一点，等宽，方便对路径 */
QTextEdit#detail {{ font-size:12px; color:{t['fg']}; }}
QPushButton#dangerOk {{ background:{t['caution']}; border-color:{t['caution']};
                       color:{t['bg']}; font-weight:700; padding:8px 22px; }}
QPushButton#dangerOk:hover {{ opacity:.9; }}

QScrollBar:vertical {{ background:transparent; width:11px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{t['line2']}; border-radius:5px; min-height:36px; }}
QScrollBar::handle:vertical:hover {{ background:{t['fg3']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
"""


def _human_path(it) -> str:
    """显示给人看的路径/位置。内部协议串（REG: / BULK:）绝不能露给用户。"""
    p = getattr(it, "path", "")
    if p.startswith("REG:"):
        op, _, arg = p[4:].partition(":")
        if op == "mru":
            return T(r"HKCU 下 10 个「资源管理器使用记录」键")
        return arg or p
    if p.startswith("BULK:"):
        n = len(engine.expand_bulk(p))
        return T(f"扫描根目录下匹配的 {n} 个空文件 / 空目录 / 断链（逐条删除）")
    return p


def _lbl(text: str, obj: str = "", parent: Optional[QWidget] = None) -> QLabel:
    w = QLabel(text, parent)
    if obj:
        w.setObjectName(obj)
    return w


def _make_check_png(color: str) -> str:
    """QSS 没法画对勾，只能给它一张图。运行时用 QPainter 画一张，省掉打包资源。
    颜色要跟主题走 —— 白对勾压在浅强调色（Rosé Pine / Tokyo Night）上几乎看不见。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainter, QPen, QPixmap
    d = Path(os.environ.get("TEMP", ".")) / f"devcleaner_check_{color.lstrip('#')}.png"
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color), 2.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline([QPointF(3.5, 8.4), QPointF(6.6, 11.6), QPointF(12.5, 4.8)])
    p.end()
    pm.save(str(d), "PNG")
    return d.as_posix()


_check_png_cache: Dict[str, str] = {}


# ============================ 条目行 ============================


class ItemRow(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, it, selectable: bool, parent=None):
        super().__init__(parent)
        self.path = it.path
        self.setObjectName("rowRo" if not selectable else "row")
        self.sel_color = SEL_TINT          # 勾选态底色，由 apply_theme 刷新
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 9, 14, 9)
        h.setSpacing(11)

        self.cb = QCheckBox()
        self.cb.setEnabled(selectable)
        self.cb.toggled.connect(lambda v: self.toggled.emit(self.path, v))
        h.addWidget(self.cb, 0, Qt.AlignmentFlag.AlignTop)

        body = QWidget()
        body.setObjectName("rowRo")
        b = QVBoxLayout(body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(2)
        b.addWidget(_lbl(getattr(it, "name", "—"), "itemName"))
        b.addWidget(_lbl(_human_path(it), "itemPath"))
        if it.meta:
            b.addWidget(_lbl(it.meta, "itemMeta"))
        if getattr(it, "note", ""):
            b.addWidget(_lbl(it.note, "itemNote"))
        h.addWidget(body, 1)

        right = QWidget()
        right.setObjectName("rowRo")
        r = QVBoxLayout(right)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(3)
        r.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        r.addWidget(_lbl(fmt(it), "itemSize"))
        risk = getattr(it, "risk", "note")
        txt = T({"safe": "安全", "caution": "需确认"}.get(risk, "只读"))
        obj = {"safe": "badgeSafe", "caution": "badgeCaution"}.get(risk, "badgeNote")
        r.addWidget(_lbl(txt, obj))
        h.addWidget(right, 0)

    def set_checked(self, on: bool) -> None:
        self.cb.blockSignals(True)
        self.cb.setChecked(on)
        self.cb.blockSignals(False)
        # 用 palette 上色，不要 setObjectName + unpolish/polish。
        # 后者会让 Qt 重新解析整份样式表，勾选 30 个条目就是 30 次全量重算，
        # 主线程直接卡住 —— 表现就是整窗闪。
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window,
                     QColor(self.sel_color) if on else QColor(0, 0, 0, 0))
        self.setPalette(pal)


# ============================ 分类卡片 ============================


class CategoryCard(QFrame):
    def __init__(self, title: str, icon: str, items, hint: str, selectable: bool,
                 on_change, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.rows: List[ItemRow] = []
        self.selectable = selectable
        self.on_change = on_change
        self.title = title

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QFrame()
        head.setObjectName("cardHead")
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        hh = QHBoxLayout(head)
        hh.setContentsMargins(14, 11, 14, 11)
        hh.setSpacing(10)
        self.arrow = _lbl("▾")
        self.arrow.setObjectName("catCount")
        hh.addWidget(_lbl(icon, "catName"))
        self.name = _lbl(title, "catName")
        hh.addWidget(self.name)
        n = len(items)
        units = [getattr(i, "unit", "bytes") for i in items]
        if selectable:
            sub = sum(1 for i in items if i.risk == "safe")
            hh.addWidget(_lbl(T(f"{n} 项 · 安全 {sub}"), "catCount"))
        hh.addStretch(1)
        if hint:
            hh.addWidget(_lbl(hint, "catHint"))
        self.size = _lbl(_mix([i.size for i in items], units), "catSize")
        hh.addWidget(self.size)
        hh.addWidget(self.arrow)
        head.mousePressEvent = self._flip
        v.addWidget(head)
        self.head = head
        self.body = QWidget()
        self.body.setObjectName("rowRo")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        for it in items:
            row = ItemRow(it, selectable)
            row.toggled.connect(on_change)
            bl.addWidget(row)
            self.rows.append(row)
        v.addWidget(self.body)

        if selectable and items:
            bar = QFrame()
            bar.setObjectName("cardHead")
            fb = QHBoxLayout(bar)
            fb.setContentsMargins(14, 7, 14, 7)
            fb.setSpacing(8)
            b_all = QPushButton(T("全选本组"))
            b_all.setObjectName("small")
            b_none = QPushButton(T("清选本组"))
            b_none.setObjectName("small")
            b_all.clicked.connect(lambda: self._bulk(True))
            b_none.clicked.connect(lambda: self._bulk(False))
            fb.addWidget(b_all)
            fb.addWidget(b_none)
            fb.addStretch(1)
            fb.addWidget(_lbl(T(f"共 {_mix([i.size for i in items], units)}"), "catHint"))
            v.addWidget(bar)
            self.footbar = bar
        else:
            self.footbar = None
        self.set_total(items)
        self.set_expanded(expanded)

    def set_expanded(self, on: bool) -> None:
        """默认折叠：一屏能看完所有分类，不必一路往下翻"""
        self.body.setVisible(on)
        if self.footbar is not None:
            self.footbar.setVisible(on)
        self.arrow.setText("▾" if on else "▸")

    def expanded(self) -> bool:
        # 用 isHidden 而不是 isVisible：isVisible 会因为祖先未显示而恒为 False，
        # 只有 isHidden 表达「是我们主动折叠的」这一个意思。
        return not self.body.isHidden()

    def set_total(self, items) -> None:
        units = [getattr(i, "unit", "bytes") for i in items]
        self.size.setText(_mix([i.size for i in items], units))

    def _flip(self, _e) -> None:
        self.set_expanded(self.body.isHidden())

    def _bulk(self, on: bool) -> None:
        for r in self.rows:
            if r.cb.isEnabled():
                r.cb.setChecked(on)
        self.on_change(None, False)

    def set_all(self, on: bool) -> None:
        for r in self.rows:
            if r.cb.isEnabled():
                r.cb.setChecked(on)
                r.set_checked(on)


# ============================ 扫描线程 ============================


class ScanThread(QThread):
    progressed = Signal(str, float)
    done = Signal()

    def run(self) -> None:
        # 扫描线程几乎全程持 GIL 做 os.scandir/stat。sys.setswitchinterval 就是
        # 主线程的最坏等待时间：之前设的 25ms 意味着 UI 每 40ms 才有机会画一次，
        # 配合「一次重绘=全窗重绘」就是肉眼可见的闪。压回 5ms（默认）让主线程
        # 随时能插进来 —— 扫描慢一点无所谓，界面不能闪。
        old = sys.getswitchinterval()
        try:
            sys.setswitchinterval(0.005)
            engine.run_scan(on_progress=lambda s, p: self.progressed.emit(s, p))
        finally:
            sys.setswitchinterval(old)
        self.done.emit()


class CleanThread(QThread):
    """后台执行清理，避免阻塞 GUI 事件循环。

    旧代码把删除循环直接跑在主线程上，file_locked 又逐文件遍历所有进程，
    proc.open_files() 在某些系统进程上会无限阻塞 → 界面卡死、清理走不到。
    """
    progressed = Signal(str, int, int)          # 当前条目名, 已完成, 总数
    done = Signal(list, list, list)             # ok_names, failures, backups

    def __init__(self, sel: List) -> None:
        super().__init__()
        self.sel = sel

    def run(self) -> None:
        # SHFileOperationW 是 Shell COM API，在未初始化 COM 的线程里调用会死锁。
        # GUI 线程由 Qt 自动初始化了 COM，但 QThread 不会继承。这里手动初始化 STA。
        import ctypes
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
        except OSError:
            pass
        try:
            self._run_body()
        finally:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except OSError:
                pass

    def _run_body(self) -> None:
        ok_n: List[str] = []
        fail: List[str] = []
        backups: List[str] = []
        # 创建文件备份会话（用于回滚）；注册表类不走此路径
        backup_dir, session_id = engine.create_backup_session()
        # 批量检测占用：只遍历一次进程列表，而非逐文件遍历
        file_paths = [i.path for i in self.sel
                      if not i.path.startswith("REG:") and not i.path.startswith("BULK:")]
        locked = engine.locked_set(file_paths)
        total = len(self.sel)
        for idx, i in enumerate(self.sel):
            self.progressed.emit(i.name, idx, total)
            if i.path.startswith("REG:"):
                good, msg = engine.apply_registry_item(i)
                if good:
                    ok_n.append(i.name)
                    if "备份" in msg:
                        bk = msg.split("备份", 1)[1].strip()
                        backups.append(bk)
                        engine.audit_log("BACKUP", f"{i.name} | {bk}")
                else:
                    fail.append(f"{i.name}（{msg}）")
                engine.audit_log("OK" if good else "FAIL",
                                 f"REG | {i.name} | {i.path} | {msg}")
                continue
            if i.path.startswith("BULK:"):
                a, b, errs = engine.delete_bulk(i.path)
                ok_n.append(f"{i.name}（{a} 项）")
                if b:
                    fail.extend(errs[:5])
                engine.audit_log("OK" if not b else "FAIL",
                                 f"BULK | {i.name} | {i.path} | 成功 {a} 失败 {b}")
                continue
            p = Path(i.path)
            if not p.exists():
                fail.append(f"{i.name}（已不存在）")
                engine.audit_log("SKIP", f"{i.name} | {i.path} | 已不存在")
                continue
            if os.path.normcase(i.path) in locked:
                fail.append(f"{i.name}（被进程占用）")
                engine.audit_log("SKIP", f"{i.name} | {i.path} | 被进程占用")
                continue
            good, msg = engine.safe_delete(i.path, backup_dir=backup_dir)
            if good:
                ok_n.append(i.name)
            else:
                fail.append(f"{i.name}（{msg}）")
            engine.audit_log("OK" if good else "FAIL",
                             f"FILE | {i.name} | {i.path} | {msg}")
        # 如果备份目录为空（全是注册表/批量），清理掉
        try:
            if not any(backup_dir.iterdir()):
                backup_dir.rmdir()
        except OSError:
            pass
        self.done.emit(ok_n, fail, backups)


# ============================ 主窗口 ============================


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{engine.APP_NAME} {engine.__version__} · {T('本地清理')}")
        self.resize(1180, 900)
        self.setMinimumSize(880, 620)
        self.pick: set = set()
        self.cards: List[CategoryCard] = []
        self.notes_cards: List[CategoryCard] = []
        self.thread: Optional[ScanThread] = None
        self.clean_thread: Optional[CleanThread] = None
        self.theme = engine.DEFAULT_THEME
        self._remember = True     # 构造期套用默认主题时不回写配置
        self._last_stage_text = ""

        # 启动时清理 7 天前的文件备份
        try:
            engine.cleanup_old_backups(7)
        except OSError:
            pass

        # 启动时清理 7 天前的文件备份
        try:
            engine.cleanup_old_backups(7)
        except OSError:
            pass

        root = QWidget()
        root.setObjectName("root")     # QSS 只给它上底色，其余控件透明（见 build_qss）
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 头部 ----
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 16, 22, 12)
        hl.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_lbl("● DevCleaner", "title"))
        # 副标题给伸缩因子：英文比中文长一截，不设的话会被右边的下拉框压掉
        # 尾巴（中文下刚好不露，英文下就剩 "everything goes to the Recycl"）。
        sub = _lbl(T("本地独立清理 · 文件先备份，7 天内可回滚"), "subtitle")
        sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        titles.addWidget(sub)
        hl.addLayout(titles, 1)
        hl.addStretch(0)
        self.cb_theme = QComboBox()
        for k in engine.THEME_ORDER:
            self.cb_theme.addItem(engine.THEMES[k]["n"], k)
        self.cb_theme.setToolTip(T("配色主题"))
        default = engine.DEFAULT_THEME
        if default in engine.THEME_ORDER:
            self.cb_theme.setCurrentIndex(engine.THEME_ORDER.index(default))
        self.cb_theme.currentIndexChanged.connect(self.apply_theme)
        hl.addWidget(_lbl(T("主题"), "themeLbl"))
        hl.addWidget(self.cb_theme)

        # ---- 语言 ----
        self.cb_lang = QComboBox()
        self.cb_lang.addItem("中文", "zh")
        self.cb_lang.addItem("English", "en")
        self.cb_lang.setCurrentIndex(0 if lang.LANG == "zh" else 1)
        self.cb_lang.setToolTip(T("语言"))
        self.cb_lang.currentIndexChanged.connect(self._switch_lang)
        hl.addWidget(_lbl(T("语言"), "themeLbl"))
        hl.addWidget(self.cb_lang)
        self.t_safe = self._tile(hl, T("安全可清"), "—", "statOk")
        self.t_caut = self._tile(hl, T("需确认"), "—", "statWarn")
        self.t_tot = self._tile(hl, T("合计"), "—", "statV")
        outer.addWidget(head)

        # ---- 工具条 ----
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(22, 0, 22, 12)
        bl.setSpacing(11)
        self.btn_scan = QPushButton(T("开始扫描"))
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self.start_scan)
        bl.addWidget(self.btn_scan)
        self.btn_expand = QPushButton(T("全部展开"))
        self.btn_expand.clicked.connect(
            lambda: self._set_all_expanded(not self.cards[0].expanded()
                                           if self.cards else False))
        bl.addWidget(self.btn_expand)
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        self.prog.setRange(0, 100)
        bl.addWidget(self.prog, 1)
        self.stage = _lbl(T("待命"), "stage")
        self.stage.setMinimumWidth(190)
        bl.addWidget(self.stage)
        outer.addWidget(bar)

        # ---- 列表 ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.holder = QWidget()
        self.holder.setObjectName("rowRo")
        self.list_layout = QVBoxLayout(self.holder)
        self.list_layout.setContentsMargins(22, 0, 22, 10)
        self.list_layout.setSpacing(11)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.holder)
        outer.addWidget(self.scroll, 1)
        self.placeholder = _lbl(T("点击「开始扫描」查找可清理项"), "catCount")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_layout.insertWidget(0, self.placeholder)

        # ---- 日志 ----
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(112)
        self.log.hide()
        outer.addWidget(self.log)

        # ---- 底栏 ----
        foot = QFrame()
        foot.setObjectName("foot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(22, 10, 22, 10)
        fl.setSpacing(10)
        self.foot = _lbl(T("已选 0 项 · 0 B"), "footText")
        fl.addWidget(self.foot)
        # 署名 + 可点的 GitHub 链接。点开用系统默认浏览器，不在应用内导航。
        self.ver = _lbl(f"{engine.OWNER} {T('GitHub')} v{engine.__version__}", "catHint")
        self.ver.setToolTip(
            f"{engine.REPO}\n"
            f"CC BY-NC 4.0 · 署名 Matou1118 · 禁商用\n"
            f"Attribution required · Non-commercial only")
        self.ver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ver.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.ver.setOpenExternalLinks(True)
        self._set_byline(engine.THEMES[self.theme]["accent"]
                         if self.theme in engine.THEMES else "#7aa2f7")
        fl.addWidget(self.ver)
        fl.addStretch(1)
        b_all = QPushButton(T("全选安全项"))
        b_all.clicked.connect(lambda: self.bulk(True))
        b_none = QPushButton(T("清空选择"))
        b_none.clicked.connect(lambda: self.bulk(False))
        self.btn_clean = QPushButton(T("移入备份目录"))
        self.btn_clean.setObjectName("primary")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(self.do_clean)
        for b in (b_all, b_none, self.btn_clean):
            fl.addWidget(b)
        self.btn_log = QPushButton(T("日志"))
        self.btn_log.setObjectName("small")
        self.btn_log.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        fl.addWidget(self.btn_log)
        self.btn_hist = QPushButton(T("历史"))
        self.btn_hist.setObjectName("small")
        self.btn_hist.clicked.connect(self._show_history)
        fl.addWidget(self.btn_hist)
        self.btn_rollback = QPushButton(T("回滚"))
        self.btn_rollback.setObjectName("small")
        self.btn_rollback.clicked.connect(self._show_rollback)
        fl.addWidget(self.btn_rollback)
        self.btn_uninstall = QPushButton(T("软件卸载"))
        self.btn_uninstall.setObjectName("small")
        self.btn_uninstall.clicked.connect(self._show_uninstall)
        fl.addWidget(self.btn_uninstall)
        outer.addWidget(foot)

    def _tile(self, parent_layout, k, v, obj) -> QLabel:
        f = QFrame()
        f.setObjectName("statTile")
        f.setMinimumWidth(128)
        l = QVBoxLayout(f)
        l.setContentsMargins(14, 9, 14, 9)
        l.setSpacing(1)
        l.addWidget(_lbl(k, "statK"))
        val = _lbl(v, obj)
        l.addWidget(val)
        parent_layout.addWidget(f)
        return val

    # ---------------- 扫描 ----------------
    def start_scan(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.pick.clear()
        self._clear_cards()
        self.placeholder.setText(T("正在扫描…"))
        self.placeholder.show()            # 扫描中必须可见
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText(T("扫描中…"))
        self.btn_expand.setEnabled(False)
        # 走马灯（setRange(0,0)）会自己连续重绘，而本窗口任意一次重绘都是全窗
        # （160+ 个带样式的子控件，样式表让它们互相牵连）—— 那是扫描期满屏闪的
        # 来源。改成用 run_scan 给的真实百分比：整数没变就不重绘。
        self.prog.setRange(0, 100)
        self.prog.setValue(0)
        self._last_stage_text = ""
        self._last_stage = 0.0
        self._last_pct = -1
        self.stage.setText(T("准备中"))
        self.log.clear()
        # 不再 setUpdatesEnabled(False)：那会把进度条一起关掉（用户反馈"没有进度条"），
        # 而 tools/screenprobe.py 的抓屏实测显示窗口像素本来就是稳的 —— 31 秒扫描
        # 402 帧里只有 8 帧变化，全在进度条那一行（y=117..175，x 从 231 推到 941）。
        # tools/starve.py ��显示主线程拿到了 100% 时间片、零卡顿。
        # 所以「全窗口关更新」是砍错地方。真正要省的是重绘次数：进度条限到
        # 4 次/秒 + 整数变了才重绘，肉眼看着在动，但每秒只有 4 次重绘。
        self.thread = ScanThread()
        self.thread.progressed.connect(self._on_progress)
        self.thread.done.connect(self._on_done)
        self.thread.start()

    def _on_progress(self, stage: str, p: float) -> None:
        # 进度条：setValue 内部只在整数变化时重绘，很便宜。
        try:
            v = int(max(0.0, min(1.0, float(p))) * 100)
        except (TypeError, ValueError):
            v = 0
        if v != self._last_pct:
            self._last_pct = v
            self.prog.setValue(v)
        # 阶段文字：既节流又去重。setText 内容相同也触发重绘，而扫描里大量阶段名
        # 是重复的（9 个扫描器各自报一次），不去重就是白刷。
        txt = T(stage)
        now = time.monotonic()
        if txt != self._last_stage_text and now - self._last_stage >= 0.25:
            self._last_stage_text = txt
            self._last_stage = now
            self.stage.setText(txt)

    def _on_done(self) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText(T("重新扫描"))
        self.btn_expand.setEnabled(True)
        self.stage.setText(T(f"完成 · {engine.STATE.finished_at}"))
        self.prog.setRange(0, 100)
        self.prog.setValue(100)
        self.log.setPlainText("\n".join(engine.STATE.log))
        if any(l.startswith(("[失败", "[异常")) for l in engine.STATE.log):
            self.log.show()          # 出错了才主动亮出来
            self.btn_log.setText(T("隐藏日志"))
        self._render()
        self.bulk(True, only_safe=True)
        self.recalc()

    def _clear_cards(self) -> None:
        for c in self.cards + self.notes_cards:
            self.list_layout.removeWidget(c)
            c.deleteLater()
        self.cards.clear()
        self.notes_cards.clear()

    def _render(self) -> None:
        self._clear_cards()
        # 占位文字由 _render 自己管。之前只在 _on_done 里 hide()，
        # 任何别的路径调 _render（比如重新渲染）都会留下一句
        # "点击开始扫描"压在真实内容上面。
        self.placeholder.setVisible(not engine.STATE.items and not engine.STATE.notes)
        groups: dict = {}
        for it in engine.STATE.items:
            groups.setdefault(it.category, []).append(it)
        for cat, rows in groups.items():
            rows.sort(key=lambda x: -x.size)
            c = CategoryCard(T(cat), rows[0].icon or "●", rows, T("可回收"),
                             True, self._on_toggle)
            self.list_layout.insertWidget(self.list_layout.count() - 1, c)
            self.cards.append(c)
        kinds: dict = {}
        for n in engine.STATE.notes:
            kinds.setdefault(n.kind or "其他", []).append(n)
        for kind, rows in kinds.items():
            rows.sort(key=lambda x: -x.size)
            c = CategoryCard(T(f"{kind}（只读）"), "\U0001f512", rows, T("不提供删除"),
                             False, self._on_toggle)
            self.list_layout.insertWidget(self.list_layout.count() - 1, c)
            self.notes_cards.append(c)
        self._set_all_expanded(False)
        self.t_safe.setText(engine.human(sum(i.size for i in engine.STATE.items
                                              if i.risk == "safe" and i.unit != "count")))
        self.t_caut.setText(engine.human(sum(i.size for i in engine.STATE.items
                                              if i.risk == "caution" and i.unit != "count")))
        self.t_tot.setText(engine.human(sum(i.size for i in engine.STATE.items
                                            if i.unit != "count")))
        n_extra = sum(1 for i in engine.STATE.items if i.unit == "count")
        if n_extra:
            self.stage.setText(T(f"完成 · {engine.STATE.finished_at} · 另有 {n_extra} 项按条目计"))

    # ---------------- 选择 ----------------
    def _on_toggle(self, path: Optional[str], on: bool) -> None:
        if path is None:                      # 来自「全选本组」
            self.recalc()
            return
        if on:
            self.pick.add(path)
        else:
            self.pick.discard(path)
        for c in self.cards:
            for r in c.rows:
                if r.path == path:
                    r.set_checked(on)
        self.recalc()

    def bulk(self, on: bool, only_safe: bool = False) -> None:
        for c in self.cards:
            for r in c.rows:
                it = next((x for x in engine.STATE.items if x.path == r.path), None)
                if it is None:
                    continue
                yes = on and (not only_safe or it.risk == "safe")
                r.cb.setChecked(yes)
                r.set_checked(yes)
                if yes:
                    self.pick.add(r.path)
                else:
                    self.pick.discard(r.path)
        self.recalc()

    def recalc(self) -> None:
        sel = [i for i in engine.STATE.items if i.path in self.pick]
        self.foot.setText(T(
            f"已选 {len(sel)} 项 · "
            + _mix([i.size for i in sel], [getattr(i, "unit", "bytes") for i in sel])))
        self.btn_clean.setEnabled(bool(sel))

    def _set_all_expanded(self, on: bool) -> None:
        for c in self.cards + self.notes_cards:
            c.set_expanded(on)
        self.btn_expand.setText(T("全部折叠") if on else T("全部展开"))

    # ---------------- 语言 ----------------
    def _switch_lang(self, idx: int) -> None:
        """切语言要重建窗口：文案散在各处 setText 里，没有统一的重绘入口。
        扫描线程在跑时不重建（STATE 会被正在跑的线程改），下次启动生效。"""
        code = self.cb_lang.itemData(idx)
        if code == lang.LANG:
            return
        set_lang(code)
        engine.set_config_value("lang", f'"{code}"')
        if self.thread and self.thread.isRunning():
            return
        self.close()
        w = MainWindow()
        if engine.STATE.items or engine.STATE.notes:
            w._render()
        w.show()
        self._next = w       # 不给引用会被 GC 掉，窗口一闪就没

    # ---------------- 主题 ----------------
    def _set_byline(self, accent: str) -> None:
        byline = f'{engine.OWNER} {T("GitHub")} v{engine.__version__}'
        self.ver.setText(f'<a href="{engine.REPO}" style="color:{accent};'
                         f'text-decoration:none">{byline}</a>')

    def apply_theme(self, idx: int) -> None:
        key = self.cb_theme.itemData(idx)
        t = engine.THEMES.get(key)
        if not t:
            return
        qa = QApplication.instance()
        if qa is None:
            return
        check = _check_png_cache.get(t["onaccent"])
        if not check:
            check = _make_check_png(t["onaccent"])
            _check_png_cache[t["onaccent"]] = check
        qa.setStyleSheet(build_qss(t).replace("__CHECK__", check))
        self.theme = key
        # 署名链接是富文本，颜色写死在 HTML 里，换主题要重刷
        if hasattr(self, "ver"):
            self._set_byline(t["accent"])
        # 勾选底色是按主题算的，换主题要重刷一遍（palette 改色，不重解析样式表）
        global SEL_TINT
        SEL_TINT = t["sel"]
        for c in self.cards + self.notes_cards:
            for r in c.rows:
                r.sel_color = SEL_TINT
                r.set_checked(r.cb.isChecked())
        if self._remember:
            engine.set_config_value("theme", f'"{key}"')   # 记住选择，重启仍是这套

    # ---------------- 清理 ----------------
    def do_clean(self) -> None:
        sel = [i for i in engine.STATE.items if i.path in self.pick]
        if not sel:
            return
        if self.clean_thread and self.clean_thread.isRunning():
            return
        risky = [i for i in sel if i.risk == "caution"]
        regs = [i for i in sel if i.path.startswith("REG:")]
        # 预览：分类汇总 + 风险分解
        preview = _clean_preview(sel)
        # 明细最多列 60 条，剩下的在末尾汇总 —— 列表可滚动了，不用那么保守
        detail = _confirm_details(sel[:60])
        if len(sel) > 60:
            detail += f"\n{T('… 另有')} {len(sel) - 60} {T('项')}"

        if regs:
            summary = T(f"确认清理 {len(sel)} 项，其中 {len(regs)} 项是注册表修改？")
            note = T(
                f"文件类会备份到本地（7 天内可回滚）。\n"
                f"注册表类会先备份 .reg 到\n{engine.backup_root()}\n"
                f"再删除，导出失败则不会删除。还原方式：对备份目录里的 .reg 执行 reg import。\n\n")
            dlg = ConfirmDialog(self, T("确认清理"), summary,
                                preview + note + detail, _confirm_risky(risky), danger=bool(regs))
        else:
            extra = T("其中包含批量删除，请注意条目数。") if any(
                i.path.startswith("BULK:") for i in sel) else ""
            summary = T(f"确认清理 {len(sel)} 个条目，"
                        f"合计 {_mix([i.size for i in sel], [getattr(i, 'unit', 'bytes') for i in sel])}？{extra}")
            dlg = ConfirmDialog(self, T("确认清理"), summary, preview + detail,
                                _confirm_risky(risky), danger=bool(risky))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self.btn_clean.setEnabled(False)
        self.setCursor(Qt.CursorShape.WaitCursor)
        self.stage.setText(T("清理中…"))
        self._clean_has_regs = bool(regs)
        self.clean_thread = CleanThread(sel)
        self.clean_thread.progressed.connect(self._on_clean_progress)
        self.clean_thread.done.connect(self._on_clean_done)
        self.clean_thread.start()

    def _on_clean_progress(self, name: str, done: int, total: int) -> None:
        self.stage.setText(T(f"清理中 {done}/{total} · {name}"))
        if total > 0:
            self.prog.setRange(0, total)
            self.prog.setValue(done)

    def _on_clean_done(self, ok_n: List[str], fail: List[str],
                       backups: List[str]) -> None:
        self.unsetCursor()
        self.prog.setRange(0, 100)
        self.prog.setValue(100)
        report = [f"成功 {len(ok_n)} 项"]
        if backups:
            report.append("\n注册表备份位置：\n" + "\n".join(sorted(set(backups))))
        if ok_n and not getattr(self, "_clean_has_regs", False):
            report.append("\n文件已备份到本地，7 天内可点「回滚」还原。")
        if fail:
            report.append(f"\n未处理 {len(fail)} 项：\n· " + "\n· ".join(fail[:15]))
        QMessageBox.information(self, T("清理结果"), "\n".join(report))
        self.bulk(False)
        self._render()
        self.recalc()

    def _show_history(self) -> None:
        """显示清理审计日志（最近 200 行）。"""
        p = engine.audit_log_path()
        lines: list = []
        if p.is_file():
            try:
                all_lines = p.read_text(encoding="utf-8").splitlines()
                lines = all_lines[-200:]
            except OSError:
                lines = []
        dlg = QDialog(self)
        dlg.setWindowTitle(T("历史"))
        dlg.setMinimumWidth(620)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 12)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText("\n".join(lines) if lines else T("暂无清理历史"))
        v.addWidget(view)
        b = QPushButton(T("关闭"))
        b.clicked.connect(dlg.accept)
        v.addWidget(b)
        dlg.exec()

    def _show_rollback(self) -> None:
        """显示可回滚的备份会话，选中后一键还原。"""
        sessions = engine.list_backup_sessions()
        dlg = QDialog(self)
        dlg.setWindowTitle(T("回滚"))
        dlg.setMinimumWidth(580)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 12)
        if not sessions:
            lbl = QLabel(T("暂无可回滚的备份"))
            v.addWidget(lbl)
            b = QPushButton(T("关闭"))
            b.clicked.connect(dlg.accept)
            v.addWidget(b)
            dlg.exec()
            return
        view = QTextEdit()
        view.setReadOnly(True)
        lines = []
        for s in sessions[:20]:
            lines.append(f"■ {s['id']}  —  {s['count']} {T('项')}  {engine.human(s['size'])}")
        view.setPlainText("\n".join(lines))
        v.addWidget(view)
        # 选择会话 ID
        from PySide6.QtWidgets import QComboBox
        combo = QComboBox()
        for s in sessions[:20]:
            combo.addItem(f"{s['id']}  ({s['count']} {T('项')}, {engine.human(s['size'])})", s["id"])
        v.addWidget(combo)
        btns = QHBoxLayout()
        b_restore = QPushButton(T("回滚选中会话"))
        b_restore.setObjectName("primary")
        b_cancel = QPushButton(T("关闭"))
        b_cancel.clicked.connect(dlg.accept)
        b_restore.clicked.connect(lambda: self._do_rollback(combo.currentData(), dlg))
        btns.addWidget(b_cancel)
        btns.addStretch(1)
        btns.addWidget(b_restore)
        v.addLayout(btns)
        dlg.exec()

    def _do_rollback(self, session_id: str, parent_dlg) -> None:
        """执行回滚并显示结果。"""
        if not session_id:
            return
        ok, fail, errs = engine.restore_backup_session(session_id)
        engine.audit_log("ROLLBACK", f"会话 {session_id} | 成功 {ok} 失败 {fail}")
        msg = [f"{T('回滚完成')}：{T('成功')} {ok} {T('项')}"]
        if fail:
            msg.append(f"{T('失败')} {fail} {T('项')}：\n" + "\n".join(errs[:10]))
        QMessageBox.information(self, T("回滚结果"), "\n".join(msg))
        parent_dlg.accept()
        self.bulk(False)
        self._render()
        self.recalc()

    # ---------------- 软件卸载 ----------------
    def _show_uninstall(self) -> None:
        """软件卸载主对话框：列出已安装软件，搜索选择后运行其卸载程序。"""
        import time as _time
        dlg = QDialog(self)
        dlg.setWindowTitle(T("软件卸载"))
        dlg.setMinimumWidth(780)
        dlg.setMinimumHeight(520)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 12)

        # 搜索框
        search = QLineEdit()
        search.setPlaceholderText(T("搜索软件名称…"))
        v.addWidget(search)

        # 软件列表表格（5 列：名称 / 发布者 / 上次使用 / 闲置天数 / 大小）
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(
            [T("软件名称"), T("发布者"), T("上次使用"), T("闲置天数"), T("大小(MB)")])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        v.addWidget(table)

        # 状态标签
        status = QLabel(T("正在读取已安装软件列表…"))
        v.addWidget(status)

        # 加载软件列表
        software_list = engine.list_installed_software()
        sort_by_idle = [True]   # 默认按闲置排序（最久没用过的排前面）
        displayed: list = []    # 当前表格行 → InstalledSoftware 对象

        def _idle_text(sw) -> str:
            if sw.last_used <= 0:
                return "—"
            days = int((_time.time() - sw.last_used) / 86400)
            if days <= 0:
                return T("今天")
            return f"{days}{T('天')}"

        def _date_text(sw) -> str:
            if sw.last_used <= 0:
                return T("未知")
            return _time.strftime("%Y-%m-%d", _time.localtime(sw.last_used))

        def populate(filter_text: str = ""):
            nonlocal displayed
            table.setRowCount(0)
            displayed = []
            ft = filter_text.lower()
            filtered = [sw for sw in software_list
                        if not ft or ft in sw.name.lower() or ft in sw.publisher.lower()]
            # 排序：按闲置 → last_used 升序（0 排最前）；按名称 → 字母序
            if sort_by_idle[0]:
                filtered.sort(key=lambda s: s.last_used)
            else:
                filtered.sort(key=lambda s: s.name.lower())
            for sw in filtered:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(sw.name))
                table.setItem(row, 1, QTableWidgetItem(sw.publisher))
                table.setItem(row, 2, QTableWidgetItem(_date_text(sw)))
                table.setItem(row, 3, QTableWidgetItem(_idle_text(sw)))
                table.setItem(row, 4, QTableWidgetItem(
                    str(sw.size_mb) if sw.size_mb else ""))
                displayed.append(sw)
            status.setText(f"{T('共')} {table.rowCount()} {T('款软件')}")

        populate()
        search.textChanged.connect(lambda t: populate(t))

        # 按钮区
        btns = QHBoxLayout()
        b_sort = QPushButton(T("按闲置排序"))
        b_refresh = QPushButton(T("刷新列表"))
        b_uninstall = QPushButton(T("运行卸载程序"))
        b_uninstall.setObjectName("primary")
        b_close = QPushButton(T("关闭"))
        b_close.clicked.connect(dlg.accept)

        def toggle_sort():
            sort_by_idle[0] = not sort_by_idle[0]
            b_sort.setText(T("按闲置排序") if not sort_by_idle[0] else T("按名称排序"))
            populate(search.text())

        b_sort.clicked.connect(toggle_sort)

        def do_uninstall():
            row = table.currentRow()
            if row < 0 or row >= len(displayed):
                QMessageBox.warning(dlg, T("提示"), T("请先选择要卸载的软件"))
                return
            sw = displayed[row]
            # 确认
            ans = QMessageBox.question(
                dlg, T("确认卸载"),
                f"{T('即将运行卸载程序')}\n\n{sw.name}\n{sw.publisher}\n\n"
                f"{T('卸载完成后将自动扫描残留文件和注册表')}\n"
                f"{T('是否继续')}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
            # 运行卸载程序
            status.setText(T("正在运行卸载程序，请等待完成…"))
            dlg.repaint()
            ok, msg = engine.run_uninstaller(sw.uninstall_string, wait=True)
            engine.audit_log("UNINSTALL", f"{sw.name} | {msg}")
            if not ok:
                QMessageBox.warning(dlg, T("卸载失败"), msg)
                status.setText(T("卸载失败"))
                return
            # 扫描残留
            status.setText(T("正在扫描残留…"))
            dlg.repaint()
            residuals = engine.find_residuals(sw.name, sw.install_location)
            total = (len(residuals["registry"]) +
                     len(residuals["folders"]) +
                     len(residuals["shortcuts"]))
            if total == 0:
                QMessageBox.information(dlg, T("卸载完成"),
                                        f"{sw.name} {T('已卸载')}\n{T('未发现残留')}")
                status.setText(T("卸载完成，无残留"))
                populate(search.text())
                return
            # 显示残留清理对话框
            self._show_residuals(dlg, sw, residuals)
            populate(search.text())
            status.setText(T("卸载完成"))

        b_uninstall.clicked.connect(do_uninstall)

        def do_refresh():
            nonlocal software_list
            status.setText(T("正在刷新…"))
            dlg.repaint()
            software_list = engine.list_installed_software()
            populate(search.text())

        b_refresh.clicked.connect(do_refresh)

        btns.addWidget(b_sort)
        btns.addWidget(b_refresh)
        btns.addStretch(1)
        btns.addWidget(b_close)
        btns.addWidget(b_uninstall)
        v.addLayout(btns)
        dlg.exec()

    def _show_residuals(self, parent_dlg, sw, residuals: dict) -> None:
        """显示卸载后残留项，让用户选择清理。"""
        dlg = QDialog(parent_dlg)
        dlg.setWindowTitle(T("残留清理") + f" — {sw.name}")
        dlg.setMinimumWidth(600)
        dlg.setMinimumHeight(420)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 12)

        view = QTextEdit()
        view.setReadOnly(True)
        lines: list = []

        # 注册表残留
        reg = residuals.get("registry", [])
        if reg:
            lines.append(f"{'═' * 50}")
            lines.append(f"⚠ {T('注册表残留')} ({len(reg)} {T('项')})")
            lines.append(f"{'─' * 50}")
            for r in reg[:30]:
                lines.append(f"  {r}")
            if len(reg) > 30:
                lines.append(f"  … {T('等')} {len(reg)} {T('项')}")
            lines.append("")

        # 文件夹残留
        folders = residuals.get("folders", [])
        if folders:
            lines.append(f"{'═' * 50}")
            lines.append(f"📁 {T('文件夹残留')} ({len(folders)} {T('项')})")
            lines.append(f"{'─' * 50}")
            for f in folders:
                lines.append(f"  {f}")
            lines.append("")

        # 快捷方式残留
        lnks = residuals.get("shortcuts", [])
        if lnks:
            lines.append(f"{'═' * 50}")
            lines.append(f"🔗 {T('快捷方式残留')} ({len(lnks)} {T('项')})")
            lines.append(f"{'─' * 50}")
            for l in lnks:
                lines.append(f"  {l}")
            lines.append("")

        view.setPlainText("\n".join(lines))
        v.addWidget(view)

        info = QLabel(
            f"{T('文件夹和快捷方式可安全清理（已备份，可回滚）')}\n"
            f"{T('注册表残留需手动确认，不会自动删除')}")
        v.addWidget(info)

        btns = QHBoxLayout()
        b_clean = QPushButton(T("清理残留"))
        b_clean.setObjectName("primary")
        b_skip = QPushButton(T("跳过"))
        b_skip.clicked.connect(dlg.accept)

        def do_clean():
            b_clean.setEnabled(False)
            b_clean.setText(T("正在清理…"))
            dlg.repaint()
            result = engine.clean_residuals(residuals,
                                             backup_dir=engine.file_backup_root())
            engine.audit_log("RESIDUAL_CLEAN",
                             f"{sw.name} | 删除 {result['deleted']} "
                             f"失败 {result['failed']} "
                             f"注册表待定 {result['reg_pending']}")
            msg = [f"{T('清理完成')}"]
            msg.append(f"  {T('已删除')} {result['deleted']} {T('项')}")
            if result['failed']:
                msg.append(f"  {T('失败')} {result['failed']} {T('项')}")
            if result['reg_pending']:
                msg.append(f"  ⚠ {T('注册表残留')} {result['reg_pending']} "
                           f"{T('项需手动处理')}")
            msg.append("")
            msg.append(T("已删除项已备份，可通过「回滚」恢复"))
            QMessageBox.information(dlg, T("残留清理结果"), "\n".join(msg))
            dlg.accept()

        b_clean.clicked.connect(do_clean)
        btns.addWidget(b_skip)
        btns.addStretch(1)
        btns.addWidget(b_clean)
        v.addLayout(btns)
        dlg.exec()


class ConfirmDialog(QDialog):
    """确认清理对话框，明细列表可上下滚动。

    为什么不用 QMessageBox：它的 setInformativeText 没有滚动条，条目一多
    （这里最多列 60 条）整个对话框就撑到超出屏幕，**确认按钮被顶到看不见
    的地方** —— 用户要么看不到按钮，要么瞎点。

    这里的做法：说明文字和明细**全部**放进一个 QTextEdit（自带滚动条、
    只读、可选中复制路径），对话框高度按屏幕可用高度硬封顶。这样不管
    说明多长、条目多少，按钮永远在可视区内。
    """

    MAX_H = 0.60          # 占屏幕可用高度比例上限。留足任务栏和标题栏

    def __init__(self, parent, title: str, summary: str, detail: str,
                 risky: str = "", danger: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(580)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        # 摘要单独一行（最重要的一句，不该被滚走）；其余全部进滚动区
        head = _lbl(summary, "itemName")
        head.setWordWrap(True)
        v.addWidget(head)

        body = []
        if risky:
            body.append(risky)
        if detail:
            body.append(detail)
        if body:
            self.view = QTextEdit()
            self.view.setReadOnly(True)
            self.view.setObjectName("detail")
            self.view.setPlainText("\n\n".join(body))
            # 高度：按内容算，但绝不超上限；下限保证少量条目时也别太小
            fm = self.view.document().documentLayout().documentSize()
            scr = QApplication.primaryScreen()
            avail = scr.availableGeometry().height() if scr else 800
            cap = int(avail * self.MAX_H)
            self.view.setFixedHeight(max(200, min(int(fm.height()) + 16, cap)))
            v.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        buttons.addStretch(1)
        b_cancel = QPushButton(T("取消"))
        b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(T("确认清理"))
        b_ok.setObjectName("dangerOk" if danger else "primary")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        buttons.addWidget(b_cancel)
        buttons.addWidget(b_ok)
        v.addLayout(buttons)

        # 双保险：整体高度也不许超过上限（防止某个平台忽略 QSS 或字体变大）。
        # 余量 96px = 摘要(约2行) + 标题栏 + 按钮行(约36) + 上下边距(约34)。
        # 不能再多 —— 728px 的小屏上每多 10px 余量都是在把按钮往屏幕外推。
        self.setMaximumHeight(cap + 96)


def _confirm_details(sel) -> str:
    """明细文本：每条两行（名字+大小 / 完整路径）。"""
    out = []
    for i in sel:
        out.append(f"· {i.name}  {fmt(i)}")
        out.append(f"  {_human_path(i)}")
    return "\n".join(out)


def _clean_preview(sel) -> str:
    """清理预览：按分类汇总空间 + 风险分解，让用户在确认前看清将删什么。"""
    from collections import OrderedDict
    by_cat: OrderedDict = OrderedDict()
    safe_n = caution_n = 0
    for i in sel:
        cat = i.category
        if cat not in by_cat:
            by_cat[cat] = {"count": 0, "size": 0, "unit": getattr(i, "unit", "bytes")}
        by_cat[cat]["count"] += 1
        if by_cat[cat]["unit"] != "count":
            by_cat[cat]["size"] += i.size
        if i.risk == "caution":
            caution_n += 1
        else:
            safe_n += 1
    lines = [T("── 清理预览 ──")]
    for cat, info in by_cat.items():
        sz = engine.human(info["size"]) if info["unit"] != "count" else f"{info['count']} {T('项')}"
        lines.append(f"  {cat}: {info['count']} {T('项')}  {sz}")
    lines.append(T(f"── 安全 {safe_n} 项 / 需确认 {caution_n} 项 ──"))
    lines.append("")
    return "\n".join(lines)


def _confirm_risky(risky) -> str:
    if not risky:
        return ""
    names = "\n".join("· " + i.name for i in risky[:12])
    more = (f"\n{T('… 另有')} {len(risky) - 12} {T('项')}" if len(risky) > 12 else "")
    return T(f"⚠ 其中 {len(risky)} 项标记为「需确认」：\n") + names + more




def main() -> int:
    # 打包成 console=False 的 GUI exe 后没有真实 stdout，print() 会失败或
    # 被丢弃。所以 --version/--help 走 stderr（stderr 永远可用）并用退出码
    # 表达结果；同时尽量也往 stdout 写一份，能写就写。
    def emit(msg: str) -> None:
        for name in ("stderr", "stdout"):
            try:
                getattr(sys, name).write(msg + "\n")
                getattr(sys, name).flush()
            except (OSError, ValueError, AttributeError):
                pass

    if "--version" in sys.argv or "-V" in sys.argv:
        emit(f"{engine.APP_NAME} {engine.__version__}")
        return 0
    if "--help" in sys.argv or "-h" in sys.argv:
        emit("DevCleaner - Windows 本地清理工具\n"
             "  DevCleaner.exe            打开界面（自动扫描）\n"
             "  DevCleaner.exe --version  打印版本\n"
             "配置见 exe 同目录的 settings.yaml")
        return 0
    set_lang(str(engine.CFG.get("lang") or "zh"))
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    qa = QApplication(sys.argv)
    qa.setApplicationName(engine.APP_NAME)
    qa.setApplicationVersion(engine.__version__)
    qa.setStyle("Fusion")
    qa.setFont(QFont("Microsoft YaHei UI", 9))
    w = MainWindow()
    w._remember = False          # 启动时应用默认主题，不回写
    w.apply_theme(w.cb_theme.currentIndex())
    w._remember = True
    w.show()
    QTimer.singleShot(250, w.start_scan)   # 打开就扫，不用手点
    return qa.exec()


if __name__ == "__main__":
    sys.exit(main())
