# 本地互联（rustdesk_patch）

这是基于官方 [RustDesk](https://github.com/rustdesk/rustdesk) 的补丁与自动编译仓库。仓库本身不含 RustDesk 完整源码，只在 GitHub Actions 中克隆对应官方版本、运行 `patch_rustdesk.py`，再编译并发布到本仓库的 Releases。

默认软件显示名称为 **本地互联**。

- 本仓库 Releases：<https://github.com/s1oz/rustdesk_patch/releases>
- 官方项目：<https://github.com/rustdesk/rustdesk>

## 这个仓库做了什么

相对官方客户端，当前补丁会：

- **自定义显示名称**：默认「本地互联」，窗口标题、托盘、Android 应用标签等会一起改掉。内部二进制 / 服务名仍保留 `RustDesk`，以免便携包和 Windows 自动更新识别出错。
- **Windows 无感被控**：隐藏被控端连接管理（CM）弹窗。这是桌面窗口技巧；Android 没有对应桌面窗口时，补丁会安全跳过，不会因此失败。
- **界面清理**：隐藏主界面底部「自建服务器」提示条；去掉桌面设置里的「账户」「关于」页；若未配置自定义 `API_SERVER`，会清空源码里默认的 `https://admin.rustdesk.com`。
- **Windows 应用内自动更新改指向本仓库**：版本检查和更新下载改为本仓库 Releases，并用本仓库自己的 ed25519 密钥校验 `rustdesk-update.json`（不是官方密钥）。
- **Android 使用独立应用 ID**：默认 `com.s1oz.bendihulian`，可以和官方 RustDesk（`com.carriez.flutter_hbb`）同时安装，不会互相覆盖。

本仓库 **没有** 改官方协议，也 **没有** 提供自建服务器。是否内置服务器地址是可选配置。

## 如何下载与安装

打开 [Releases](https://github.com/s1oz/rustdesk_patch/releases)，按版本下载：

| 文件 | 说明 |
| --- | --- |
| `rustdesk-{版本}-install.exe` | Windows 64 位安装包 |
| `rustdesk-{版本}-x86_64.exe` | Windows 64 位便携版 |
| `rustdesk-{版本}-aarch64.apk` | Android 64 位（arm64-v8a，大多数现代手机） |
| `rustdesk-{版本}-armv7.apk` | Android 32 位（armeabi-v7a，较旧手机） |
| `rustdesk-{版本}-x86_64.apk` | Android x86_64（主要用于模拟器） |
| `rustdesk-{版本}-universal.apk` | 上述三个 ABI 合一的通用包，体积更大 |
| `rustdesk-update.json` / `rustdesk-update.json.sig` | 仅供 **Windows** 应用内更新校验，请不要当安装包下载 |

文件名沿用官方 `rustdesk-*.exe` / `rustdesk-*.apk` 形式，只是显示名称是「本地互联」。

### Windows：旧版需要先手动装一次

从 1.5.1 起，官方客户端会下载并校验 `rustdesk-update.json`。本仓库早期发布的、尚未带上本仓库签名公钥的 Windows 客户端，**不能**直接在软件里升级到本仓库的新版本（它们仍信任官方公钥和官方仓库地址）。

请先从 Releases **手动安装一次** 已带签名更新的版本（当前为 1.5.3 及之后）。之后同一套签名的后续 Windows 更新就可以在软件内完成。

### Android：请从 Releases 安装新 APK

官方 Android 客户端 **不会** 使用 GitHub 上的 `rustdesk-update.json` 做应用内自动更新。请每次到 Releases 下载并安装新的 APK。

覆盖安装必须同时满足：

1. 还是同一个 `applicationId`（默认 `com.s1oz.bendihulian`）；
2. 还是同一把 Android 签发证书。

**一旦丢失签发用的 keystore，用户将无法对已安装的应用做覆盖更新**，只能卸载后重装，应用数据可能丢失。请把 keystore 备份放在安全的地方，不要提交到 Git 仓库。

## 每日上游同步

工作流每天 **08:00（Asia/Hong_Kong，即 UTC 00:00）** 检查官方 `rustdesk/rustdesk` 是否有新的正式版。对应 cron 为 `0 0 * * *`。

- 若本仓库还没有该版本的 Release，会自动编译并发布 Windows 与 Android。
- 若该版本已经发布过，定时任务会跳过，避免无意义重复编译。
- 在 Actions 页面手动「Run workflow」时，默认允许强制重编并覆盖同版本产物。

## 如何手动运行工作流

1. 打开仓库的 Actions 页面，选择工作流 **Auto Sync & Build 本地互联 (Windows + Android)**（文件名仍是 `.github/workflows/rustdesk-win64-auto-build.yml`）。
2. 点击 **Run workflow**。
3. 填写输入后运行。一次手动运行会针对 **同一个版本** 并行编译 Windows 和 Android，并上传到同一个 GitHub Release（tag 就是版本号，例如 `1.5.3`）。

### 工作流输入

| 输入 | 含义 | 默认值 |
| --- | --- | --- |
| `version` | 要编译的官方版本号（如 `1.5.3`）。留空则使用官方最新正式版 | 空 |
| `app_name` | 客户端显示名称 | `本地互联` |
| `force_build` | 本仓库已有同版本 Release 时，是否强制重新编译并覆盖产物 | 手动触发时为 `true` |
| `application_id` | Android `applicationId`，必须不同于官方的 `com.carriez.flutter_hbb` | `com.s1oz.bendihulian` |

工作流会先读取官方对应 tag 的 `flutter-build.yml` / `bridge.yml`，尽量沿用官方的 Flutter、flutter_rust_bridge、vcpkg、Rust、NDK、cargo-ndk 版本；解析失败时回退到与官方 1.5.3 一致的默认值。

## Secrets 与 Variables

在仓库 **Settings → Secrets and variables → Actions** 中配置。下面只列出名称，不要把私钥、密码或 keystore 写进 README、Issue 或 Git 提交。

### 可选：内置自建服务器

不设置时，客户端不会写死服务器地址，用户仍可在软件里自行填写。

| 名称 | 类型 | 作用 |
| --- | --- | --- |
| `RENDEZVOUS_SERVER` | Secret | 可选，内置 ID 服务器（hbbs） |
| `RELAY_SERVER` | Secret | 可选，内置中继服务器（hbbr） |
| `API_SERVER` | Secret | 可选，内置 API 服务器。若未设置，补丁会清空官方默认的 `https://admin.rustdesk.com` |
| `RS_PUB_KEY` | Secret | 可选，自建服务器的 Base64 公钥 |

### Windows 自动更新签名

| 名称 | 类型 | 作用 |
| --- | --- | --- |
| `RUSTDESK_UPDATE_ED25519_SEED` | Secret | 本仓库更新元数据的 ed25519 私钥种子。丢失后无法再为同一套已发布客户端签发更新元数据 |
| `RUSTDESK_UPDATE_ED25519_PUBLIC_KEY` | Variable | 对应公钥（可公开）。工作流和 `patch_rustdesk.py` 会把它写入客户端信任列表 |

默认的更新密钥 ID 为 `s1oz-ed25519-main`。脚本里也内置了与该 Variable 相同的默认公钥，便于本地跑补丁；真正签名必须依赖上面的 Seed Secret。

### Android 发行签名

| 名称 | 类型 | 作用 |
| --- | --- | --- |
| `ANDROID_SIGNING_KEY` | Secret | 发行 keystore 的 Base64 |
| `ANDROID_ALIAS` | Secret | keystore 中的别名 |
| `ANDROID_KEY_STORE_PASSWORD` | Secret | keystore 密码 |
| `ANDROID_KEY_PASSWORD` | Secret | 密钥密码 |

这四个 Secret 必须同时存在，工作流才会签名并发布 APK。**缺少其中任一项时，不会把调试签名或未签名的 APK 当作正式版发布。**

工作流没有 `APPLICATION_ID` 这个 Secret；应用 ID 来自手动运行时的 `application_id` 输入，或默认值 `com.s1oz.bendihulian`。

## `patch_rustdesk.py` 命令行参数

脚本在克隆后的官方源码目录上打补丁。工作流会自动调用；本地也可手动运行。

| 参数 | 对应环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--root` | — | `.` | RustDesk 源码根目录 |
| `--repo` | `GITHUB_REPOSITORY` | 空（必须是 `owner/repo`） | Windows 更新检查与下载指向的仓库 |
| `--app-name` | `CUSTOM_APP_NAME` | `本地互联` | 显示名称 |
| `--id-server` | `RENDEZVOUS_SERVER` | 空 | 可选内置 ID 服务器 |
| `--relay-server` | `RELAY_SERVER` | 空 | 可选内置中继服务器 |
| `--api-server` | `API_SERVER` | 空 | 可选内置 API 服务器 |
| `--pub-key` | `RS_PUB_KEY` | 空 | 可选自建服务器公钥 |
| `--update-key-id` | `RUSTDESK_UPDATE_KEY_ID` | `s1oz-ed25519-main` | 更新元数据签名的 key id |
| `--update-public-key` | `RUSTDESK_UPDATE_ED25519_PUBLIC_KEY` | 脚本内置的本仓库公钥 | 客户端信任的更新公钥（标准 Base64） |
| `--application-id` | `APPLICATION_ID` | `com.s1oz.bendihulian` | Android `applicationId`，禁止填官方 ID |

Android 只会修改 Gradle 里的 `applicationId`，**不会**改 `namespace` 和 Kotlin 包名（仍为 `com.carriez.flutter_hbb`），以免 `R` / `BuildConfig` 引用编译失败。应用标签会同步改到 `AndroidManifest.xml` 和 `strings.xml`。

## 哪些可以自定义，哪些是写死的

**可配置（工作流输入、Secrets、Variables 或脚本参数）：**

- 要编译的官方版本、是否强制重编
- 显示名称 `app_name`
- Android `application_id`
- 可选的内置服务器地址和公钥
- Windows 更新签名的 key id、公钥和私钥种子
- Android 发行签名 keystore 及其密码

**每次构建都会应用、不能靠上述输入关掉的行为：**

- Windows 隐藏 CM 弹窗
- 上述界面清理
- 把 Windows 更新检查 / 下载地址改到本仓库，并要求校验带签名的 `rustdesk-update.json`
- Android 使用自定义 `applicationId`（可用参数改成别的，但不能保持官方 ID）
- 缺失 Android 签名 Secret 时拒绝发布非发行签名 APK

## 安全提醒

- **不要**把私钥、keystore、密码、更新签名 seed 提交到本仓库或写进 Issue / README。本仓库是公开的。
- 丢失 Android keystore 后，已安装用户无法覆盖更新同一应用。
- 丢失更新签名 seed 后，已安装的、已写入该公钥的 Windows 客户端将无法再校验新的 `rustdesk-update.json`。
- 本仓库只维护补丁脚本和工作流。请以官方 [rustdesk/rustdesk](https://github.com/rustdesk/rustdesk) 的安全说明和许可证为准。
