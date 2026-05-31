<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open } from "@tauri-apps/plugin-dialog";
import appIcon from "./assets/1.png";

type PackageType = "msix" | "msi";

type PackageInfo = {
  version: string;
  packageType: PackageType | string;
  downloadUrl: string;
  features: string;
  fileSize: string;
  createdAt: string;
  isActive: boolean;
  isTest: boolean;
};

type InstalledInfo = {
  packageType: string;
  version: string;
  installPath: string;
};

type InstalledApps = {
  msi: InstalledInfo | null;
  msix: InstalledInfo | null;
};

type BootstrapData = {
  packages: PackageInfo[];
  installed: InstalledApps;
  defaultInstallDir: string;
  isAdmin: boolean;
  vcRedistInstalled: boolean;
};

type InstallEvent = {
  kind: "status" | "progress" | "log" | "done" | "error";
  message: string;
  progress: number;
};

const licenseText = `WDG Snap Hutao 安装许可确认

在继续安装前，请确认你理解并同意以下事项：
1. 原开发者已不参与维护，请勿打扰原作者。
2. 如果选择安装 MSIX 包，程序需要安装证书后才能安装软件。

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

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.`;

const packages = ref<PackageInfo[]>([]);
const installed = ref<InstalledApps>({ msi: null, msix: null });
const selectedVersion = ref("");
const selectedType = ref<PackageType>("msix");
const installDir = ref("");
const licenseAccepted = ref(false);
const busy = ref(false);
const loading = ref(true);
const isAdmin = ref(false);
const vcRedistInstalled = ref(false);
const statusText = ref("正在初始化安装器...");
const progress = ref(0);
const logs = ref<string[]>([]);
const activeStep = ref(0);
const maxStep = ref(0);
const installFinished = ref(false);
const installFailed = ref(false);

const steps = ["初始化", "选择安装", "许可确认", "安装进度", "完成"];

const versions = computed(() => {
  const values: string[] = [];
  packages.value.forEach((item) => {
    if (!values.includes(item.version)) {
      values.push(item.version);
    }
  });
  return values;
});

const availableTypes = computed(() => {
  const values = packages.value
    .filter((item) => item.version === selectedVersion.value)
    .map((item) => item.packageType)
    .filter((item): item is PackageType => item === "msix" || item === "msi");
  return Array.from(new Set(values));
});

const selectedPackage = computed(() =>
  packages.value.find(
    (item) => item.version === selectedVersion.value && item.packageType === selectedType.value,
  ) ?? null,
);

const selectedInstalled = computed(() =>
  selectedType.value === "msi" ? installed.value.msi : installed.value.msix,
);

const packageMeta = computed(() => [
  { label: "当前选择", value: `${selectedPackage.value?.version ?? "未选择"} / ${selectedType.value.toUpperCase()}` },
  { label: "安装包大小", value: selectedPackage.value?.fileSize || "下载前自动探测" },
  { label: "发布时间", value: selectedPackage.value?.createdAt || "未知" },
]);

const packageRelation = computed(() => {
  const current = selectedInstalled.value;
  const target = selectedPackage.value;
  if (!current || !target) {
    return `本机未检测到 ${selectedType.value.toUpperCase()} 安装。`;
  }
  const comparison = compareVersions(target.version, current.version);
  if (comparison > 0) {
    return `已检测到 ${current.packageType.toUpperCase()} ${current.version}，本次将更新。`;
  }
  if (comparison < 0) {
    return `已检测到 ${current.packageType.toUpperCase()} ${current.version}，本次将降级。`;
  }
  return `已检测到 ${current.packageType.toUpperCase()} ${current.version}，本次将重新安装。`;
});

const installedSummary = computed(() => {
  const items = [];
  items.push(installed.value.msix ? `MSIX ${installed.value.msix.version}` : "未检测到 MSIX");
  items.push(installed.value.msi ? `MSI ${installed.value.msi.version}` : "未检测到 MSI");
  return items.join(" / ");
});

const canContinueSelection = computed(() =>
  Boolean(selectedPackage.value && (!busy.value || activeStep.value < 3)),
);

const canStartInstall = computed(() =>
  Boolean(selectedPackage.value && licenseAccepted.value && !busy.value && !loading.value),
);

watch(selectedVersion, () => {
  if (!availableTypes.value.includes(selectedType.value)) {
    selectedType.value = availableTypes.value[0] ?? "msix";
  }
});

