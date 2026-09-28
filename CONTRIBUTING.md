# 贡献指南

感谢你愿意动手。这个项目很小，规则也少，但有**一条硬性要求**。

## 硬性要求：改清理判据必须同时加测试

这不是形式主义。这个工具会删你机器上的东西，一个判据写错的代价是
「删掉在用的东西且无法还原」。

所以：

- 改任何 `Scanner` 的判据 → 在 `test_app.py` 里加一个用例，**先让它失败，再让它通过**
- 修一个误判 → 加一个用例盯住它不再犯（参考 `t_no_false_orphan`）
- 放宽任何安全阀 → 在同一个 PR 里说明你凭什么认为安全

`python test_app.py` 必须全绿才能合。CI 会在 Python 3.10~3.13 上各跑一遍。

## 环境

```bash
pip install -r requirements.txt
python test_app.py        # 29 项自检，约 40 秒
python gui.py             # 本地试
build.bat                 # 打包成 dist\DevCleaner.exe
```

只改前端/文档的话可以不装 PySide6，但自检里有一项会离屏构建界面，装上省事。

## 代码风格

跟着周围代码走。具体：

- **标准库优先。** 引擎只用 `psutil` + `PyYAML`，其余全是标准库。加工具前先想想标准库有没有
- **不引入新依赖**，除非它能换掉一大段自己写的代码。加之前先在 Issue 里问
- **不重构没被要求改的东西。** 想动的地方单独开 PR
- 中文界面文案可以直接写，但 `build.bat` 必须是纯 ASCII —— cmd 按 OEM 代码页读 `.bat`，中文加 `&` 会被误解析成不存在的命令
- 不要用 PowerShell 的 `Get-Content`/`Set-Content` 改源码，它们按 ANSI 读 UTF-8，会把中文搞成乱码

## 提交前

```bash
python test_app.py
git status          # 别误提交 build/ dist/ __pycache__/
```

`.reg` 备份和扫描结果都不要提交。`settings.yaml` 要提交（它是默认配置），但你自己机器上的路径改动请走 `settings.local.yaml`。

## 加一个扫描器

```python
class MyScanner(Scanner):
    category, icon = "我的分类", "\U0001f9f0"

    def scan(self) -> List[Item]:
        return [mk(self.category, Path("C:/some/cache"), "名称", "safe",
                   note="为什么可以安全删除")]
```

然后塞进 `SCANNERS` 列表。界面会自动多出一个折叠分组，**不用改 UI 代码**。

两条要求：

- `risk` 要诚实。拿不准就用 `caution`，用户不会被自动勾选
- 如果这类项的体积是 0（注册表、空文件这种），`Item.unit` 填 `"count"` —— 界面会按条目数显示，不拿字节数骗人

## 改配色

色值在 `app.py` 的 `_PALETTES`，原始设计稿在 `docs/palette-directions.html`。

次级/三级文字色、分割线、强调色上的文字色都是**推导出来的**，不要手抄 —— 改了主色它们会自动跟着走。

如果新配色过不了 WCAG AA，`t_theme_contrast` 会拦下来。文字在强调色上的对比度不够时，它会在白色和底色之间自动选更高的那个。

## 改界面

`gui.py` 一个文件，QSS 由 `build_qss(theme)` 生成。

有个坑在代码注释里写过了：勾选态上色用 `QPalette`，**不要**用
`setObjectName` + `unpolish/polish`。后者会让 Qt 重新解析整份样式表，
自动全选 27 行就是 27 次全量重算连续触发，主线程卡死，表现为整窗闪动。
`t_no_repolish_on_check` 会守住这条。

## 翻译

`README.en.md` / `CONTRIBUTING.en.md` / `SECURITY.en.md` 和中文版对照。
改了中文版记得同步英文版。界面文案 i18n 还没做（见路线图）。

## 不接受的东西

- 扫描并删除无法用程序判定的目录
- 遍历 `HKCR\CLSID` 之类的注册表区域
- 为了减少代码行数而牺牲可读性
- 依赖管理员权限才能用的功能（除了 `HKLM` 下的键，那条失败时已经会明确报「权限不足」）

## 行为准则

见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
