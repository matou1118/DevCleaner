# 更新日志

本文件记录 DevCleaner 的所有重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

**注意：0.x 阶段，次版本号即代表不兼容变更。**

## [未发布]

### 计划中

- 按需只扫描选中的分类（现在是全盘扫一遍）
- 扫描结果导出为报告文件
- 界面文案 i18n（目前硬编码中文）

---

## [0.1.0] — 2026-09-28

首个公开版本。Windows 11 / 24 盘实测。

### 新增 · 扫描能力

| 分类 | 判据 | 本机实测 |
|---|---|---|
| 已安装软件的安装包 | 剥掉版本/平台/角色后缀得产品名，再用**进程名 + 安装目录 + 卸载注册表**三重证据确认「已装」 | 6 项 / 1.51 GB |
| 传统垃圾文件 | 缩略图、跳转列表、浏览器缓存、着色器缓存、崩溃转储、Windows 更新缓存 | 5 项 / 51.6 MB |
| 过期临时文件 | 超过 N 天未动；目录里有 exe 在跑则标为需确认 | 0 项 |
| GitHub 残留 | gh CLI / GitHub Desktop / Copilot 缓存；无远程的本地 clone | 0 项 |
| AI Agent / Skill 缓存 | 不在 `opencode.jsonc` 的 `plugin` 列表里的包；`X` 与 `X@latest` 并存时的旧版本 | 1 项 / 79.6 MB |
| 更新器残留 | `*@*-updater\pending\*`、`*\updates\executors\*` | 1 项 / 87.2 MB |
| 构建产物 / 开发垃圾 | `*.spec` 同级的 `build/`；`__pycache__`、`.pytest_cache`、`.ruff_cache` 等 | 6 项 / 248 MB |
| Python 环境与缓存 | `.venv`（需有 `pyvenv.cfg`）、pip 缓存、配置里追加的任何目录 | 5 项 / 182 MB |
| 注册表 | 卸载命令指向不存在 exe 的卸载项与启动项；可安全重置的 MRU 键 | 1 项 / 466 项 |
| 空文件 / 空目录 / 断链 | 0 字节项，自动跳过 `.gitkeep` / `*.lock` / `desktop.ini` / `Thumbs.db` | 1 项 / 4369 项 |

合计 **2.22 GB** 可回收。

### 新增 · 界面

- 原生 PySide6 窗口，无浏览器、无 WebView、无控制台
- 6 套色板主题（Studio Dark/Light、Ink、Paper、Rosé Pine、Tokyo Night），实时切换并写回配置
- 分类默认全部折叠，一屏看完所有分类与大小；「全部展开 / 全部折叠」
- 注册表与空文件类按**条目数**显示，不按字节骗人
- 打开即自动扫描，进度条走不确定模式 + 阶段文字节流
- 启动扫描耗时从 42.5 s 降到 5.9 s（`excluded()` 缓存 resolve 结果）

### 安全

- 文件删除走 `SHFileOperationW` + `FOF_ALLOWUNDO`，**进回收站可还原**
- 注册表**先写 `.reg` 备份，导出成功才删；导出失败拒绝删除**
- `.reg` 由本工具自行生成，不调 `reg.exe export`（后者在含空格路径下报「无效语法」）
- 断链用 `os.rmdir`/`os.unlink` 只删链接本身
- 扫描前检查文件/目录是否被进程占用，被占用则跳过
- 需确认项不自动勾选，必须手动勾
- 有 remote 的 Git 仓库绝不进可删列表
- 失效程序的判据只认「卸载命令里的 exe 不存在」

### 已知限制

- 删 `HKLM` 下的键需要管理员权限，普通用户会看到「权限不足」（预期行为）
- 注册表只扫 `HKCU` 的 10 个 MRU 键和三个 `Uninstall`/`Run` 分支。刻意不遍历 `HKCR\CLSID`，那里的误删代价是系统装不上程序
- 空文件/空目录是全量遍历，占了约一半扫描时间
- 只读清单里的 Git 仓库不提供一键删除
- 界面文案硬编码中文

### 决策记录

这几条是踩过坑之后定下来的，改动前请先读：

**「失效程序」只看卸载命令的 exe。**
早期版本额外要求 `InstallLocation` 目录也不存在，结果误报了一大片 —— 微信和 Visual Studio Installer 的 `Uninstall.exe` 明明还在，只是 `InstallLocation` 指向了旧路径。删掉活程序的卸载项 = 以后再也卸不掉它。

**Git 仓库默认只读。**
没有任何信号能可靠区分「临时 clone」和「你的在用项目」。只有同时满足无远程仓库 + 超过 60 天未动 + 无未提交改动三条，才进可删列表。

**不扫 Windows Temp 的新文件。**
本机 Temp 有 770 MB，但全部在 7 天内，其中 121 MB 是正在运行的 PyInstaller 解包目录。按天龄过滤在这里收益≈0 还会误删。

**不碰 Prefetch。**
删了会让下次启动变慢，负收益。

**勾选态用 QPalette 上色，不用 setObjectName + unpolish/polish。**
后者会让 Qt 重新解析整份样式表，自动全选 27 行就是 27 次全量重算连续触发，主线程卡死，表现为整窗闪动。

**「强调色上的文字」按 WCAG 算，不手抄。**
复现了设计稿在 4 套主题上的选择；Ink 偏离设计稿 —— 白字 3.3:1，13px 粗体按 AA 要 4.5:1，改用底色字 5.3:1。

**配置回写逐行替换，不用 yaml.dump 全量重写。**
后者会冲掉用户写的注释。

**`build.bat` 纯 ASCII。**
cmd 按 OEM 代码页读 `.bat`，中文和 `&` 组合会被误解析成不存在的命令。

### 测试

35 项自检，`python test_app.py`。重点覆盖：

- 离屏构建界面、6 套主题逐一切换
- 注册表完整往返：建键 → 备份 → 删除 → `reg import` 还原 → 校验数据一致
- 深层子树的注册表键必须删干净
- 「卸载命令有效 + InstallLocation 失效」不得被误判
- 批量空文件真删，且 `.gitkeep` 不被误删
- 有 remote 的仓库不进可删列表
- 主色与设计稿逐字一致、7 组对比度达 WCAG AA
- 勾选不上色走 `unpolish`/`polish`
- 分类默认折叠、展开按钮真实点击
- 改配置保留注释
- 内部协议串（`REG:` / `BULK:`）不外泄到界面
- 版本号与 CHANGELOG / README 同步、20 个开源必需文件齐全、无占位符残留
- 仓库链接用户名一致、所有本地图片引用有效

[未发布]: https://github.com/matou1118/DevCleaner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/matou1118/DevCleaner/releases/tag/v0.1.0
