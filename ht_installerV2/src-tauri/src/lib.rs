use reqwest::blocking::Client;
use reqwest::header::{CONTENT_LENGTH, RANGE, USER_AGENT};
use serde::{Deserialize, Serialize};
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter};

const API_URL: &str = "https://htserver.wdg12.work/api/download-resources";
const VC_REDIST_X64_URL: &str = "https://aka.ms/vc14/vc_redist.x64.exe";
const DOWNLOAD_THREADS: usize = 5;
const USER_AGENT_VALUE: &str = "SnapHutaoTauriInstaller/2.0";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PackageInfo {
    version: String,
    package_type: String,
    download_url: String,
    features: String,
    file_size: String,
    created_at: String,
    is_active: bool,
    is_test: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InstalledInfo {
    package_type: String,
    version: String,
    install_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InstalledApps {
    msi: Option<InstalledInfo>,
    msix: Option<InstalledInfo>,
}

#[derive(Debug, Deserialize)]
struct ApiResponse {
    code: i64,
    data: Vec<ApiPackage>,
}

#[derive(Debug, Deserialize)]
struct ApiPackage {
    version: Option<String>,
    package_type: Option<String>,
    download_url: Option<String>,
    features: Option<String>,
    file_size: Option<String>,
    created_at: Option<String>,
    is_active: Option<bool>,
    is_test: Option<bool>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct BootstrapData {
    packages: Vec<PackageInfo>,
    installed: InstalledApps,
    default_install_dir: String,
    is_admin: bool,
    vc_redist_installed: bool,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct InstallEvent {
    kind: String,
    message: String,
    progress: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InstallRequest {
    package: PackageInfo,
    install_dir: String,
}

#[tauri::command]
async fn bootstrap() -> Result<BootstrapData, String> {
    tauri::async_runtime::spawn_blocking(|| {
        Ok(BootstrapData {
            packages: fetch_packages()?,
            installed: detect_installed_apps(),
            default_install_dir: default_install_dir(),
            is_admin: is_running_as_admin(),
            vc_redist_installed: is_vc_redist_x64_installed(),
        })
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn refresh_packages() -> Result<Vec<PackageInfo>, String> {
    tauri::async_runtime::spawn_blocking(fetch_packages)
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn refresh_installed() -> Result<InstalledApps, String> {
    tauri::async_runtime::spawn_blocking(|| Ok(detect_installed_apps()))
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn install_package(app: AppHandle, request: InstallRequest) -> Result<String, String> {
    let worker_app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        install_package_inner(&worker_app, request).map_err(|error| {
            emit(&worker_app, "error", &format!("安装失败：{error}"), 0.0);
            error
        })
    })
    .await
    .map_err(|error| error.to_string())??;

    let message = "安装流程已完成。".to_string();
    emit(&app, "done", &message, 1.0);
    Ok(message)
}

#[tauri::command]
async fn install_vc_redist(app: AppHandle) -> Result<String, String> {
    let worker_app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        install_vc_redist_inner(&worker_app).map_err(|error| {
            emit(&worker_app, "error", &format!("VC++ 运行库安装失败：{error}"), 0.0);
            error
        })
    })
    .await
    .map_err(|error| error.to_string())??;

    let message = "VC++ 运行库安装完成。".to_string();
    emit(&app, "done", &message, 1.0);
    Ok(message)
}

#[tauri::command]
fn relaunch_as_admin() -> Result<(), String> {
    let executable = std::env::current_exe().map_err(|error| error.to_string())?;
    let script = format!(
        "Start-Process -FilePath {} -Verb RunAs",
        quote_ps_arg(&executable.to_string_lossy())
    );
    run_powershell_script(&script).map(|_| ())
}

fn fetch_packages() -> Result<Vec<PackageInfo>, String> {
    let client = Client::builder()
        .timeout(Duration::from_secs(25))
        .build()
        .map_err(|error| error.to_string())?;
    let payload: ApiResponse = client
        .get(API_URL)
        .header(USER_AGENT, USER_AGENT_VALUE)
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| format!("获取安装包列表失败：{error}"))?
        .json()
        .map_err(|error| format!("解析安装包列表失败：{error}"))?;

    if payload.code != 0 {
        return Err(format!("接口返回异常：code={}", payload.code));
    }

    let mut packages: Vec<PackageInfo> = payload
        .data
        .into_iter()
        .filter_map(|item| {
            let package_type = item.package_type.unwrap_or_default().to_lowercase();
            let is_active = item.is_active.unwrap_or(false);
            if !is_active || !matches!(package_type.as_str(), "msix" | "msi") {
                return None;
            }
            Some(PackageInfo {
                version: item.version.unwrap_or_default(),
                package_type,
                download_url: item.download_url.unwrap_or_default(),
                features: item.features.unwrap_or_default(),
                file_size: item.file_size.unwrap_or_default(),
                created_at: item.created_at.unwrap_or_default(),
                is_active,
                is_test: item.is_test.unwrap_or(false),
            })
        })
        .collect();

    packages.sort_by(|left, right| {
        version_key(&right.version)
            .cmp(&version_key(&left.version))
            .then_with(|| right.package_type.cmp(&left.package_type))
    });

    if packages.is_empty() {
        return Err("没有可用安装包。".to_string());
    }

    Ok(packages)
}

fn install_package_inner(app: &AppHandle, request: InstallRequest) -> Result<(), String> {
    if request.package.download_url.trim().is_empty() {
        return Err("安装包下载地址为空。".to_string());
    }
    if request.package.package_type == "msix" && !is_running_as_admin() {
        return Err("MSIX 证书安装需要管理员权限，请以管理员身份重新启动安装器。".to_string());
    }

    let work_dir = make_temp_dir("snap_hutao_installer")?;
    let result = (|| {
        let file_name = request
            .package
            .download_url
            .split('/')
            .last()
            .filter(|value| !value.is_empty())
            .unwrap_or("snap-hutao-package.bin");
        let download_path = work_dir.join(file_name);

        download_with_fallback(app, &request.package.download_url, &download_path, DOWNLOAD_THREADS)?;
        match request.package.package_type.as_str() {
            "msix" => install_msix_zip(app, &download_path, &work_dir),
            "msi" => install_msi(app, &download_path, &request.install_dir),
            other => Err(format!("不支持的包类型：{other}")),
        }
    })();
    let _ = fs::remove_dir_all(&work_dir);
    result
}

fn install_msix_zip(app: &AppHandle, zip_path: &Path, work_dir: &Path) -> Result<(), String> {
    let extract_dir = work_dir.join("msix");
    emit(app, "status", "正在解压 MSIX 安装包...", 1.0);
    fs::create_dir_all(&extract_dir).map_err(|error| error.to_string())?;

    let archive_file = File::open(zip_path).map_err(|error| error.to_string())?;
    let mut archive = zip::ZipArchive::new(archive_file).map_err(|error| error.to_string())?;
    archive
        .extract(&extract_dir)
        .map_err(|error| format!("解压安装包失败：{error}"))?;

    let msix_path = find_file_with_extension(&extract_dir, "msix")
        .ok_or_else(|| "压缩包中没有找到 .msix 文件。".to_string())?;
    let cert_path = find_file_with_extension(&extract_dir, "cer")
        .ok_or_else(|| "压缩包中没有找到 .cer 证书文件。".to_string())?;

    emit(app, "log", &format!("证书：{}", cert_path.display()), 1.0);
    emit(app, "log", &format!("MSIX：{}", msix_path.display()), 1.0);
    install_msix_certificate(app, &cert_path)?;

    emit(app, "status", "正在安装 MSIX...", 1.0);
    run_powershell_args(&[
        "Add-AppxPackage",
        "-Path",
        &msix_path.to_string_lossy(),
        "-ForceApplicationShutdown",
    ])
    .map(|_| ())
}

fn install_msix_certificate(app: &AppHandle, cert_path: &Path) -> Result<(), String> {
    let stores = [
        ("本地计算机的受信任根证书颁发机构", "Cert:\\LocalMachine\\Root"),
        ("本地计算机的受信任人", "Cert:\\LocalMachine\\TrustedPeople"),
    ];

    for (display_name, store_location) in stores {
        emit(app, "status", &format!("正在安装证书到{display_name}..."), 1.0);
        emit(app, "log", &format!("导入证书到 {store_location}"), 1.0);
        run_powershell_args(&[
            "Import-Certificate",
            "-FilePath",
            &cert_path.to_string_lossy(),
            "-CertStoreLocation",
            store_location,
        ])?;
    }
    Ok(())
}

fn install_msi(app: &AppHandle, msi_path: &Path, install_dir: &str) -> Result<(), String> {
    let requested_path = PathBuf::from(install_dir);
    fs::create_dir_all(&requested_path).map_err(|error| format!("创建安装目录失败：{error}"))?;
    let install_path = normalize_windows_path(&requested_path);
    let install_folder = format_msi_directory_property(&install_path);
    let log_path = make_temp_file_path("snap_hutao_msi", "log")?;

    emit(app, "status", "正在运行 MSI 安装程序...", 1.0);
    emit(app, "log", &format!("安装路径：{}", install_path.display()), 1.0);
    emit(app, "log", &format!("MSI 日志：{}", log_path.display()), 1.0);

    let script = format!(
        r#"
$msi = {msi}
$target = {target}
$log = {log}
$quotedTarget = '"' + $target + '"'
$arguments = @(
  '/i',
  $msi,
  '/passive',
  '/norestart',
  '/L*v',
  $log,
  ('INSTALLFOLDER=' + $quotedTarget),
  ('INSTALLDIR=' + $quotedTarget),
  ('TARGETDIR=' + $quotedTarget),
  ('APPLICATIONFOLDER=' + $quotedTarget)
)
$process = Start-Process -FilePath 'msiexec.exe' -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
exit $process.ExitCode
"#,
        msi = quote_ps_arg(&msi_path.to_string_lossy()),
        target = quote_ps_arg(&install_folder),
        log = quote_ps_arg(&log_path.to_string_lossy())
    );

    let output = hidden_command("powershell.exe")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &script])
        .output()
        .map_err(|error| format!("启动 msiexec 失败：{error}"))?;

    if !output.status.success() {
        return Err(format!("{}。详细日志：{}", command_error("msiexec", &output), log_path.display()));
    }
    remember_msi_install_path(&install_path)?;
    Ok(())
}

fn normalize_windows_path(path: &Path) -> PathBuf {
    let value = path.to_string_lossy();
    if let Some(stripped) = value.strip_prefix(r"\\?\") {
        PathBuf::from(stripped)
    } else {
        path.to_path_buf()
    }
}

fn install_vc_redist_inner(app: &AppHandle) -> Result<(), String> {
    let work_dir = make_temp_dir("snap_hutao_vc_redist")?;
    let result = (|| {
        let installer_path = work_dir.join("vc_redist.x64.exe");
        download_with_fallback(app, VC_REDIST_X64_URL, &installer_path, 2)?;
        emit(app, "status", "正在安装 VC++ 运行库...", 1.0);
        let output = hidden_command(&installer_path)
            .args(["/install", "/passive", "/norestart"])
            .output()
            .map_err(|error| format!("启动 VC++ 安装程序失败：{error}"))?;
        let code = output.status.code().unwrap_or(-1);
        if !matches!(code, 0 | 1638 | 3010) {
            return Err(command_error("VC++ 安装程序", &output));
        }
        if code == 3010 {
            emit(app, "log", "VC++ 运行库安装完成，可能需要重启 Windows 后生效。", 1.0);
        }
        Ok(())
    })();
    let _ = fs::remove_dir_all(&work_dir);
    result
}

fn download_with_fallback(app: &AppHandle, url: &str, target: &Path, threads: usize) -> Result<(), String> {
    match download_ranged(app, url, target, threads) {
        Ok(()) => Ok(()),
        Err(error) => {
            emit(app, "log", &format!("分片下载失败，切换兼容模式：{error}"), 0.0);
            download_stream(app, url, target)
        }
    }
}

fn download_ranged(app: &AppHandle, url: &str, target: &Path, threads: usize) -> Result<(), String> {
    fs::create_dir_all(target.parent().unwrap_or_else(|| Path::new("."))).map_err(|error| error.to_string())?;
    let client = Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|error| error.to_string())?;
    let total = client
        .head(url)
        .header(USER_AGENT, USER_AGENT_VALUE)
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| format!("无法获取安装包大小：{error}"))?
        .headers()
        .get(CONTENT_LENGTH)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .ok_or_else(|| "无法获取安装包大小，不能进行分片下载。".to_string())?;

    if total == 0 {
        return Err("安装包大小为 0。".to_string());
    }

    emit(app, "log", &format!("开始 {threads} 线程下载，文件大小 {}", format_size(total)), 0.0);
    emit(app, "status", "正在下载安装包...", 0.0);

    let downloaded = Arc::new(Mutex::new(0u64));
    let mut handles = Vec::new();
    let chunk = total / threads as u64;
    for index in 0..threads {
        let start = index as u64 * chunk;
        let end = if index == threads - 1 { total - 1 } else { start + chunk - 1 };
        let part_path = target.with_extension(format!("part{index}"));
        let downloaded = Arc::clone(&downloaded);
        let url = url.to_string();
        handles.push(thread::spawn(move || -> Result<PathBuf, String> {
            let client = Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .map_err(|error| error.to_string())?;
            let mut response = client
                .get(url)
                .header(USER_AGENT, USER_AGENT_VALUE)
                .header(RANGE, format!("bytes={start}-{end}"))
                .send()
                .and_then(|response| response.error_for_status())
                .map_err(|error| error.to_string())?;
            if response.status().as_u16() != 206 {
                return Err("服务器未按 Range 请求返回分片内容。".to_string());
            }

            let mut output = File::create(&part_path).map_err(|error| error.to_string())?;
            let mut buffer = [0u8; 256 * 1024];
            loop {
                let read = response.read(&mut buffer).map_err(|error| error.to_string())?;
                if read == 0 {
                    break;
                }
                output.write_all(&buffer[..read]).map_err(|error| error.to_string())?;
                let mut value = downloaded.lock().map_err(|_| "下载进度锁定失败。".to_string())?;
                *value += read as u64;
            }
            Ok(part_path)
        }));
    }

    loop {
        let progress = *downloaded.lock().map_err(|_| "下载进度锁定失败。".to_string())?;
        emit(
            app,
            "progress",
            &format!("已下载 {} / {}", format_size(progress), format_size(total)),
            (progress as f64 / total as f64).clamp(0.0, 1.0),
        );
        if handles.iter().all(|handle| handle.is_finished()) {
            break;
        }
        thread::sleep(Duration::from_millis(250));
    }

    let mut part_paths = Vec::new();
    for handle in handles {
        part_paths.push(handle.join().map_err(|_| "下载线程异常退出。".to_string())??);
    }
    part_paths.sort();

    let mut output = File::create(target).map_err(|error| error.to_string())?;
    for part_path in &part_paths {
        let mut part = File::open(part_path).map_err(|error| error.to_string())?;
        io::copy(&mut part, &mut output).map_err(|error| error.to_string())?;
        let _ = fs::remove_file(part_path);
    }

    let actual_size = target.metadata().map_err(|error| error.to_string())?.len();
    if actual_size != total {
        return Err(format!("下载文件大小不匹配：期望 {total} 字节，实际 {actual_size} 字节。"));
    }

    emit(app, "log", "下载完成", 1.0);
    Ok(())
}

fn download_stream(app: &AppHandle, url: &str, target: &Path) -> Result<(), String> {
    fs::create_dir_all(target.parent().unwrap_or_else(|| Path::new("."))).map_err(|error| error.to_string())?;
    emit(app, "status", "正在使用兼容模式下载...", 0.0);
    let client = Client::builder()
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|error| error.to_string())?;
    let mut response = client
        .get(url)
        .header(USER_AGENT, USER_AGENT_VALUE)
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| format!("兼容模式下载失败：{error}"))?;
    let total = response.content_length().unwrap_or(0);
    let mut output = File::create(target).map_err(|error| error.to_string())?;
    let mut downloaded = 0u64;
    let mut buffer = [0u8; 256 * 1024];
    loop {
        let read = response.read(&mut buffer).map_err(|error| error.to_string())?;
        if read == 0 {
            break;
        }
        output.write_all(&buffer[..read]).map_err(|error| error.to_string())?;
        downloaded += read as u64;
        let progress = if total > 0 { downloaded as f64 / total as f64 } else { 0.0 };
        let message = if total > 0 {
            format!("已下载 {} / {}", format_size(downloaded), format_size(total))
        } else {
            format!("已下载 {}", format_size(downloaded))
        };
        emit(app, "progress", &message, progress);
    }
    if target.metadata().map_err(|error| error.to_string())?.len() == 0 {
        return Err("下载文件为空。".to_string());
    }
    emit(app, "log", "下载完成", 1.0);
    Ok(())
}

