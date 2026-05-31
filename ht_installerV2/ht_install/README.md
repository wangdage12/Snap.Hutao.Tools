# Snap Hutao Installer

CustomTkinter 编写的 Snap Hutao Windows 安装器。

## 安装流程

- 从 `https://htserver.wdg12.work/api/download-resources` 获取安装包列表（api文档：https://rdgm3wrj7r.apifox.cn ）
- 启动时自动检测 MSI / MSIX 是否已安装
- 选择版本和安装包类型（MSIX / MSI）
- 显示许可协议并要求同意后继续
- 使用多线程分片下载
- MSIX ZIP 自动解压、安装证书、安装 MSIX
- MSI 支持选择安装路径并自动调用 `msiexec`，已安装时自动回填原安装路径
- 安装成功后检测 Microsoft Visual C++ Redistributable 2015-2022 x64，缺失时可自动下载并安装

## 运行

```powershell
python -m pip install -r requirements.txt
python app.py
```

## 注意

- MSIX 安装需要导入证书，需要管理员权限
- MSI 安装会调用 `msiexec` 并传入 WiX 安装目录属性 `INSTALLFOLDER`，同时保留 `INSTALLDIR`、`TARGETDIR`、`APPLICATIONFOLDER` 作为兼容参数，如果要修改自用，需要确认参数名。
- VC++ 运行库缺失时，会从 `https://aka.ms/vc14/vc_redist.x64.exe` 下载官方安装程序并以 `/install /passive /norestart` 参数运行。
- MSI安装失败可能卡住
