"""DevCleaner 原生界面（PySide6）。扫描逻辑全在 app.py，这里只管显示。"""
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
                               QProgressBar)

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
        self.theme = engine.DEFAULT_THEME
        self._remember = True     # 构造期套用默认主题时不回写配置
        self._last_stage_text = ""

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
        sub = _lbl(T("本地独立清理 · 所有条目移入 Windows 回收站，可恢复"), "subtitle")
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
        self.btn_clean = QPushButton(T("移入回收站"))
        self.btn_clean.setObjectName("primary")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(self.do_clean)
        for b in (b_all, b_none, self.btn_clean):
            fl.addWidget(b)
        self.btn_log = QPushButton(T("日志"))
        self.btn_log.setObjectName("small")
        self.btn_log.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        fl.addWidget(self.btn_log)
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
        risky = [i for i in sel if i.risk == "caution"]
        regs = [i for i in sel if i.path.startswith("REG:")]
        # 明细最多列 60 条，剩下的在末尾汇总 —— 列表可滚动了，不用那么保守
        detail = _confirm_details(sel[:60])
        if len(sel) > 60:
            detail += f"\n{T('… 另有')} {len(sel) - 60} {T('项')}"

        if regs:
            summary = T(f"确认清理 {len(sel)} 项，其中 {len(regs)} 项是注册表修改？")
            note = T(
                f"文件类会移入回收站（可还原）。\n"
                f"注册表类会先备份 .reg 到\n{engine.backup_root()}\n"
                f"再删除，导出失败则不会删除。还原方式：对备份目录里的 .reg 执行 reg import。\n\n")
            dlg = ConfirmDialog(self, T("确认清理"), summary,
                                note + detail, _confirm_risky(risky), danger=bool(regs))
        else:
            extra = T("其中包含批量删除，请注意条目数。") if any(
                i.path.startswith("BULK:") for i in sel) else ""
            summary = T(f"确认清理 {len(sel)} 个条目，"
                        f"合计 {_mix([i.size for i in sel], [getattr(i, 'unit', 'bytes') for i in sel])}？{extra}")
            dlg = ConfirmDialog(self, T("确认清理"), summary, detail,
                                _confirm_risky(risky), danger=bool(risky))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

            self.btn_clean.setEnabled(False)
            self.setCursor(Qt.CursorShape.WaitCursor)
            ok_n: List[str] = []
            fail: List[str] = []
            backups: List[str] = []
            for i in sel:
                if i.path.startswith("REG:"):
                    good, msg = engine.apply_registry_item(i)
                    if good:
                        ok_n.append(i.name)
                        if "备份" in msg:
                            backups.append(msg.split("备份", 1)[1].strip())
                    else:
                        fail.append(f"{i.name}（{msg}）")
                    continue
                if i.path.startswith("BULK:"):
                    a, b, errs = engine.delete_bulk(i.path)
                    ok_n.append(f"{i.name}（{a} 项）")
                    if b:
                        fail.extend(errs[:5])
                    continue
                p = Path(i.path)
                if not p.exists():
                    fail.append(f"{i.name}（已不存在）")
                    continue
                if engine.file_locked(p):
                    fail.append(f"{i.name}（被进程占用）")
                    continue
                good, msg = engine.to_recycle_bin(i.path)
                if good:
                    ok_n.append(i.name)
                else:
                    fail.append(f"{i.name}（{msg}）")
            self.unsetCursor()
            report = [f"成功 {len(ok_n)} 项"]
            if backups:
                report.append("\n注册表备份位置：\n" + "\n".join(sorted(set(backups))))
            if ok_n and not regs:
                report.append("\n文件已进入回收站，清空回收站后才会真正释放空间。")
            if fail:
                report.append(f"\n未处理 {len(fail)} 项：\n· " + "\n· ".join(fail[:15]))
            QMessageBox.information(self, T("清理结果"), "\n".join(report))
            self.bulk(False)
            self._render()
            self.recalc()


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
