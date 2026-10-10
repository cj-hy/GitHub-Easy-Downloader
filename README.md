# GitHub 下载器

一个给非程序员用的 GitHub 下载工具：中文界面，无需命令、无需账号、**无需代理**，即可下载公开仓库的源码打包或 Release 中的预编译文件。

## 为什么不用代理

在国内被阻断的只有 `github.com` 这个网页域名，而真正传输文件字节的域名都可以直连。本工具全程只访问下面四个域名：

| 用途 | 域名 |
| --- | --- |
| 仓库信息、文件列表、Release 列表 | `api.github.com` |
| 源码归档 zip | `codeload.github.com` |
| 单个文件 | `raw.githubusercontent.com` |
| Release 附件 | `release-assets.githubusercontent.com` |

因此不需要任何代理、加速服务或 token。

## 功能

- 顶部输入 `owner/repo` 或完整链接（如 `https://github.com/psf/requests`）即可加载
- **源码文件页**：列出仓库全部文件及大小，支持过滤查找；可下载整仓 ZIP，也可勾选单个文件下载
- **Release 版本页**：列出所有版本，展开可看到该版本下的全部预编译附件（名称、大小、下载次数），勾选任意项下载
- 下载带进度显示，支持断点续传

## 使用

1. 到本仓库的 [Releases](../../releases) 页面下载最新的 `GitHubDownloader.exe`
2. 双击运行。免安装，不需要 Python；首次运行 Windows 可能弹出 SmartScreen 提示，点「更多信息」→「仍要运行」即可
3. 在顶部输入仓库地址，点「加载」，等待下方窗口显示
4. 在「源码文件」页下载整仓 ZIP 或选中的文件，在「Release 版本」页下载选中的附件
5. 每次下载会让你选择保存目录

仅支持 Windows 10 / 11 64 位。

## 从源码运行

需要 Python 3.8+（自带 tkinter）：

```bat
python main.py
```

## 从源码构建 exe

需要 PyInstaller。执行 `build.bat` 即可，产物为 `dist\GitHubDownloader.exe`。

`build.bat` 的路径必须按你的情况修改。在 conda 环境下打包时注意两点：

- 打包前把该环境的 `Library\bin` 放到 `PATH` 最前，否则 PyInstaller 会从 base 环境收集到不匹配的 Tcl/Tk DLL，运行时报 `init.tcl` 版本冲突。
- OpenSSL 库 `libssl-3-x64.dll`、`libcrypto-3-x64.dll` 需要用 `--add-binary` 一起打进包，否则运行时报 `_ssl` DLL 加载失败。

## 已知限制

- 只支持**公开仓库**；私有仓库需要登录 token，暂未支持
- **Git LFS** 大文件与**子模块（submodule）** 不会包含在源码包里
- 未登录的接口有每小时 60 次访问限制；加载列表只占几次，文件下载不走接口，不受影响
- 仓库默认分支名含 `/`（少见）时，「下载选中文件」可能失败，改用整仓 ZIP