fn detect_installed_apps() -> InstalledApps {
    InstalledApps {
        msi: detect_msi_install(),
        msix: detect_msix_install(),
    }
}

fn detect_msi_install() -> Option<InstalledInfo> {
    let script = r#"
$roots = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$remembered = ''
try { $remembered = (Get-ItemProperty -Path 'HKCU:\Software\Snap.Hutao.Installer' -Name MSIInstallPath -ErrorAction Stop).MSIInstallPath } catch {}
$defaultPath = ''
foreach ($p in @("$env:ProgramFiles\Snap.Hutao", "${env:ProgramFiles(x86)}\Snap.Hutao")) {
  if ($p -and (Test-Path (Join-Path $p 'Snap.Hutao.exe'))) { $defaultPath = $p; break }
}
$items = Get-ItemProperty $roots -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -and ($_.DisplayName -eq 'Snap.Hutao' -or $_.DisplayName -eq 'Snap Hutao') -and $_.DisplayVersion } |
  ForEach-Object {
    $path = $_.InstallLocation
    if (-not $path -and $_.DisplayIcon) {
      $icon = $_.DisplayIcon.Trim('"')
      $idx = $icon.ToLowerInvariant().IndexOf('.exe')
      if ($idx -ge 0) { $path = Split-Path $icon.Substring(0, $idx + 4) -Parent }
    }
    if (-not $path) { $path = $remembered }
    if (-not $path) { $path = $defaultPath }
    if (-not $path) { $path = '' }
    [pscustomobject]@{ packageType='msi'; version=[string]$_.DisplayVersion; installPath=[string]$path }
  }
