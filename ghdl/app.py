"""图形界面（中文，tkinter）。

界面分两个标签页：
  - 源码文件：列出仓库所有文件，可下载整仓 ZIP 或选中单个文件
  - Release 版本：列出所有版本及其预编译附件，可勾选下载
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import core

MAX_ROWS = 5000


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GitHub 下载器")
        self.geometry("940x660")
        self.minsize(760, 520)

        self.owner = None
        self.repo = None
        self.branch = None
        self.files = []
        self.files_truncated = False
        self.releases = []

        self.q = queue.Queue()
        self.cancel = None
        self.busy = False
        self._indeterminate = False

        self._build_ui()
        self.after(100, self._poll)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 2))
        top.pack(fill="x")
        ttk.Label(top, text="仓库地址：").pack(side="left")
        self.repo_var = tk.StringVar()
        self.entry = ttk.Entry(top, textvariable=self.repo_var)
        self.entry.pack(side="left", fill="x", expand=True, padx=6)
        self.entry.bind("<Return>", lambda e: self._load())
        self.load_btn = ttk.Button(top, text="加载", command=self._load)
        self.load_btn.pack(side="left")

        ttk.Label(
            self,
            text="支持 owner/repo，或完整链接（例如 https://github.com/psf/requests）",
            foreground="#777",
        ).pack(fill="x", padx=12)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=6)

        self._build_files_tab()
        self._build_releases_tab()

        bottom = ttk.Frame(self, padding=(10, 0, 10, 4))
        bottom.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self.status_var, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        self.cancel_btn = ttk.Button(bottom, text="取消下载", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(0, 10))

    def _build_files_tab(self):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="源码文件")

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.zip_btn = ttk.Button(bar, text="下载整仓 ZIP", command=self._download_zip, state="disabled")
        self.zip_btn.pack(side="left")
        self.file_btn = ttk.Button(
            bar, text="下载选中文件", command=self._download_selected_files, state="disabled"
        )
        self.file_btn.pack(side="left", padx=6)
        ttk.Label(bar, text="过滤：").pack(side="left", padx=(10, 2))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._render_files())
        ttk.Entry(bar, textvariable=self.filter_var, width=28).pack(side="left")

        self.files_info_var = tk.StringVar()
        ttk.Label(tab, textvariable=self.files_info_var, foreground="#777").pack(fill="x", pady=(6, 2))

        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True)
        self.file_tree = ttk.Treeview(wrap, columns=("size",), selectmode="extended")
        self.file_tree.heading("#0", text="路径")
        self.file_tree.heading("size", text="大小")
        self.file_tree.column("#0", width=650, anchor="w")
        self.file_tree.column("size", width=110, anchor="e", stretch=False)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=vsb.set)
        self.file_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.file_tree.bind("<Double-1>", lambda e: self._download_selected_files())

    def _build_releases_tab(self):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Release 版本")

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.rel_btn = ttk.Button(
            bar, text="下载选中项", command=self._download_selected_releases, state="disabled"
        )
        self.rel_btn.pack(side="left")
        ttk.Button(bar, text="展开全部", command=lambda: self._toggle_all(True)).pack(side="left", padx=6)
        ttk.Button(bar, text="折叠全部", command=lambda: self._toggle_all(False)).pack(side="left")

        self.rel_info_var = tk.StringVar()
        ttk.Label(tab, textvariable=self.rel_info_var, foreground="#777").pack(fill="x", pady=(6, 2))

        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True)
        self.rel_tree = ttk.Treeview(wrap, columns=("size", "dl"), selectmode="extended")
        self.rel_tree.heading("#0", text="版本 / 资源")
        self.rel_tree.heading("size", text="大小")
        self.rel_tree.heading("dl", text="下载次数")
        self.rel_tree.column("#0", width=470, anchor="w")
        self.rel_tree.column("size", width=120, anchor="e", stretch=False)
        self.rel_tree.column("dl", width=90, anchor="e", stretch=False)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.rel_tree.yview)
        self.rel_tree.configure(yscrollcommand=vsb.set)
        self.rel_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ------------------------------------------------------------------ 加载
    def _load(self):
        if self.busy:
            return
        try:
            owner, repo = core.parse_repo(self.repo_var.get())
        except core.GhError as err:
            messagebox.showwarning("提示", str(err))
            return

        self.owner, self.repo = owner, repo
        self.branch = None
        self.files = []
        self.files_truncated = False
        self.releases = []
        self.filter_var.set("")
        self._render_files()
        self._render_releases()
        self._set_busy(True)
        self.status_var.set(f"正在获取 {owner}/{repo} 的信息…")
        self._run(self._fetch_all, owner, repo)

    def _fetch_all(self, owner, repo):
        self.q.put(("status", "正在获取文件列表…"))
        files, truncated, ref = core.get_tree(owner, repo)
        self.q.put(("files", files, truncated, ref))

        self.q.put(("status", "正在获取 Release 列表…"))
        releases = core.list_releases(owner, repo)
        self.q.put(("releases", releases))

        self.q.put(("finished", "加载完成"))

    # ------------------------------------------------------------------ 渲染
    def _render_files(self):
        self.file_tree.delete(*self.file_tree.get_children())
        if not self.owner:
            self.files_info_var.set("")
            return
        keyword = self.filter_var.get().strip().lower()
        shown = [f for f in self.files if keyword in f["path"].lower()] if keyword else list(self.files)
        rows = shown[:MAX_ROWS]
        for item in rows:
            self.file_tree.insert(
                "", "end", iid="file:" + item["path"],
                text=item["path"], values=(core.human_size(item["size"]),),
            )
        info = f"分支：{self.branch}　共 {len(self.files)} 个文件"
        if self.files_truncated:
            info += "　（列表被 GitHub 截断，建议直接下载整仓 ZIP）"
        if len(shown) > len(rows):
            info += f"　过滤结果 {len(shown)} 项，仅显示前 {MAX_ROWS} 项"
        self.files_info_var.set(info)

    def _render_releases(self):
        self.rel_tree.delete(*self.rel_tree.get_children())
        if not self.owner:
            self.rel_info_var.set("")
            return
        if not self.releases:
            self.rel_info_var.set("没有找到 Release（该仓库可能未发布版本）。")
            return
        asset_count = 0
        for ri, rel in enumerate(self.releases):
            title = rel["tag"]
            if rel["prerelease"]:
                title += "（预发布）"
            if rel["published"]:
                title += f"　{rel['published']}"
            node = self.rel_tree.insert("", "end", iid=f"rel:{ri}", text=title, values=("", ""))
            self.rel_tree.insert(node, "end", iid=f"src:{ri}", text="源代码 (zip)", values=("", ""))
            self.rel_tree.insert(node, "end", iid=f"tar:{ri}", text="源代码 (tar.gz)", values=("", ""))
            for ai, asset in enumerate(rel["assets"]):
                asset_count += 1
                self.rel_tree.insert(
                    node, "end", iid=f"asset:{ri}:{ai}", text=asset["name"],
                    values=(core.human_size(asset["size"]), asset["downloads"]),
                )
        self.rel_info_var.set(
            f"共 {len(self.releases)} 个版本，{asset_count} 个附件（展开版本可勾选具体文件）"
        )

    def _toggle_all(self, open_state):
        for iid in self.rel_tree.get_children():
            self.rel_tree.item(iid, open=open_state)

    # ------------------------------------------------------------------ 下载
    def _download_zip(self):
        if self.busy or not self.owner:
            return
        dest_dir = filedialog.askdirectory(title="选择保存目录")
        if not dest_dir:
            return
        name = core.safe_name(f"{self.repo}-{self.branch or 'source'}.zip")
        url = core.source_zip_url(self.owner, self.repo, None)
        self._start_downloads([(url, name, None)], dest_dir)

    def _download_selected_files(self):
        if self.busy or not self.owner:
            return
        paths = [iid[len("file:"):] for iid in self.file_tree.selection() if iid.startswith("file:")]
        if not paths:
            messagebox.showinfo("提示", "请先在列表中选择文件。")
            return
        dest_dir = filedialog.askdirectory(title="选择保存目录")
        if not dest_dir:
            return
        jobs = [
            (
                core.raw_file_url(self.owner, self.repo, self.branch, path),
                core.safe_name(os.path.basename(path)),
                None,
            )
            for path in paths
        ]
        self._start_downloads(jobs, dest_dir)

    def _download_selected_releases(self):
        if self.busy or not self.owner:
            return
        selection = self.rel_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要下载的版本或附件。")
            return

        jobs = []
        for iid in selection:
            kind = iid.split(":", 1)[0]
            if kind == "asset":
                _, ri, ai = iid.split(":")
                asset = self.releases[int(ri)]["assets"][int(ai)]
                jobs.append((asset["url"], asset["name"], {"Accept": "application/octet-stream"}))
            elif kind in ("src", "tar"):
                rel = self.releases[int(iid.split(":")[1])]
                ext = "zip" if kind == "src" else "tar.gz"
                url = core.source_zip_url(self.owner, self.repo, f"refs/tags/{rel['tag']}")
                jobs.append((url, f"{self.repo}-{rel['tag']}.{ext}", None))
            elif kind == "rel":
                rel = self.releases[int(iid.split(":")[1])]
                for asset in rel["assets"]:
                    jobs.append((asset["url"], asset["name"], {"Accept": "application/octet-stream"}))

        if not jobs:
            messagebox.showinfo("提示", "所选项目没有可下载的内容。")
            return
        dest_dir = filedialog.askdirectory(title="选择保存目录")
        if not dest_dir:
            return
        self._start_downloads(jobs, dest_dir)

    def _start_downloads(self, jobs, dest_dir):
        self.cancel = core.CancelToken()
        self._set_busy(True)
        self.cancel_btn.config(state="normal")
        self.progress.config(mode="determinate", maximum=100, value=0)
        self.status_var.set(f"准备下载 {len(jobs)} 个文件…")
        self._run(self._do_downloads, jobs, dest_dir)

    def _do_downloads(self, jobs, dest_dir):
        total = len(jobs)
        final = "下载完成"
        for index, (url, name, headers) in enumerate(jobs, 1):
            if self.cancel.cancelled:
                final = "已取消"
                break
            filename = core.safe_name(name)
            dest = core.unique_path(os.path.join(dest_dir, filename))
            self.q.put(("status", f"({index}/{total}) 下载中：{filename}"))

            def on_progress(done, size, _i=index, _n=filename):
                self.q.put(("progress", done, size, f"({_i}/{total}) {_n}"))

            try:
                core.download(url, dest, headers=headers, progress=on_progress, cancel=self.cancel)
            except core.GhError as err:
                if self.cancel.cancelled:
                    final = "已取消"
                    break
                self.q.put(("error", f"{filename} 下载失败：{err}"))
                final = None
                break
        self.q.put(("finished", final))

    def _cancel(self):
        if self.cancel:
            self.cancel.cancel()
            self.status_var.set("正在取消…")

    # ------------------------------------------------------------------ 状态
    def _set_busy(self, busy):
        self.busy = busy
        self._update_buttons()

    def _update_buttons(self):
        ready = not self.busy
        has_repo = bool(self.owner and self.repo)
        self.load_btn.config(state="normal" if ready else "disabled")
        self.zip_btn.config(state="normal" if (ready and has_repo) else "disabled")
        self.file_btn.config(state="normal" if (ready and self.files) else "disabled")
        self.rel_btn.config(state="normal" if (ready and self.releases) else "disabled")

    def _on_progress(self, done, size, label):
        if size:
            if self._indeterminate:
                self.progress.stop()
                self._indeterminate = False
            self.progress.config(mode="determinate", maximum=100)
            self.progress["value"] = min(100, done * 100.0 / size)
            self.status_var.set(f"{label}　{core.human_size(done)} / {core.human_size(size)}")
        else:
            if not self._indeterminate:
                self.progress.config(mode="indeterminate")
                self.progress.start(60)
                self._indeterminate = True
            self.status_var.set(f"{label}　{core.human_size(done)}")

    def _reset_after_task(self, final_status):
        if self._indeterminate:
            self.progress.stop()
            self._indeterminate = False
        if final_status is not None:
            self.progress.config(mode="determinate", maximum=100, value=100)
        self.cancel = None
        self.cancel_btn.config(state="disabled")
        self._set_busy(False)
        if final_status:
            self.status_var.set(final_status)

    # ------------------------------------------------------------------ 事件
    def _run(self, func, *args):
        def worker():
            try:
                func(*args)
            except core.GhError as err:
                self.q.put(("error", str(err)))
                self.q.put(("finished", None))
            except Exception as err:  # noqa: BLE001 - 兜底，避免线程静默退出
                self.q.put(("error", f"发生错误：{err}"))
                self.q.put(("finished", None))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        while True:
            try:
                event = self.q.get_nowait()
            except queue.Empty:
                break
            self._dispatch(event)
        self.after(100, self._poll)

    def _dispatch(self, event):
        kind = event[0]
        if kind == "status":
            self.status_var.set(event[1])
        elif kind == "error":
            self.status_var.set("出错")
            messagebox.showerror("错误", event[1])
        elif kind == "files":
            _, files, truncated, ref = event
            self.files = files
            self.files_truncated = truncated
            self.branch = ref
            self._render_files()
            self._update_buttons()
        elif kind == "releases":
            self.releases = event[1]
            self._render_releases()
            self._update_buttons()
        elif kind == "progress":
            self._on_progress(event[1], event[2], event[3])
        elif kind == "finished":
            self._reset_after_task(event[1])


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