onMounted(async () => {
  const unlisten = await listen<InstallEvent>("install-event", (event) => {
    handleInstallEvent(event.payload);
  });
  window.addEventListener("beforeunload", () => {
    void unlisten();
  });
  await loadBootstrap();
});

async function loadBootstrap() {
  loading.value = true;
  busy.value = true;
  activeStep.value = 0;
  maxStep.value = 0;
  statusText.value = "正在获取安装包列表并检测现有安装...";
  try {
    const data = await invoke<BootstrapData>("bootstrap");
    packages.value = data.packages;
    installed.value = data.installed;
    installDir.value = data.installed.msi?.installPath || data.defaultInstallDir;
    isAdmin.value = data.isAdmin;
    vcRedistInstalled.value = data.vcRedistInstalled;
    selectedVersion.value = versions.value[0] ?? "";
    selectedType.value = availableTypes.value.includes("msix") ? "msix" : availableTypes.value[0] ?? "msix";
    statusText.value = `已加载 ${data.packages.length} 个安装包。`;
    appendLog("初始化完成。");
    activeStep.value = 1;
    maxStep.value = 1;
  } catch (error) {
    statusText.value = "初始化失败。";
    appendLog(String(error));
  } finally {
    loading.value = false;
    busy.value = false;
  }
}

async function refreshAll() {
  loading.value = true;
  statusText.value = "正在刷新安装信息...";
  try {
    packages.value = await invoke<PackageInfo[]>("refresh_packages");
    installed.value = await invoke<InstalledApps>("refresh_installed");
    if (!selectedVersion.value) {
      selectedVersion.value = versions.value[0] ?? "";
    }
    statusText.value = "刷新完成。";
    appendLog("已刷新安装包与本机安装状态。");
  } catch (error) {
    statusText.value = "刷新失败。";
    appendLog(String(error));
  } finally {
    loading.value = false;
  }
}

async function chooseInstallDir() {
  const selected = await open({
    directory: true,
    multiple: false,
    defaultPath: installDir.value || undefined,
    title: "选择 MSI 安装目录",
  });
  if (typeof selected === "string") {
    installDir.value = selected;
  }
}

function goToLicense() {
  activeStep.value = 2;
  maxStep.value = Math.max(maxStep.value, 2);
}

async function startInstall() {
  const target = selectedPackage.value;
  if (!target) {
    return;
  }
  if (target.packageType === "msix" && !isAdmin.value) {
    const relaunch = confirm("MSIX 证书安装需要管理员权限。是否现在以管理员身份重新启动安装器？");
    if (relaunch) {
      await invoke("relaunch_as_admin");
    }
    return;
  }
  const installedInfo = selectedInstalled.value;
  if (installedInfo && target.packageType === "msix" && compareVersions(target.version, installedInfo.version) < 0) {
    alert(`已安装 MSIX ${installedInfo.version}，不能安装更低版本 ${target.version}。`);
    return;
  }
  if (installedInfo && !confirm(`${packageRelation.value}\n\n用户数据将保留。是否继续？`)) {
    return;
  }

  busy.value = true;
  installFinished.value = false;
  installFailed.value = false;
  progress.value = 0;
  activeStep.value = 3;
  maxStep.value = 3;
  statusText.value = "准备下载安装包...";
  try {
    await invoke("install_package", {
      request: {
        package: target,
        installDir: installDir.value,
      },
    });
    installed.value = await invoke<InstalledApps>("refresh_installed");
  } catch (error) {
    installFailed.value = true;
    statusText.value = "安装失败。";
    appendLog(String(error));
  } finally {
    busy.value = false;
    installFinished.value = true;
    activeStep.value = 4;
    maxStep.value = 4;
  }
}

async function installVcRedist() {
  busy.value = true;
  progress.value = 0;
  statusText.value = "正在准备安装 VC++ 运行库...";
  try {
    await invoke("install_vc_redist");
    vcRedistInstalled.value = true;
  } catch (error) {
    statusText.value = "VC++ 运行库安装失败。";
    appendLog(String(error));
  } finally {
    busy.value = false;
  }
}

async function closeApp() {
  await getCurrentWindow().close();
}

function handleInstallEvent(event: InstallEvent) {
  if (event.kind === "progress") {
    progress.value = event.progress;
    statusText.value = event.message;
    return;
  }
  if (event.kind === "status") {
    statusText.value = event.message;
    return;
  }
  if (event.kind === "done") {
    progress.value = 1;
    statusText.value = event.message;
    appendLog(event.message);
    return;
  }
  if (event.kind === "error") {
    installFailed.value = true;
  }
  appendLog(event.message);
}

