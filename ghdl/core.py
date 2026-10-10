"""核心逻辑：解析仓库、列出文件、列出 Release、下载。

只用 Python 标准库。所有请求都避开被墙的 github.com：
  - 仓库元数据、Release 列表   -> api.github.com
  - 源码归档 zip              -> codeload.github.com
  - 单个文件                  -> raw.githubusercontent.com
  - Release 附件              -> api.github.com 返回 302 跳转到
                                release-assets.githubusercontent.com

因此本工具不需要任何代理或加速服务。
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.github.com"
CODELOAD_BASE = "https://codeload.github.com"
RAW_BASE = "https://raw.githubusercontent.com"

USER_AGENT = "GitHubDownloader/1.0"
CHUNK = 64 * 1024

_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class GhError(Exception):
    """可以直接展示给用户的错误信息。"""


class CancelToken:
    """下载取消令牌。"""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def parse_repo(text: str):
    """从用户输入中解析出 (owner, repo)。

    支持 "owner/repo"、"https://github.com/owner/repo"、
    "github.com/owner/repo/tree/main/..." 等写法。
    """
    text = (text or "").strip()
    if not text:
        raise GhError("请输入仓库地址，例如 owner/repo 或 GitHub 链接。")

    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^www\.", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^github\.com/", "", text, flags=re.IGNORECASE)
    text = text.split("?", 1)[0].split("#", 1)[0]

    parts = [p for p in text.split("/") if p]
    if len(parts) < 2:
        raise GhError("仓库格式不对，应为 owner/repo 或 GitHub 链接。")

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _NAME_RE.fullmatch(owner) or not _NAME_RE.fullmatch(repo):
        raise GhError("仓库名包含非法字符，请检查输入。")
    return owner, repo


def human_size(n) -> str:
    """把字节数转成易读字符串。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def safe_name(name: str) -> str:
    """清理成 Windows 可用的文件名。"""
    name = os.path.basename(str(name)).strip()
    name = _INVALID_CHARS.sub("_", name)
    return name or "download"


def unique_path(path: str) -> str:
    """若目标已存在，追加 (1)(2)… 避免覆盖。"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{base} ({i}){ext}"
        if not os.path.exists(cand):
            return cand
        i += 1


# --------------------------------------------------------------------------- #
# HTTP 底层
# --------------------------------------------------------------------------- #
def _ssl_context():
    return ssl.create_default_context()


def _open(url: str, headers=None, timeout: int = 30):
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def _friendly_http_error(err) -> GhError:
    code = getattr(err, "code", None)
    headers = getattr(err, "headers", None)
    if code == 404:
        return GhError("未找到（仓库或版本不存在，也可能是私有仓库）。")
    if code == 403:
        remaining = headers.get("X-RateLimit-Remaining") if headers else None
        if remaining == "0":
            return GhError("触发了 GitHub 未登录访问的频率限制（每小时 60 次），请稍后再试。")
        return GhError("访问被拒绝（HTTP 403）。")
    if code == 451:
        return GhError("该仓库因法律原因不可用（HTTP 451）。")
    return GhError(f"请求失败：HTTP {code}。")


def _api_get(path: str, timeout: int = 30):
    url = API_BASE + path
    try:
        with _open(url, headers={"Accept": "application/vnd.github+json"}, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        raise _friendly_http_error(err) from None
    except urllib.error.URLError as err:
        raise GhError(f"网络连接失败：{getattr(err, 'reason', err)}") from None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise GhError("接口返回了无法解析的内容（可能被网络中间件篡改）。") from None


# --------------------------------------------------------------------------- #
# GitHub 数据
# --------------------------------------------------------------------------- #
def get_repo(owner: str, repo: str, timeout: int = 30):
    """获取仓库信息（含默认分支）。"""
    return _api_get(f"/repos/{owner}/{repo}", timeout=timeout)


def get_tree(owner: str, repo: str, ref=None, timeout: int = 60):
    """列出仓库全部文件。

    返回 (files, truncated, ref)。files 为 [{"path", "size"}]，只含文件，
    ref 为实际使用的分支名。
    """
    if not ref:
        ref = get_repo(owner, repo, timeout=timeout).get("default_branch") or "main"
    quoted = urllib.parse.quote(ref, safe="")
    data = _api_get(f"/repos/{owner}/{repo}/git/trees/{quoted}?recursive=1", timeout=timeout)
    files = []
    for item in data.get("tree", []):
        if item.get("type") == "blob":
            files.append({"path": item["path"], "size": item.get("size", 0)})
    files.sort(key=lambda f: f["path"].lower())
    return files, bool(data.get("truncated")), ref


def list_releases(owner: str, repo: str, timeout: int = 60):
    """列出全部 Release（含每个版本的全部附件）。"""
    data = _api_get(f"/repos/{owner}/{repo}/releases?per_page=100", timeout=timeout)
    releases = []
    for item in data:
        assets = []
        for a in item.get("assets", []):
            assets.append(
                {
                    "name": a.get("name", ""),
                    "size": a.get("size", 0),
                    "downloads": a.get("download_count", 0),
                    "url": a.get("url", ""),
                }
            )
        releases.append(
            {
                "tag": item.get("tag_name") or item.get("name") or "",
                "name": item.get("name") or item.get("tag_name") or "",
                "prerelease": bool(item.get("prerelease")),
                "published": (item.get("published_at") or "")[:10],
                "assets": assets,
            }
        )
    return releases


def source_zip_url(owner: str, repo: str, ref=None) -> str:
    """源码 zip 下载地址。ref 为 None 时用默认分支（HEAD）。"""
    fragment = ref or "HEAD"
    return f"{CODELOAD_BASE}/{owner}/{repo}/zip/{fragment}"


def raw_file_url(owner: str, repo: str, ref: str, path: str) -> str:
    """单个文件的原始内容地址。"""
    ref_q = urllib.parse.quote(ref, safe="")
    path_q = urllib.parse.quote(path, safe="/")
    return f"{RAW_BASE}/{owner}/{repo}/{ref_q}/{path_q}"


# --------------------------------------------------------------------------- #
# 下载
# --------------------------------------------------------------------------- #
def download(url: str, dest: str, headers=None, progress=None, cancel=None, timeout: int = 30) -> str:
    """流式下载到 dest，支持断点续传。

    progress(done, total) 会被周期性调用；total 为 0 表示长度未知。
    返回实际写入的路径。
    """
    part = dest + ".part"
    pos = os.path.getsize(part) if os.path.exists(part) else 0

    req_headers = dict(headers or {})
    if pos > 0:
        req_headers["Range"] = f"bytes={pos}-"
    mode = "ab" if pos > 0 else "wb"

    try:
        resp = _open(url, headers=req_headers, timeout=timeout)
    except urllib.error.HTTPError as err:
        if err.code == 416 and pos > 0:
            os.replace(part, dest)
            return dest
        raise _friendly_http_error(err) from None
    except urllib.error.URLError as err:
        raise GhError(f"下载失败：{getattr(err, 'reason', err)}") from None

    with resp:
        if pos > 0 and resp.status != 206:
            pos = 0
            mode = "wb"
        length = resp.headers.get("Content-Length")
        total = pos + int(length) if (length and length.isdigit()) else 0
        done = pos
        if progress is not None:
            progress(done, total)
        with open(part, mode) as fh:
            while True:
                if cancel is not None and cancel.cancelled:
                    raise GhError("已取消。")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)

    os.replace(part, dest)
    return dest