$selected = $items | Sort-Object Version -Descending | Select-Object -First 1
if ($selected) { $selected | ConvertTo-Json -Compress }
"#;
    let output = run_powershell_script(script).ok()?;
    if output.trim().is_empty() { return None; }
    serde_json::from_str(&output).ok()
}

fn detect_msix_install() -> Option<InstalledInfo> {
    let script = r#"
$pkg = Get-AppxPackage -Name '*Snap*Hutao*' -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -eq 'Snap.Hutao' -or $_.Name -like '*Snap*Hutao*' -or $_.PackageFullName -like 'Snap.Hutao_*' } |
  Sort-Object Version -Descending |
  Select-Object -First 1
if ($pkg) {
  $location = $pkg.InstallLocation
  if (-not $location) { $location = '' }
  [pscustomobject]@{ packageType='msix'; version=[string]$pkg.Version; installPath=[string]$location } |
    ConvertTo-Json -Compress
}
"#;
    let output = run_powershell_script(script).ok()?;
    if output.trim().is_empty() { return None; }
    serde_json::from_str(&output).ok()
}

fn is_vc_redist_x64_installed() -> bool {
    let script = r#"
$paths = @(
  'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
)
foreach ($path in $paths) {
  try {
    $item = Get-ItemProperty -Path $path -ErrorAction Stop
    if ($item.Installed -eq 1 -and $item.Major -ge 14) { 'true'; exit 0 }
  } catch {}
}
'false'
"#;
    run_powershell_script(script)
        .map(|output| output.trim().eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

fn remember_msi_install_path(path: &Path) -> Result<(), String> {
    let script = format!(
        "New-Item -Path 'HKCU:\\Software\\Snap.Hutao.Installer' -Force | Out-Null; Set-ItemProperty -Path 'HKCU:\\Software\\Snap.Hutao.Installer' -Name MSIInstallPath -Value {}",
        quote_ps_arg(&path.to_string_lossy())
    );
    run_powershell_script(&script).map(|_| ())
}

fn run_powershell_args(args: &[&str]) -> Result<String, String> {
    let script = args.iter().map(|arg| quote_ps_arg(arg)).collect::<Vec<_>>().join(" ");
    run_powershell_script(&script)
}

fn run_powershell_script(script: &str) -> Result<String, String> {
    let script = format!(
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; {script}"
    );
    let output = hidden_command("powershell.exe")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &script])
        .output()
        .map_err(|error| format!("启动 PowerShell 失败：{error}"))?;
    if !output.status.success() {
        return Err(command_error("PowerShell", &output));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn hidden_command<S: AsRef<std::ffi::OsStr>>(program: S) -> Command {
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command
}

fn command_error(name: &str, output: &std::process::Output) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if !stderr.is_empty() {
        stderr
    } else if !stdout.is_empty() {
        stdout
    } else {
        format!("{name} 返回码 {}", output.status.code().unwrap_or(-1))
    }
}

fn emit(app: &AppHandle, kind: &str, message: &str, progress: f64) {
    let _ = app.emit(
        "install-event",
        InstallEvent {
            kind: kind.to_string(),
            message: message.to_string(),
            progress,
        },
    );
}

fn find_file_with_extension(root: &Path, extension: &str) -> Option<PathBuf> {
    for entry in fs::read_dir(root).ok()? {
        let path = entry.ok()?.path();
        if path.is_dir() {
            if let Some(found) = find_file_with_extension(&path, extension) {
                return Some(found);
            }
        } else if path
            .extension()
            .and_then(|value| value.to_str())
            .is_some_and(|value| value.eq_ignore_ascii_case(extension))
        {
            return Some(path);
        }
    }
    None
}

fn make_temp_dir(prefix: &str) -> Result<PathBuf, String> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_millis();
    let path = std::env::temp_dir().join(format!("{prefix}_{millis}"));
    fs::create_dir_all(&path).map_err(|error| error.to_string())?;
    Ok(path)
}