function onVersionChange(event: Event) {
  selectedVersion.value = (event.target as HTMLInputElement).value;
}

function onTypeChange(event: Event) {
  const value = (event.target as HTMLInputElement).value;
  if (value === "msix" || value === "msi") {
    selectedType.value = value;
  }
}

function onInstallDirInput(event: Event) {
  installDir.value = (event.target as HTMLInputElement).value;
}

function onLicenseChange(event: Event) {
  licenseAccepted.value = (event.target as HTMLInputElement).checked;
}

function appendLog(message: string) {
  const timestamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  logs.value = [...logs.value.slice(-120), `[${timestamp}] ${message}`];
}

function compareVersions(left: string, right: string) {
  const leftParts = left.split(".").map((part) => Number.parseInt(part, 10) || 0);
  const rightParts = right.split(".").map((part) => Number.parseInt(part, 10) || 0);
  const length = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < length; index += 1) {
    const leftValue = leftParts[index] ?? 0;
    const rightValue = rightParts[index] ?? 0;
    if (leftValue !== rightValue) {
      return leftValue > rightValue ? 1 : -1;
    }
  }
  return 0;
}
</script>

<template>
  <main class="shell">
    <aside class="nav-pane">
      <div class="brand">
        <img class="brand-icon" :src="appIcon" alt="" />
        <div>
          <p class="caption">WDG Snap Hutao</p>
          <h1>安装器</h1>
        </div>
      </div>

      <fluent-divider></fluent-divider>

      <nav class="steps" aria-label="安装步骤">
        <fluent-button
          v-for="(step, index) in steps"
          :key="step"
          class="step-button"
          :appearance="index === activeStep ? 'accent' : 'stealth'"
          type="button"
          :disabled="index > maxStep || busy"
          @click="activeStep = index"
        >
          <span class="step-index" :class="{ complete: index < activeStep }">{{ index + 1 }}</span>
          {{ step }}
        </fluent-button>
      </nav>

      <section class="side-status">
        <p>{{ statusText }}</p>
        <fluent-progress :value="progress" min="0" max="1"></fluent-progress>
        <strong>{{ Math.round(progress * 100) }}%</strong>
      </section>
    </aside>

    <section class="content">
      <fluent-card class="page-card">
        <section v-if="activeStep === 0" class="page init-page">
          <div class="page-heading">
            <p class="caption">准备中</p>
            <h2>正在初始化和检测安装</h2>
            <p>正在获取可用安装包，并检测本机已安装的 MSI / MSIX 版本。</p>
          </div>
          <fluent-progress></fluent-progress>
          <div class="actions">
            <fluent-button appearance="outline" type="button" :disabled="loading" @click="loadBootstrap">
              重试
            </fluent-button>
          </div>
        </section>

        <section v-else-if="activeStep === 1" class="page">
          <div class="page-heading">
            <p class="caption">选择安装</p>
            <h2>选择版本和安装方式</h2>
            <p>{{ installedSummary }}</p>
          </div>

          <div class="form-grid">
            <label class="field">
              <span>版本</span>
              <fluent-select class="full-control" :value="selectedVersion" :disabled="busy || loading" @change="onVersionChange">
                <fluent-option v-for="version in versions" :key="version" :value="version">
                  {{ version }}{{ packages.find((item) => item.version === version)?.isTest ? " - 测试版" : "" }}
                </fluent-option>
              </fluent-select>
            </label>

            <div class="field">
              <span>安装方式</span>
              <fluent-radio-group
                class="package-radio"
                orientation="horizontal"
                :value="selectedType"
                :disabled="busy || loading"
                @change="onTypeChange"
              >
                <fluent-radio v-for="type in availableTypes" :key="type" :value="type">
                  {{ type.toUpperCase() }}
                </fluent-radio>
              </fluent-radio-group>
            </div>

            <label v-if="selectedType === 'msi'" class="field wide">
              <span>MSI 安装路径</span>
              <div class="path-row">
                <fluent-text-field
                  class="full-control"
                  appearance="outline"
                  :value="installDir"
                  :disabled="busy"
                  spellcheck="false"
                  @input="onInstallDirInput"
                ></fluent-text-field>
                <fluent-button appearance="outline" type="button" :disabled="busy" @click="chooseInstallDir">
                  浏览
                </fluent-button>
              </div>
            </label>
          </div>

          <section class="callout" :class="{ warning: selectedType === 'msix' && !isAdmin }">
            <strong>{{ selectedType === "msix" && !isAdmin ? "需要管理员权限" : "安装状态检测" }}</strong>
            <p>
              {{
                selectedType === "msix" && !isAdmin
                  ? "MSIX 需要导入证书，请以管理员身份运行安装器。"
                  : packageRelation
              }}
            </p>
          </section>

          <section class="meta-grid">
            <fluent-card v-for="item in packageMeta" :key="item.label" class="meta-card">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </fluent-card>
          </section>

          <section class="features">
            <h3>更新说明</h3>
            <p>{{ selectedPackage?.features || "暂无更新说明。" }}</p>
          </section>

          <div class="actions">
            <fluent-button appearance="outline" type="button" :disabled="loading || busy" @click="refreshAll">
              刷新
            </fluent-button>
            <fluent-button appearance="accent" type="button" :disabled="!canContinueSelection" @click="goToLicense">
              下一步
            </fluent-button>
          </div>
        </section>

        <section v-else-if="activeStep === 2" class="page">
          <div class="page-heading">
            <p class="caption">许可确认</p>
            <h2>确认许可和安装提示</h2>
            <p>继续安装前，请阅读并确认许可文本。</p>
          </div>
          <fluent-text-area class="license-box" appearance="outline" readonly :value="licenseText"></fluent-text-area>
          <fluent-checkbox :checked="licenseAccepted" :disabled="busy" @change="onLicenseChange">
            我已阅读并同意许可及安装操作说明
          </fluent-checkbox>
          <div class="actions">
            <fluent-button appearance="outline" type="button" :disabled="busy" @click="activeStep = 1">
              上一步
            </fluent-button>
            <fluent-button appearance="accent" type="button" :disabled="!canStartInstall" @click="startInstall">
              开始安装
            </fluent-button>
          </div>
        </section>

        <section v-else-if="activeStep === 3" class="page progress-page">
          <div class="page-heading">
            <p class="caption">安装进度</p>
            <h2>正在下载并安装</h2>
            <p>{{ statusText }}</p>
          </div>
          <div class="big-progress">
            <fluent-progress :value="progress" min="0" max="1"></fluent-progress>
            <strong>{{ Math.round(progress * 100) }}%</strong>
          </div>
          <div class="log-list">
            <p v-for="line in logs" :key="line">{{ line }}</p>
          </div>
        </section>

        <section v-else class="page done-page">
          <div class="page-heading">
            <p class="caption">完成</p>
            <h2>{{ installFailed ? "安装未完成" : "安装已完成" }}</h2>
            <p>{{ statusText }}</p>
          </div>
          <section class="callout" :class="{ warning: installFailed }">
            <strong>{{ installFailed ? "请查看日志" : "可以退出安装器" }}</strong>
            <p>{{ installFailed ? "安装过程中发生错误，下面保留了最近日志。" : installedSummary }}</p>
          </section>
          <div class="log-list">
            <p v-for="line in logs" :key="line">{{ line }}</p>
          </div>
          <div class="actions">
            <fluent-button v-if="!vcRedistInstalled && !installFailed" appearance="outline" type="button" :disabled="busy" @click="installVcRedist">
              安装 VC++ 运行库
            </fluent-button>
            <fluent-button v-if="installFailed" appearance="outline" type="button" :disabled="busy" @click="activeStep = 1">
              返回修改
            </fluent-button>
            <fluent-button appearance="accent" type="button" @click="closeApp">
              退出
            </fluent-button>
          </div>
        </section>
      </fluent-card>
    </section>
  </main>
