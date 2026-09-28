# DevCleaner

Windows 本地清理工具。原生窗口（PySide6），单文件 exe，**离线可用，不依赖浏览器、Node、Java 或任何外部运行时**。

![主界面](docs/screenshot-dark.png)

## 它能干什么

| 分类 | 判据 | 本机实测产出 |
|---|---|---|
| **已安装软件的安装包** | 文件名剥掉版本/平台/角色后缀得到产品名，再用**进程名 + 安装目录 + 卸载注册表**三重证据确认「已装」 | 6 项 / **1.51 GB** |
| **传统垃圾文件** | 缩略图、跳转列表、浏览器缓存、着色器缓存、崩溃转储、Windows 更新缓存… | 5 项 / 51.6 MB |
| **过期临时文件** | 超过 N 天未动的临时项；目录里有 exe 在跑则标为需确认 | 0 项 |
| **GitHub 残留** | gh CLI / GitHub Desktop / Copilot 缓存；**无远程的本地 clone**（无 remote + 长期未动 + 无未提交改动） | 0 项 |
| **AI Agent / Skill 缓存** | 未在 `opencode.jsonc` 的 `plugin` 列表里启用的包；`X` 与 `X@latest` 并存时的旧版本 | 1 项 / 79.6 MB |
| **更新器残留** | `*\@*-updater\pending\*`、`*\updates\executors\*` 等 | 1 项 / 87.2 MB |
| **构建产物 / 开发垃圾** | `*.spec` 同级的 `build/`；`__pycache__`、`.pytest_cache`、`.ruff_cache` 等 | 6 项 / 248 MB |
| **Python 环境与缓存** | `.venv`（有 `pyvenv.cfg` 才算）、pip 缓存、以及你在配置里加的任何目录 | 5 项 / 182 MB |
| **注册表** | 失效的卸载项、指向不存在 exe 的启动项；以及可安全重置的 MRU 键 | 5 项 / 510 项 |
| **空文件 / 空目录 / 断链** | 0 字节项，**自动跳过 `.gitkeep` / `*.lock` / `desktop.ini` / `Thumbs.db` 等** | 1 项 / 4370 项 |

### ⚠️ 三件必须说清楚的事

1. **注册表清理不省空间。** 本机全部注册表垃圾加起来只有 **15 KB**。它的价值是清掉指向已不存在程序的死引用，不是腾空间。所以界面上它按**条目数**显示，不按字节。
2. **空文件/空目录同理。** 这类项体积是 0。它的价值是整洁，不是腾空间。
3. **Git 仓库默认只读，不提供删除。** 没有任何信号能可靠区分「临时 clone」和「你的在用项目」。只有同时满足**无远程仓库 + 超过 60 天未动 + 无未提交改动**三条才会进入可删列表；其余全部进只读清单（附带 remote URL，一眼能看出哪个是临时的）。

## 安全模型

| 类型 | 行为 |
|---|---|
| 普通文件 | 走 `SHFileOperationW` + `FOF_ALLOWUNDO`，**进回收站**，可还原 |
| 断链 | 用 `os.rmdir`/`os.unlink` 只删链接本身（它没有内容） |
| **注册表** | **先写 `.reg` 备份，导出成功才删；导出失败就拒绝删除** |
| 批量项 | 确认弹窗会显示条目数，并逐条列出前 40 项 |
| 需确认项 | 不会自动勾选，必须手动勾 |

注册表备份目录：`%LOCALAPPDATA%\DevCleaner\registry_backups\<时间戳>_<类型>\`
还原：对该目录里的 `.reg` 执行 `reg import "路径"`。

`.reg` 文件是本工具自己生成的（不调 `reg.exe export`）——`reg.exe` 的命令行引号规则在含空格路径下会报「无效语法」，直接生成更可控也更快。测试里有一轮完整的「建键 → 备份 → 删除 → `reg import` 还原 → 校验数据一致」。

## 安全阀

- **不碰 Windows Temp 里的新文件。** 本机 Temp 有 770 MB，但**全部在 7 天内**，其中 121 MB 是正在运行的 PyInstaller 解包目录。按天龄过滤在这里收益≈0 还会误删，所以默认阈值 7 天且跳过被占用的目录。
- **不碰 Prefetch。** 删了会让下次启动变慢，负收益。
- **不扫系统目录。** `C:/Windows`、`C:/Program Files`、`C:/Program Files (x86)` 默认进白名单。
- **有 remote 的 Git 仓库绝不进可删列表**，测试里专门盯这条。

## 安装

下载 `DevCleaner.exe` 双击即可。打开即自动开始扫描，关闭即退出。

需要 Python 3.10+ 才能从源码运行或重新打包。

## 从源码运行 / 打包

```bash
pip install -r requirements.txt

python app.py       # 无界面：跑一次扫描并打印结果（调试用）
python gui.py       # 原生界面
python test_app.py  # 20 项自检，含离屏构建界面 + 注册表备份还原往返
build.bat           # 自检 -> 清理 -> PyInstaller onefile -> 复制 settings.yaml
```

## 配置

`settings.yaml` 放在 exe 同目录（找不到就用包内内置副本），**改完重启程序生效，不用重新打包**。

```yaml
scan_roots:                    # 需要递归遍历的根（.venv / Git / 构建产物）
  - "%USERPROFILE%"

installer_roots: []            # 留空 = 自动从 Windows 已知文件夹取 Downloads + Desktop

exclude_dirs:                  # 完全不进结果
  - "C:/Windows"
exclude_globs:
  - "**/node_modules/**"

min_installer_age_days: 14     # 「未确认已装」的安装包至少要放这么多天
temp_min_age_days: 7
stale_clone_days: 60

installed_aliases:             # 卸载注册表匹配不到时的别名
  OfficeAce: ["OfficeClaw"]

custom_cache:                  # 加任何目录进来就是一条规则，零代码
  - name: "pip 下载缓存"
    path: "%LOCALAPPDATA%/pip/Cache"
    risk: safe
    note: "删了重新下载即可。"

extra_junk: []                 # 追加传统垃圾目录
```

`risk` 取 `safe`（默认勾选）或 `caution`（默认不勾，需二次确认）。

## 主题

内置 6 套：暗夜 / 曜石 / 森林 / 绯 / 深海 / 素白。界面右上角实时切换，不需要重启。

![主题](docs/screenshot-themes.png)

## 加一个扫描器

在 `app.py` 里继承 `Scanner`，实现 `scan()`，然后塞进 `SCANNERS` 列表。界面会自动多出一个折叠分组，不用改 UI 代码。

```python
class MyScanner(Scanner):
    category, icon = "我的分类", "\U0001f9f0"

    def scan(self) -> List[Item]:
        return [mk(self.category, Path("C:/some/cache"), "名称", "safe",
                   note="说明")]
```

`Item.unit` 填 `"count"` 时，界面按**条目数**而非字节显示，且不参与 `min_size_bytes` 过滤。

![注册表](docs/screenshot-registry.png)

## 已知限制

- 需要管理员权限才能删 `HKLM` 下的键（`Run` 分支、系统级卸载项）。普通用户运行会看到「权限不足」，这是预期行为。
- 只读清单里的 Git 仓库不提供「一键删除」，需要你自己判断。
- 注册表扫描固定只看 `HKCU` 的 MRU 键和三个 `Uninstall`/`Run` 分支。刻意不去遍历 `HKCR\CLSID` 之类的地方 —— 那里的误删代价是系统装不上程序。
- 批量空文件项是聚合成一行的（4370 行没法看），清理时会展开成逐条删除。

## License

MIT