fn make_temp_file_path(prefix: &str, extension: &str) -> Result<PathBuf, String> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_millis();
    Ok(std::env::temp_dir().join(format!("{prefix}_{millis}.{extension}")))
}

fn default_install_dir() -> String {
    std::env::var("LOCALAPPDATA")
        .map(|value| PathBuf::from(value).join("Snap.Hutao").to_string_lossy().to_string())
        .unwrap_or_else(|_| "C:\\Program Files\\Snap.Hutao".to_string())
}

fn format_msi_directory_property(path: &Path) -> String {
    path.to_string_lossy()
        .trim_end_matches(['\\', '/'])
        .to_string()
}

fn format_size(size: u64) -> String {
    let mut value = size as f64;
    for unit in ["B", "KB", "MB", "GB"] {
        if value < 1024.0 || unit == "GB" {
            return format!("{value:.1} {unit}");
        }
        value /= 1024.0;
    }
    format!("{size} B")
}

fn version_key(version: &str) -> Vec<u32> {
    version
        .split('.')
        .map(|part| part.parse::<u32>().unwrap_or(0))
        .collect()
}

fn quote_ps_arg(value: &str) -> String {
    if value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '\\' | ':' | '.' | '-' | '_' | '/'))
    {
        value.to_string()
    } else {
        format!("'{}'", value.replace('\'', "''"))
    }
}

fn is_running_as_admin() -> bool {
    let script = "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)";
    run_powershell_script(script)
        .map(|output| output.trim().eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            refresh_packages,
            refresh_installed,
            install_package,
            install_vc_redist,
            relaunch_as_admin
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