</template>

<style>
:root {
  --app-accent: #0067c0;
  --app-bg: #f3f3f3;
  --app-pane: rgba(255, 255, 255, 0.76);
  --app-card: rgba(255, 255, 255, 0.9);
  --app-text: #1b1b1f;
  --app-muted: #61656d;
  --app-border: rgba(0, 0, 0, 0.08);
  --app-callout: #f4f7fb;
  --app-warning: #fff8e8;
  --app-warning-text: #5c3b00;
  color: var(--app-text);
  background: var(--app-bg);
  font-family:
    "Segoe UI Variable",
    "Segoe UI",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    system-ui,
    sans-serif;
  font-size: 16px;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

:root[data-theme="dark"] {
  --app-bg: #202020;
  --app-pane: rgba(32, 32, 32, 0.78);
  --app-card: rgba(45, 45, 45, 0.92);
  --app-text: #f5f5f5;
  --app-muted: #c8c8c8;
  --app-border: rgba(255, 255, 255, 0.12);
  --app-callout: rgba(76, 141, 199, 0.16);
  --app-warning: rgba(255, 185, 0, 0.14);
  --app-warning-text: #ffd682;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 860px;
  min-height: 600px;
  overflow: hidden;
}

h1,
h2,
h3,
p {
  margin: 0;
}

h1 {
  font-size: 22px;
  line-height: 1.2;
}

h2 {
  font-size: 26px;
  font-weight: 650;
  line-height: 1.2;
}

h3 {
  font-size: 15px;
  font-weight: 650;
}

fluent-card {
  contain: none;
}

.shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  width: 100vw;
  height: 100vh;
  color: var(--app-text);
  background: var(--app-bg);
}

