from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import ctypes
import winreg
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

API_URL = "https://htserver.wdg12.work/api/download-resources"
VC_REDIST_X64_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
DOWNLOAD_THREADS = 5

LICENSE_TEXT = """WDG Snap Hutao 安装许可确认

在继续安装前，请确认你理解并同意以下事项和许可证：

1. 原开发者已不参与维护，请勿打扰原作者
2. 如果你选择安装MSIX包，程序需要安装证书才能安装软件

MIT License

Copyright (c) 2022 DGP Studio

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


@dataclass(frozen=True)
class PackageInfo:
    version: str
    package_type: str
    download_url: str
    features: str
    file_size: str
    created_at: str
    is_active: bool
    is_test: bool

    @classmethod
    def from_dict(cls, item: dict) -> "PackageInfo":
        return cls(
            version=str(item.get("version", "")),
            package_type=str(item.get("package_type", "")).lower(),
            download_url=str(item.get("download_url", "")),
            features=str(item.get("features", "")),
            file_size=str(item.get("file_size", "")),
            created_at=str(item.get("created_at", "")),
            is_active=bool(item.get("is_active", False)),
            is_test=bool(item.get("is_test", False)),
        )

    @property
    def label(self) -> str:
        suffix = " 测试版" if self.is_test else ""
        size = f" / {self.file_size}" if self.file_size else ""
        return f"{self.version} - {self.package_type.upper()}{suffix}{size}"


@dataclass(frozen=True)
class InstalledInfo:
    package_type: str
    version: str
    install_path: str = ""


class UiBus:
    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()

    def put(self, event: str, payload: object = None) -> None:
        self._queue.put((event, payload))

    def drain(self) -> list[tuple[str, object]]:
        events: list[tuple[str, object]] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                return events


class FourThreadDownloader:
    def __init__(self, url: str, target: Path, bus: UiBus) -> None:
        self.url = url
        self.target = target
        self.bus = bus
        self.downloaded = 0
        self.total = 0
        self._lock = threading.Lock()

    def download(self) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        total = self._get_content_length()
        if total <= 0:
            raise RuntimeError("无法获取安装包大小，不能进行 5 线程分片下载。")

        self.total = total
        part_files = [self.target.with_suffix(self.target.suffix + f".part{i}") for i in range(DOWNLOAD_THREADS)]
        ranges = self._build_ranges(total)
        self.bus.put("log", f"开始 5 线程下载，文件大小 {self._format_size(total)}")

        errors: list[BaseException] = []
        threads = []
        for index, byte_range in enumerate(ranges):
            thread = threading.Thread(
                target=self._download_part,
                args=(index, byte_range, part_files[index], errors),
                daemon=True,
            )
            threads.append(thread)
            thread.start()

        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=0.1)
            self._send_progress()

        if errors:
            raise RuntimeError(str(errors[0]))

        self._send_progress()
        with self.target.open("wb") as output:
            for part_file in part_files:
                with part_file.open("rb") as part:
                    shutil.copyfileobj(part, output)
                part_file.unlink(missing_ok=True)

        actual_size = self.target.stat().st_size
        if actual_size != total:
            raise RuntimeError(f"下载文件大小不匹配：期望 {total} 字节，实际 {actual_size} 字节。")
        self.bus.put("progress", 1.0)
        self.bus.put("log", "下载完成")

    @staticmethod
    def download_stream(url: str, target: Path, bus: UiBus) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "SnapHutaoCustomTkInstaller/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            bus.put("log", "开始兼容模式下载")
            with target.open("wb") as output:
                while True:
                    block = response.read(1024 * 256)
                    if not block:
                        break
                    output.write(block)
                    downloaded += len(block)
                    if total > 0:
                        bus.put("progress", min(1.0, downloaded / total))
                        bus.put("status", f"已下载 {FourThreadDownloader._format_size(downloaded)} / {FourThreadDownloader._format_size(total)}")
                    else:
                        bus.put("status", f"已下载 {FourThreadDownloader._format_size(downloaded)}")
        if target.stat().st_size <= 0:
            raise RuntimeError("下载文件为空。")
        bus.put("progress", 1.0)
        bus.put("log", "下载完成")

    def _get_content_length(self) -> int:
        request = urllib.request.Request(
            self.url,
            method="HEAD",
            headers={"User-Agent": "SnapHutaoCustomTkInstaller/1.0"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            length = response.headers.get("Content-Length")
            if not length:
                return 0
            return int(length)

    def _build_ranges(self, total: int) -> list[tuple[int, int]]:
        chunk = total // DOWNLOAD_THREADS
        ranges = []
        start = 0
        for index in range(DOWNLOAD_THREADS):
            end = total - 1 if index == DOWNLOAD_THREADS - 1 else start + chunk - 1
            ranges.append((start, end))
            start = end + 1
        return ranges

    def _download_part(
        self,
        index: int,
        byte_range: tuple[int, int],
        part_file: Path,
        errors: list[BaseException],
    ) -> None:
        start, end = byte_range
        request = urllib.request.Request(
            self.url,
            headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "SnapHutaoCustomTkInstaller/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 206:
                    raise RuntimeError("服务器未按 Range 请求返回分片内容。")
                with part_file.open("wb") as output:
                    while True:
                        block = response.read(1024 * 256)
                        if not block:
                            break
                        output.write(block)
                        with self._lock:
                            self.downloaded += len(block)
            self.bus.put("log", f"分片 {index + 1}/{DOWNLOAD_THREADS} 下载完成")
        except BaseException as exc:
            errors.append(exc)

    def _send_progress(self) -> None:
        if self.total > 0:
            self.bus.put("progress", min(1.0, self.downloaded / self.total))
            self.bus.put("status", f"已下载 {self._format_size(self.downloaded)} / {self._format_size(self.total)}")

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"


class SnapHutaoInstaller(ctk.CTk):
    # 字体全部要求Microsoft YaHei，否则会成宋体
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("WDG Snap Hutao 安装器")
        self.geometry("980x680")
        self.minsize(900, 620)

        self.bus = UiBus()
        self.packages: list[PackageInfo] = []
        self.installed_msi: InstalledInfo | None = None
        self.installed_msix: InstalledInfo | None = None
        self.selected_package: PackageInfo | None = None
        self.install_dir = ctk.StringVar(value=str(Path.home() / "AppData" / "Local" / "Snap.Hutao"))
        self.version_var = ctk.StringVar()
        self.package_type_var = ctk.StringVar(value="msix")
        self.license_accepted = ctk.BooleanVar(value=False)
        self.progress_var = ctk.DoubleVar(value=0.0)

        self._build_ui()
        self._set_busy(True, "正在获取安装包列表...")
        self._start_worker(self._load_packages)
        self.after(80, self._poll_bus)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="WDG Snap Hutao 安装器", font=ctk.CTkFont("Microsoft YaHei",size=24, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(20, 4)
        )
        ctk.CTkLabel(header, text="选择版本、确认许可，然后下载并安装 WDG Snap Hutao。", text_color=("gray35", "gray75"),font=("Microsoft YaHei", 12)).grid(
            row=1, column=0, sticky="w", padx=24, pady=(0, 18)
        )

        body = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=20, pady=16)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body, width=280)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
        left.grid_propagate(False)
        for index, text in enumerate(("1. 选择版本", "2. 选择包类型", "3. 同意许可证", "4. 下载", "5. 安装")):
            ctk.CTkLabel(left, text=text, anchor="w", font=ctk.CTkFont("Microsoft YaHei",size=15, weight="bold")).grid(
                row=index, column=0, sticky="ew", padx=20, pady=(18 if index == 0 else 10, 0)
            )
        self.status_label = ctk.CTkLabel(left, text="准备中", wraplength=230, justify="left", text_color=("gray30", "gray75"),font=("Microsoft YaHei", 13))
        self.status_label.grid(row=6, column=0, sticky="ew", padx=20, pady=(28, 8))
        self.progress = ctk.CTkProgressBar(left, variable=self.progress_var)
        self.progress.grid(row=7, column=0, sticky="ew", padx=20, pady=(0, 16))
        self.progress.set(0)

        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        controls = ctk.CTkFrame(right, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
        controls.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(controls, text="版本", font=("Microsoft YaHei", 12)).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=8)
        self.version_menu = ctk.CTkComboBox(controls, variable=self.version_var, values=[], command=self._on_version_changed)
        self.version_menu.grid(row=0, column=1, sticky="ew", pady=8)

        ctk.CTkLabel(controls, text="包类型", font=("Microsoft YaHei", 12)).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=8)
        self.package_selector = ctk.CTkSegmentedButton(
            controls,
            values=["msix", "msi"],
            variable=self.package_type_var,
            command=self._on_package_type_changed,
        )
        self.package_selector.grid(row=1, column=1, sticky="w", pady=8)

        ctk.CTkLabel(controls, text="MSI 安装路径", font=("Microsoft YaHei", 12)).grid(row=2, column=0, sticky="w", padx=(0, 12), pady=8)
        path_row = ctk.CTkFrame(controls, fg_color="transparent")
        path_row.grid(row=2, column=1, sticky="ew", pady=8)
        path_row.grid_columnconfigure(0, weight=1)
        self.path_entry = ctk.CTkEntry(path_row, textvariable=self.install_dir)
        self.path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.path_button = ctk.CTkButton(path_row, text="浏览", font=("Microsoft YaHei", 12.5), width=84, command=self._choose_install_dir)
        self.path_button.grid(row=0, column=1)

        self.package_summary = ctk.CTkTextbox(right, height=110, wrap="word", font=ctk.CTkFont("Microsoft YaHei", size=12))
        self.package_summary.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 10))
        self.package_summary.configure(state="disabled")

        license_row = ctk.CTkFrame(right, fg_color="transparent")
        license_row.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        license_row.grid_columnconfigure(0, weight=1)
        self.accept_checkbox = ctk.CTkCheckBox(
            license_row,
            text="我已阅读并同意许可证及安装操作说明",
            variable=self.license_accepted,
            command=self._refresh_actions,
            font=ctk.CTkFont("Microsoft YaHei", size=13),
        )
        self.accept_checkbox.grid(row=0, column=0, sticky="w")

        text_area = ctk.CTkFrame(right, fg_color="transparent")
        text_area.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 12))
        text_area.grid_columnconfigure(0, weight=1)
        text_area.grid_rowconfigure(0, weight=1)
        self.license_box = ctk.CTkTextbox(text_area, wrap="word", font=ctk.CTkFont("Microsoft YaHei", size=12))
        self.license_box.grid(row=0, column=0, sticky="nsew")
        self.license_box.insert("1.0", LICENSE_TEXT)
        self.license_box.configure(state="disabled")

        bottom = ctk.CTkFrame(right, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))
        bottom.grid_columnconfigure(0, weight=1)
        self.log_box = ctk.CTkTextbox(bottom, height=96, wrap="word", font=ctk.CTkFont("Microsoft YaHei", size=12))
        self.log_box.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.log_box.configure(state="disabled")
        buttons = ctk.CTkFrame(bottom, fg_color="transparent")
        buttons.grid(row=0, column=1, sticky="n")
        self.refresh_button = ctk.CTkButton(buttons, text="刷新列表", font=("Microsoft YaHei", 12.5), command=self._refresh_packages, width=120)
        self.refresh_button.grid(row=0, column=0, pady=(0, 10))
        self.install_button = ctk.CTkButton(buttons, text="下载并安装", font=("Microsoft YaHei", 12.5), command=self._download_and_install, width=120)
        self.install_button.grid(row=1, column=0)

    def _load_packages(self) -> None:
        try:
            request = urllib.request.Request(API_URL, headers={"User-Agent": "SnapHutaoCustomTkInstaller/1.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != 0:
                raise RuntimeError(f"接口返回异常：{payload!r}")
            packages = [
                PackageInfo.from_dict(item)
                for item in payload.get("data", [])
                if item.get("is_active") and item.get("package_type") in {"msix", "msi"}
            ]
            packages.sort(key=lambda item: (self._version_key(item.version), item.package_type), reverse=True)
            if not packages:
                raise RuntimeError("没有可用安装包。")
            self.bus.put("packages", packages)
            self.bus.put("installed", self._detect_installed_apps())
        except BaseException as exc:
            self.bus.put("error", f"获取安装包列表失败：{exc}")

    def _download_and_install(self) -> None:
        if not self.selected_package:
            messagebox.showwarning("缺少选择", "请先选择版本和包类型。")
            return
        if not self.license_accepted.get():
            messagebox.showwarning("需要同意许可证", "请先阅读并同意许可证。")
            return
        if not self._confirm_install_action(self.selected_package):
            return
        if self.selected_package.package_type == "msix" and not self._is_running_as_admin():
            should_relaunch = messagebox.askyesno(
                "需要管理员权限",
                "MSIX 证书需要安装到本地计算机证书存储区。请以管理员身份重新启动安装器后继续。\n\n是否现在请求管理员权限并重新启动？",
            )
            if should_relaunch:
                try:
                    self._relaunch_as_admin()
                    self.destroy()
                except BaseException as exc:
                    messagebox.showerror("提权失败", str(exc))
            return
        self._set_busy(True, "准备下载...")
        self.progress_var.set(0)
        self._start_worker(lambda: self._install_package(self.selected_package))

    def _install_package(self, package: PackageInfo) -> None:
        work_dir = Path(tempfile.mkdtemp(prefix="snap_hutao_installer_"))
        try:
            file_name = Path(urllib.parse.urlparse(package.download_url).path).name
            download_path = work_dir / file_name
            downloader = FourThreadDownloader(package.download_url, download_path, self.bus)
            downloader.download()
            if package.package_type == "msix":
                self._install_msix_zip(download_path, work_dir)
            elif package.package_type == "msi":
                self._install_msi(download_path)
            else:
                raise RuntimeError(f"不支持的包类型：{package.package_type}")
            self.bus.put("done", "安装流程已完成。")
        except BaseException as exc:
            self.bus.put("error", f"安装失败：{exc}")
        finally:
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except BaseException:
                pass

    def _install_msix_zip(self, zip_path: Path, work_dir: Path) -> None:
        extract_dir = work_dir / "msix"
        self.bus.put("status", "正在解压 MSIX 安装包...")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)

        msix_files = list(extract_dir.rglob("*.msix"))
        cert_files = list(extract_dir.rglob("*.cer"))
        if not msix_files:
            raise RuntimeError("压缩包中没有找到 .msix 文件。")
        if not cert_files:
            raise RuntimeError("压缩包中没有找到 .cer 证书文件。")

        cert_path = cert_files[0]
        msix_path = msix_files[0]
        self.bus.put("log", f"证书：{cert_path.name}")
        self.bus.put("log", f"MSIX：{msix_path.name}")

        self._install_msix_certificate(cert_path)

        self.bus.put("status", "正在安装 MSIX...")
        self._run_powershell(["Add-AppxPackage", "-Path", str(msix_path), "-ForceApplicationShutdown"])

    def _install_msix_certificate(self, cert_path: Path) -> None:
        # 导入这两个解决99%的问题
        stores = [
            ("本地计算机的受信任根证书颁发机构", "Cert:\\LocalMachine\\Root"),
            ("本地计算机的受信任的人", "Cert:\\LocalMachine\\TrustedPeople"),
        ]
        for display_name, store_location in stores:
            self.bus.put("status", f"正在安装证书到{display_name}...")
            self.bus.put("log", f"导入证书到 {store_location}")
            self._run_powershell(
                [
                    "Import-Certificate",
                    "-FilePath",
                    str(cert_path),
                    "-CertStoreLocation",
                    store_location,
                ]
            )

    def _install_msi(self, msi_path: Path) -> None:
        install_path = Path(self.install_dir.get()).expanduser().resolve()
        install_folder_property = self._format_msi_directory_property(install_path)
        install_path.mkdir(parents=True, exist_ok=True)
        self.bus.put("status", "正在运行 MSI 安装程序...")
        self.bus.put("log", f"安装路径：{install_path}")
        self.bus.put("log", f"MSI 安装目录属性 INSTALLFOLDER={install_folder_property}")
        args = [
            "msiexec.exe",
            "/i",
            str(msi_path),
            "/passive",
            "/norestart",
            f"INSTALLFOLDER={install_folder_property}",
            f"INSTALLDIR={install_folder_property}",
            f"TARGETDIR={install_folder_property}",
            f"APPLICATIONFOLDER={install_folder_property}",
        ]
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            **self._hidden_subprocess_options(),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"msiexec 返回码 {completed.returncode}"
            raise RuntimeError(detail)
        self._remember_msi_install_path(install_path)

    @staticmethod
    def _format_msi_directory_property(path: Path) -> str:
        value = str(path)
        if not value.endswith(("\\", "/")):
            value += "\\"
        return value

    def _check_vc_redist_after_install(self) -> None:
        if self._is_vc_redist_x64_installed():
            self._append_log("已检测到 Microsoft Visual C++ Redistributable 2015-2022 x64")
            return
        should_install = messagebox.askyesno(
            "缺少 VC++ 运行库",
            "未检测到 Microsoft Visual C++ Redistributable 2015-2022 x64。\n\n"
            "Snap Hutao 可能需要该运行库才能正常启动。是否现在下载并安装？",
        )
        if not should_install:
            self._append_log("用户跳过 VC++ 运行库安装")
            return
        self._set_busy(True, "正在准备安装 VC++ 运行库...")
        self.progress_var.set(0)
        self._start_worker(self._download_and_install_vc_redist)

    def _download_and_install_vc_redist(self) -> None:
        global DOWNLOAD_THREADS
        DOWNLOAD_THREADS = 2 # 下载vc最大两个线程，否则出问题
        # 这东西下载经常出问题，可能是因为重定向的问题
        work_dir = Path(tempfile.mkdtemp(prefix="snap_hutao_vc_redist_"))
        try:
            installer_path = work_dir / "vc_redist.x64.exe"
            try:
                downloader = FourThreadDownloader(VC_REDIST_X64_URL, installer_path, self.bus)
                downloader.download()
            except BaseException as exc:
                self.bus.put("log", f"VC++ 2 线程下载失败，切换兼容模式：{exc}")
                try:
                    FourThreadDownloader.download_stream(VC_REDIST_X64_URL, installer_path, self.bus)
                except BaseException as stream_exc:
                    self.bus.put("log", f"VC++ 兼容模式下载失败，切换 PowerShell 下载：{stream_exc}")
                    try:
                        self._download_file_with_powershell(VC_REDIST_X64_URL, installer_path)
                    except BaseException as powershell_exc:
                        self.bus.put("log", f"VC++ PowerShell 下载失败，切换 curl 下载：{powershell_exc}")
                        self._download_file_with_curl(VC_REDIST_X64_URL, installer_path)
            self.bus.put("status", "正在安装 VC++ 运行库...")
            completed = subprocess.run(
                [str(installer_path), "/install", "/passive", "/norestart"],
                capture_output=True,
                text=True,
                encoding="mbcs",
                errors="replace",
                **self._hidden_subprocess_options(),
            )
            if completed.returncode not in {0, 1638, 3010}:
                detail = completed.stderr.strip() or completed.stdout.strip() or f"VC++ 安装程序返回码 {completed.returncode}"
                raise RuntimeError(detail)
            if completed.returncode == 3010:
                self.bus.put("vc_done", "VC++ 运行库安装完成，可能需要重启 Windows 后生效。")
            else:
                self.bus.put("vc_done", "VC++ 运行库安装完成。")
        except BaseException as exc:
            self.bus.put("error", f"VC++ 运行库安装失败：{exc}")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _download_file_with_powershell(self, url: str, target: Path) -> None:
        self.bus.put("status", "正在使用 PowerShell 下载 VC++ 运行库...")
        script = (
            "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
            "$ProgressPreference = 'SilentlyContinue'; "
            f"Invoke-WebRequest -Uri {self._quote_ps_arg(url)} -OutFile {self._quote_ps_arg(str(target))} -UseBasicParsing"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            **self._hidden_subprocess_options(),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"PowerShell 下载返回码 {completed.returncode}"
            raise RuntimeError(detail)
        if not target.exists() or target.stat().st_size <= 0:
            raise RuntimeError("PowerShell 下载的文件为空。")
        self.bus.put("progress", 1.0)
        self.bus.put("log", "PowerShell 下载完成")

    def _download_file_with_curl(self, url: str, target: Path) -> None:
        self.bus.put("status", "正在使用 curl 下载 VC++ 运行库...")
        completed = subprocess.run(
            ["curl.exe", "-L", "--fail", "--silent", "--show-error", "--output", str(target), url],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            **self._hidden_subprocess_options(),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"curl 返回码 {completed.returncode}"
            raise RuntimeError(detail)
        if not target.exists() or target.stat().st_size <= 0:
            raise RuntimeError("curl 下载的文件为空。")
        self.bus.put("progress", 1.0)
        self.bus.put("log", "curl 下载完成")

    @staticmethod
    def _is_vc_redist_x64_installed() -> bool:
        registry_paths = [
            r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
            r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        ]
        for registry_path in registry_paths:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
                    installed, _ = winreg.QueryValueEx(key, "Installed")
                    major, _ = winreg.QueryValueEx(key, "Major")
                    version = SnapHutaoInstaller._registry_string(key, "Version")
            except OSError:
                continue
            try:
                installed_value = int(installed)
                major_value = int(major)
            except (TypeError, ValueError):
                continue
            if installed_value != 1:
                continue
            if major_value >= 14:
                return True
            if version and SnapHutaoInstaller._compare_versions(version.lstrip("v"), "14.0") >= 0:
                return True
        return False

    def _confirm_install_action(self, package: PackageInfo) -> bool:
        installed = self._installed_info_for(package.package_type)
        if not installed:
            return True

        comparison = self._compare_versions(package.version, installed.version)
        if package.package_type == "msix" and comparison < 0:
            messagebox.showerror(
                "MSIX 不允许降级",
                f"已安装 MSIX 版本为 {installed.version}，不能安装更低版本 {package.version}。\n\n请选择当前版本或更新版本。",
            )
            return False

        action = self._install_relation_text(package.version, installed.version)
        title = f"确认{action}"
        message = (
            f"已检测到 {package.package_type.upper()} 版本 {installed.version}。\n"
            f"将安装版本 {package.version}，本次操作为{action}。\n\n"
            "用户数据将保留。是否继续？"
        )
        if package.package_type == "msi" and installed.install_path:
            message += f"\n\n将使用之前的安装路径：\n{installed.install_path}"
        return messagebox.askyesno(title, message)

    def _installed_info_for(self, package_type: str) -> InstalledInfo | None:
        if package_type == "msi":
            return self.installed_msi
        if package_type == "msix":
            return self.installed_msix
        return None

    def _install_relation_text(self, target_version: str, installed_version: str) -> str:
        comparison = self._compare_versions(target_version, installed_version)
        if comparison > 0:
            return "更新"
        if comparison < 0:
            return "降级"
        return "重新安装"

    def _detect_installed_apps(self) -> dict[str, InstalledInfo | None]:
        return {
            "msi": self._detect_msi_install(),
            "msix": self._detect_msix_install(),
        }

    def _detect_msi_install(self) -> InstalledInfo | None:
        roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        candidates: list[InstalledInfo] = []
        remembered_install_path = self._read_remembered_msi_install_path()
        shortcut_install_path = self._detect_msi_shortcut_install_path()
        default_install_path = self._detect_default_msi_install_path()
        for root, subkey in roots:
            try:
                with winreg.OpenKey(root, subkey) as uninstall_key:
                    index = 0
                    while True:
                        try:
                            name = winreg.EnumKey(uninstall_key, index)
                            index += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(uninstall_key, name) as app_key:
                                display_name = self._registry_string(app_key, "DisplayName")
                                if not display_name or display_name.lower() not in {"snap.hutao", "snap hutao"}:
                                    continue
                                version = self._registry_string(app_key, "DisplayVersion")
                                install_path = self._registry_string(app_key, "InstallLocation")
                                if not install_path:
                                    install_path = self._path_from_display_icon(self._registry_string(app_key, "DisplayIcon"))
                                if not install_path:
                                    install_path = remembered_install_path
                                if not install_path:
                                    install_path = shortcut_install_path
                                if not install_path:
                                    install_path = default_install_path
                                if version:
                                    candidates.append(InstalledInfo("msi", version, install_path))
                        except OSError:
                            continue
            except OSError:
                continue
        if not candidates:
            return None
        return max(candidates, key=lambda item: self._version_key(item.version))

    @staticmethod
    def _read_remembered_msi_install_path() -> str:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Snap.Hutao.Installer") as key:
                value, _value_type = winreg.QueryValueEx(key, "MSIInstallPath")
        except OSError:
            return ""
        path = str(value).strip()
        return path if path and Path(path).exists() else ""

    @staticmethod
    def _remember_msi_install_path(path: Path) -> None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Snap.Hutao.Installer") as key:
            winreg.SetValueEx(key, "MSIInstallPath", 0, winreg.REG_SZ, str(path))

    def _detect_msi_shortcut_install_path(self) -> str:
        # 尝试查MSI安装位置
        script = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "$shell = New-Object -ComObject WScript.Shell; "
            "$paths = @("
            "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Snap Hutao.lnk'),"
            "(Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Snap Hutao.lnk'),"
            "(Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\\Snap Hutao\\Snap Hutao.lnk'),"
            "(Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs\\Snap Hutao\\Snap Hutao.lnk')"
            "); "
            "$target = foreach ($path in $paths) { "
            "if (-not (Test-Path $path)) { continue }; "
            "$shortcut = $shell.CreateShortcut($path); "
            "if ([IO.Path]::GetFileName($shortcut.TargetPath) -ieq 'Snap.Hutao.exe') { $shortcut.TargetPath; break } "
            "}; "
            "if ($target) { [IO.Path]::GetDirectoryName($target) }"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **self._hidden_subprocess_options(),
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""

    @staticmethod
    def _detect_default_msi_install_path() -> str:
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Snap.Hutao",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Snap.Hutao",
        ]
        for candidate in candidates:
            if (candidate / "Snap.Hutao.exe").exists():
                return str(candidate)
        return ""

    def _detect_msix_install(self) -> InstalledInfo | None:
        script = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "$pkg = Get-AppxPackage -Name '*Snap*Hutao*' -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Name -eq 'Snap.Hutao' -or $_.Name -like '*Snap*Hutao*' -or $_.PackageFullName -like 'Snap.Hutao_*' } | "
            "Sort-Object Version -Descending | Select-Object -First 1; "
            "if ($pkg) { $pkg | Select-Object Name,Version,InstallLocation | ConvertTo-Json -Compress }"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **self._hidden_subprocess_options(),
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        version = str(payload.get("Version") or "")
        if not version:
            return None
        return InstalledInfo("msix", version, str(payload.get("InstallLocation") or ""))

    @staticmethod
    def _registry_string(key, name: str) -> str:
        try:
            value, _value_type = winreg.QueryValueEx(key, name)
        except OSError:
            return ""
        return str(value).strip()

    @staticmethod
    def _path_from_display_icon(display_icon: str) -> str:
        if not display_icon:
            return ""
        value = display_icon.strip().strip('"')
        if value.lower().endswith(".exe"):
            return str(Path(value).parent)
        if ".exe" in value.lower():
            exe_index = value.lower().find(".exe") + 4
            return str(Path(value[:exe_index]).parent)
        return ""

    def _run_powershell(self, command: list[str]) -> None:
        script = " ".join(self._quote_ps_arg(arg) for arg in command)
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            **self._hidden_subprocess_options(),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"PowerShell 返回码 {completed.returncode}"
            raise RuntimeError(detail)
        if completed.stdout.strip():
            self.bus.put("log", completed.stdout.strip())

    def _on_version_changed(self, _value: str | None = None) -> None:
        self._refresh_package_type_options()
        self._select_matching_package()

    def _on_package_type_changed(self, _value: str | None = None) -> None:
        self._select_matching_package()
        self._refresh_actions()

    def _select_matching_package(self) -> None:
        version = self.version_var.get()
        package_type = self.package_type_var.get()
        match = next((item for item in self.packages if item.version == version and item.package_type == package_type), None)
        self.selected_package = match
        self._update_summary()
        self._refresh_actions()

    def _update_summary(self) -> None:
        self.package_summary.configure(state="normal")
        self.package_summary.delete("1.0", "end")
        if self.selected_package:
            package = self.selected_package
            summary = (
                f"版本：{package.version}\n"
                f"类型：{package.package_type.upper()}\n"
                f"大小：{package.file_size or '接口未提供，下载前会自动探测'}\n"
                f"发布日期：{package.created_at or '未知'}\n\n"
                f"{self._installed_status_text(package)}\n\n"
                f"{package.features or '暂无更新说明'}"
            )
            self.package_summary.insert("1.0", summary)
        else:
            self.package_summary.insert("1.0", "当前版本没有所选包类型。")
        self.package_summary.configure(state="disabled")

    def _installed_status_text(self, package: PackageInfo) -> str:
        installed = self._installed_info_for(package.package_type)
        if not installed:
            return f"本机未检测到 {package.package_type.upper()} 安装。"
        relation = self._install_relation_text(package.version, installed.version)
        path = f"\n已安装路径：{installed.install_path}" if installed.install_path else ""
        return f"已检测到 {package.package_type.upper()}：{installed.version}，本次将{relation}，用户数据将保留。{path}"

    def _refresh_actions(self) -> None:
        package_type = self.package_type_var.get()
        msi_state = "normal" if package_type == "msi" else "disabled"
        self.path_entry.configure(state=msi_state)
        self.path_button.configure(state=msi_state)
        can_install = self.selected_package is not None and self.license_accepted.get()
        self.install_button.configure(state="normal" if can_install else "disabled")

    def _refresh_package_type_options(self) -> None:
        version = self.version_var.get()
        available_types = sorted({item.package_type for item in self.packages if item.version == version})
        if not available_types:
            available_types = ["msix", "msi"]
        self.package_selector.configure(values=available_types)
        if self.package_type_var.get() not in available_types:
            self.package_type_var.set(available_types[0])

    def _refresh_packages(self) -> None:
        self._set_busy(True, "正在刷新安装包列表...")
        self._start_worker(self._load_packages)

    def _choose_install_dir(self) -> None:
        directory = filedialog.askdirectory(initialdir=self.install_dir.get() or str(Path.home()))
        if directory:
            self.install_dir.set(directory)

    def _set_installed_apps(self, installed: dict[str, InstalledInfo | None]) -> None:
        self.installed_msi = installed.get("msi")
        self.installed_msix = installed.get("msix")
        if self.installed_msi and self.installed_msi.install_path:
            self.install_dir.set(self.installed_msi.install_path)
            self._append_log(f"检测到 MSI 已安装：{self.installed_msi.version}，路径 {self.installed_msi.install_path}")
        if self.installed_msix:
            self._append_log(f"检测到 MSIX 已安装：{self.installed_msix.version}")
        if not self.installed_msi and not self.installed_msix:
            self._append_log("未检测到已安装的 Snap Hutao")
        self._update_summary()

    def _set_packages(self, packages: list[PackageInfo]) -> None:
        self.packages = packages
        versions: list[str] = []
        for package in packages:
            if package.version not in versions:
                versions.append(package.version)
        self.version_menu.configure(values=versions)
        if versions:
            self.version_var.set(versions[0])
        self._refresh_package_type_options()
        self._select_matching_package()
        self._set_busy(False, f"已加载 {len(packages)} 个安装包。")
        self._append_log("安装包列表已更新")

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status_label.configure(text=status)
        state = "disabled" if busy else "normal"
        self.refresh_button.configure(state=state)
        self.version_menu.configure(state=state)
        self.package_selector.configure(state=state)
        self.accept_checkbox.configure(state=state)
        if busy:
            self.install_button.configure(state="disabled")
        else:
            self._refresh_actions()

    def _append_log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_bus(self) -> None:
        for event, payload in self.bus.drain():
            if event == "packages":
                self._set_packages(payload)  # type: ignore[arg-type]
            elif event == "installed":
                self._set_installed_apps(payload)  # type: ignore[arg-type]
            elif event == "progress":
                self.progress_var.set(float(payload))
            elif event == "status":
                self.status_label.configure(text=str(payload))
            elif event == "log":
                self._append_log(str(payload))
            elif event == "error":
                self._set_busy(False, "发生错误")
                self._append_log(str(payload))
                messagebox.showerror("错误", str(payload))
            elif event == "done":
                self.progress_var.set(1)
                self._set_busy(False, str(payload))
                self._append_log(str(payload))
                messagebox.showinfo("完成", str(payload))
                self._check_vc_redist_after_install()
            elif event == "vc_done":
                self.progress_var.set(1)
                self._set_busy(False, str(payload))
                self._append_log(str(payload))
                messagebox.showinfo("完成", str(payload))
        self.after(80, self._poll_bus)

    def _start_worker(self, target) -> None:
        threading.Thread(target=target, daemon=True).start()

    @staticmethod
    def _hidden_subprocess_options() -> dict:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return {
            "startupinfo": startupinfo,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        }

    @staticmethod
    def _is_running_as_admin() -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except BaseException:
            return False

    @staticmethod
    def _relaunch_as_admin() -> None:
        script = Path(sys.argv[0]).resolve()
        parameters = subprocess.list2cmdline([str(script), *sys.argv[1:]])
        executable = sys.executable
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            str(Path.cwd()),
            1,
        )
        if result <= 32:
            raise RuntimeError(f"无法请求管理员权限，ShellExecuteW 返回值：{result}")

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        parts = []
        for part in version.split("."):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    @classmethod
    def _compare_versions(cls, left: str, right: str) -> int:
        left_parts = list(cls._version_key(left))
        right_parts = list(cls._version_key(right))
        length = max(len(left_parts), len(right_parts))
        left_parts.extend([0] * (length - len(left_parts)))
        right_parts.extend([0] * (length - len(right_parts)))
        if left_parts > right_parts:
            return 1
        if left_parts < right_parts:
            return -1
        return 0

    @staticmethod
    def _quote_ps_arg(value: str) -> str:
        if value.replace("\\", "").replace(":", "").replace(".", "").replace("-", "").isalnum():
            return value
        return "'" + value.replace("'", "''") + "'"


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("此安装器仅支持 Windows。")
    app = SnapHutaoInstaller()
    app.mainloop()