.nav-pane {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
  padding: 26px 18px;
  border-right: 1px solid var(--app-border);
  background: var(--app-pane);
  backdrop-filter: blur(24px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-icon {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  object-fit: cover;
}

.caption {
  margin-bottom: 4px;
  color: var(--app-muted);
  font-size: 12px;
}

.steps {
  display: grid;
  gap: 4px;
}

.step-button {
  width: 100%;
}

.step-button::part(control) {
  justify-content: flex-start;
}

.step-index {
  display: inline-grid;
  width: 24px;
  height: 24px;
  margin-right: 8px;
  place-items: center;
  border-radius: 50%;
  background: color-mix(in srgb, var(--app-muted), transparent 78%);
  color: var(--app-text);
  font-size: 12px;
}

.step-index.complete {
  color: white;
  background: var(--app-accent);
}

.side-status {
  display: grid;
  gap: 10px;
  margin-top: auto;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-card);
}

.side-status p {
  min-height: 42px;
  color: var(--app-text);
  font-size: 13px;
  line-height: 1.45;
}

.side-status strong {
  color: var(--app-accent);
}

.content {
  display: grid;
  place-items: center;
  min-width: 0;
  padding: 28px;
}

.page-card {
  width: min(760px, 100%);
  height: min(620px, calc(100vh - 56px));
  padding: 0;
  overflow: hidden;
  background: var(--app-card);
}

.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  height: 100%;
  min-height: 0;
  padding: 26px;
}

.page-heading {
  display: grid;
  gap: 6px;
}

.page-heading > p:last-child {
  color: var(--app-muted);
  line-height: 1.45;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.field {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.field.wide {
  grid-column: 1 / -1;
}

.field > span {
  color: var(--app-muted);
  font-size: 12px;
}

.full-control,
.full-control::part(control) {
  width: 100%;
}

.package-radio {
  display: flex;
  min-height: 34px;
  gap: 18px;
}

.path-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

.callout {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-callout);
  color: var(--app-text);
  font-size: 13px;
}

.callout.warning {
  background: var(--app-warning);
  color: var(--app-warning-text);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.meta-card {
  display: grid;
  gap: 5px;
  min-height: 66px;
  padding: 12px;
  background: color-mix(in srgb, var(--app-card), var(--app-bg) 18%);
}

.meta-card span {
  color: var(--app-muted);
  font-size: 12px;
}

.meta-card strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.features {
  display: grid;
  gap: 8px;
  min-height: 0;
}

.features p {
  max-height: 112px;
  overflow: auto;
  color: var(--app-text);
  line-height: 1.55;
  white-space: pre-wrap;
}

.license-box {
  flex: 1;
  width: 100%;
  min-height: 0;
}

.license-box::part(control) {
  height: 100%;
}

.big-progress {
  display: grid;
  gap: 8px;
}

.big-progress strong {
  color: var(--app-accent);
}

.log-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  color: var(--app-text);
  background: color-mix(in srgb, var(--app-card), var(--app-bg) 20%);
  font-family: Consolas, "Cascadia Mono", monospace;
  font-size: 12px;
  line-height: 1.55;
}

.log-list p {
  white-space: pre-wrap;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: auto;
}

.init-page {
  justify-content: center;
}

@media (max-width: 900px) {
  body {
    min-width: 760px;
  }

  .shell {
    grid-template-columns: 226px minmax(0, 1fr);
  }

  .content {
    padding: 18px;
  }

  .form-grid,
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
