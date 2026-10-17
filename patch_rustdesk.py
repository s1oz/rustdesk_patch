### Gemini Canvas: Patch Rustdesk

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RustDesk Windows (x86_64) 自动补丁脚本 (patch_rustdesk.py)
功能：
  1. 彻底隐藏被控端连接管理弹窗（CM 窗口），消除连接建立时的几秒延迟弹窗（无需内置固定密码、无需 Pro 授权）
  2. 将客户端版本检查与 Windows 自动更新下载地址替换为你的 GitHub 仓库 Releases 地址
  3. 默认启用 Windows 自动更新 (allow-auto-update=Y) 与启动检查更新 (enable-check-update=Y)
  4. （可选）如果环境变量中配置了自建服务器信息 (RENDEZVOUS_SERVER / RS_PUB_KEY / API_SERVER)，自动一并写入
"""

import argparse
import os
import re
import sys
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def patch_config_rs(root: Path, id_server: str, relay_server: str, api_server: str, pub_key: str) -> None:
    """修改 libs/hbb_common/src/config.rs：注入隐藏弹窗与自动更新默认选项，以及可选的自建服务器地址。"""
    config_path = root / "libs" / "hbb_common" / "src" / "config.rs"
    if not config_path.exists():
        print(f"[WARN] 未找到 {config_path}，请确认已拉取 git submodule (libs/hbb_common)", file=sys.stderr)
        return

    content = read_text(config_path)
    original = content

    # 1. 可选：如果传入了自建 ID 服务器或公钥，替换 RENDEZVOUS_SERVERS 与 RS_PUB_KEY
    if id_server:
        content, n = re.subn(
            r"(pub\s+const\s+RENDEZVOUS_SERVERS\s*:\s*&(?:'static\s+)?\[&(?:'static\s+)?str\]\s*=\s*&\[)[^\]]*(\];)",
            rf'\1"{id_server}"\2',
            content,
            count=1,
        )
        print(f"[INFO] config.rs: 已替换 RENDEZVOUS_SERVERS -> {id_server} (匹配 {n} 处)")

    if pub_key:
        content, n = re.subn(
            r'(pub\s+const\s+RS_PUB_KEY\s*:\s*&str\s*=[\s\S]*?_?\s*=>\s*)"[^"]*"',
            rf'\1"{pub_key}"',
            content,
            count=1,
        )
        if n == 0:
            content, n = re.subn(
                r'(pub\s+const\s+RS_PUB_KEY\s*:\s*&str\s*=\s*)"[^"]*"',
                rf'\1"{pub_key}"',
                content,
                count=1,
            )
        print(f"[INFO] config.rs: 已替换 RS_PUB_KEY (匹配 {n} 处)")

    # 2. 在 Config2::load() 中注入全局默认选项：
    #    - allow-hide-cm = Y (允许隐藏连接管理窗口)
    #    - allow-auto-update = Y (开启 Windows 客户端自动从 GitHub Releases 下载并静默更新)
    #    - enable-udp-punch = Y / enable-ipv6-punch = Y (提升 P2P 直连成功率)
    config2_inject_lines = [
        '        let mut store = false;',
        '        for (k, v) in [',
        '            ("allow-hide-cm", "Y"),',
        '            ("allow-auto-update", "Y"),',
        '            ("enable-udp-punch", "Y"),',
        '            ("enable-ipv6-punch", "Y"),',
    ]
    if id_server:
        config2_inject_lines.append(f'            ("custom-rendezvous-server", "{id_server}"),')
    if relay_server:
        config2_inject_lines.append(f'            ("relay-server", "{relay_server}"),')
    if api_server:
        config2_inject_lines.append(f'            ("api-server", "{api_server}"),')
    if pub_key:
        config2_inject_lines.append(f'            ("key", "{pub_key}"),')

    config2_inject_lines.extend([
        '        ] {',
        '            if !config.options.contains_key(k) {',
        '                config.options.insert(k.to_string(), v.to_string());',
        '                store = true;',
        '            }',
        '        }',
        '        if store {',
        '            config.store();',
        '        }',
    ])
    config2_inject_block = "\n".join(config2_inject_lines)

    # 兼容不同版本的 Config2::load 实现
    if 'Config::load_::<Config2>("2")' in content and '"allow-hide-cm", "Y"' not in content:
        pattern_simple = re.compile(
            r'(fn\s+load\s*\(\s*\)\s*->\s*Config2\s*\{\s*)Config::load_::<Config2>\("2"\)\s*(\})'
        )
        if pattern_simple.search(content):
            content = pattern_simple.sub(
                rf'\1let mut config = Config::load_::<Config2>("2");' + "\n" + config2_inject_block + "\n        config\n    " + r'\2',
                content,
                count=1,
            )
            print("[INFO] config.rs: 已在 Config2::load() (简洁结构) 中注入 allow-hide-cm=Y 与 allow-auto-update=Y")
        else:
            pattern_mut = re.compile(r'(let\s+mut\s+config\s*=\s*Config::load_::<Config2>\("2"\);)')
            if pattern_mut.search(content):
                content = pattern_mut.sub(r'\1' + "\n" + config2_inject_block, content, count=1)
                print("[INFO] config.rs: 已在 Config2::load() (可变结构) 中注入 allow-hide-cm=Y 与 allow-auto-update=Y")

    # 3. 在 LocalConfig::load() 中注入本地默认选项：
    #    - hide-cm-window = Y (默认折叠/隐藏连接管理窗口)
    #    - enable-check-update = Y (启动时检查新版本)
    #    - show-scam-warning = N (关闭防诈倒计时提示)
    local_inject_block = "\n".join([
        '        let mut store_custom = false;',
        '        for (k, v) in [',
        '            ("allow-hide-cm", "Y"),',
        '            ("hide-cm-window", "Y"),',
        '            ("enable-check-update", "Y"),',
        '            ("allow-auto-update", "Y"),',
        '            ("show-scam-warning", "N"),',
        '        ] {',
        '            if !config.options.contains_key(k) {',
        '                config.options.insert(k.to_string(), v.to_string());',
        '                store_custom = true;',
        '            }',
        '        }',
        '        if store_custom {',
        '            config.store();',
        '        }',
    ])

    if 'Config::load_::<LocalConfig>("_local")' in content and '"hide-cm-window", "Y"' not in content:
        pattern_local_simple = re.compile(
            r'(fn\s+load\s*\(\s*\)\s*->\s*LocalConfig\s*\{\s*)Config::load_::<LocalConfig>\("_local"\)\s*(\})'
        )
        if pattern_local_simple.search(content):
            content = pattern_local_simple.sub(
                r'\1let mut config = Config::load_::<LocalConfig>("_local");' + "\n" + local_inject_block + "\n        config\n    " + r'\2',
                content,
                count=1,
            )
            print("[INFO] config.rs: 已在 LocalConfig::load() (简洁结构) 中注入 hide-cm-window=Y 与 enable-check-update=Y")
        else:
            pattern_local_mut = re.compile(r'(let\s+mut\s+config\s*=\s*Config::load_::<LocalConfig>\("_local"\);)')
            if pattern_local_mut.search(content):
                content = pattern_local_mut.sub(r'\1' + "\n" + local_inject_block, content, count=1)
                print("[INFO] config.rs: 已在 LocalConfig::load() (可变结构) 中注入 hide-cm-window=Y 与 enable-check-update=Y")

    # 4. 如果新版本存在 DEFAULT_SETTINGS / DEFAULT_LOCAL_SETTINGS 静态数组，也一并注入
    if "DEFAULT_SETTINGS" in content and '"allow-hide-cm"' not in content:
        content = re.sub(
            r'(const\s+DEFAULT_SETTINGS\s*:\s*&\[\(&str,\s*&str\)\]\s*=\s*&\[)',
            r'\1' + '\n    ("allow-hide-cm", "Y"),\n    ("allow-auto-update", "Y"),',
            content,
            count=1,
        )
        print("[INFO] config.rs: 已向 DEFAULT_SETTINGS 注入 allow-hide-cm=Y 与 allow-auto-update=Y")

    if content != original:
        write_text(config_path, content)


def patch_hide_cm_popup(root: Path) -> None:
    """
    修改 Rust 与 Flutter 层的连接管理器 (CM) 弹窗逻辑：
      1. 解除开源版对 allow-hide-cm 的限制（让 allow_hide_cm 恒为 true）
      2. 将 Flutter 端 cm_page.dart 中“弹出几秒后才消失”的定时器延迟改为立即隐藏
    """
    # 1. 修改 Rust 端 (src/ui/cm_interface.rs, src/flutter.rs, src/server/connection.rs 等)
    rust_candidates = []
    if (root / "src").exists():
        rust_candidates.extend((root / "src").rglob("*.rs"))
    if (root / "libs").exists():
        rust_candidates.extend((root / "libs").rglob("*.rs"))

    for rs_file in rust_candidates:
        text = read_text(rs_file)
        orig = text

        # 如果存在 fn allow_hide_cm() -> bool 或类似函数，强制返回 true
        text = re.sub(
            r'(pub\s+fn\s+allow_hide_cm\s*\([^)]*\)\s*->\s*bool\s*\{)',
            r'\1 return true;',
            text,
        )
        # 将 Config::get_option("allow-hide-cm") 的布尔判断恒设为 true
        if '"allow-hide-cm"' in text or 'OPTION_ALLOW_HIDE_CM' in text:
            text = re.sub(
                r'option2bool\(\s*"allow-hide-cm"\s*,\s*&Config::get_option\(\s*"allow-hide-cm"\s*\)\s*\)',
                'true',
                text,
            )
            text = re.sub(
                r'option2bool\(\s*OPTION_ALLOW_HIDE_CM\s*,\s*&Config::get_option\(\s*OPTION_ALLOW_HIDE_CM\s*\)\s*\)',
                'true',
                text,
            )

        if text != orig:
            write_text(rs_file, text)
            print(f"[INFO] 隐藏弹窗 (Rust): 已修改 {rs_file.relative_to(root)}")

    # 2. 修改 Flutter 端 (flutter/lib/desktop/pages/cm_page.dart 等)
    flutter_dir = root / "flutter" / "lib"
    if not flutter_dir.exists():
        return

    for dart_file in flutter_dir.rglob("*.dart"):
        if "cm" not in dart_file.name.lower() and "main" not in dart_file.name.lower():
            continue
        text = read_text(dart_file)
        orig = text

        # 消除 CM 窗口显示的 3 秒延迟 (Timer(const Duration(seconds: 3), () => windowManager.hide()))
        if "windowManager.hide" in text or "hide_cm" in text or "hideCm" in text:
            text = re.sub(
                r'Duration\(\s*seconds\s*:\s*[1-9]\d*\s*\)',
                'Duration(milliseconds: 0)',
                text,
            )
            # 在 cm_page.dart 中，将窗口弹出显示与聚焦直接改为隐藏
            if dart_file.name == "cm_page.dart":
                text = re.sub(
                    r'windowManager\.show\(\)\s*;',
                    'windowManager.hide();',
                    text,
                )
                text = re.sub(
                    r'windowManager\.focus\(\)\s*;',
                    'windowManager.hide();',
                    text,
                )

        if text != orig:
            write_text(dart_file, text)
            print(f"[INFO] 隐藏弹窗 (Flutter): 已修改 {dart_file.relative_to(root)}，移除弹窗显示与等待延迟")


def patch_update_urls(root: Path, target_repo: str, api_server: str) -> None:
    """
    将 RustDesk 的版本检测与自动更新下载地址改为用户自己的 GitHub 仓库 (target_repo = owner/repo)。
    覆盖位置：
      - src/common.rs (check_software_update 版本检测)
      - src/updater.rs (Windows 自动更新下载器)
      - flutter/lib/ 下的关于页面与更新下载链接
    """
    if not target_repo or "/" not in target_repo:
        print(f"[ERROR] 无效的目标仓库名: {target_repo}，格式应为 owner/repo", file=sys.stderr)
        sys.exit(1)

    target_releases_url = f"https://github.com/{target_repo}/releases"
    target_api_releases_url = f"https://api.github.com/repos/{target_repo}/releases"

    search_dirs = [root / "src", root / "libs", root / "flutter" / "lib"]
    patched_files = 0

    for d in search_dirs:
        if not d.exists():
            continue
        for file_path in d.rglob("*"):
            if not file_path.is_file() or file_path.suffix not in (".rs", ".dart"):
                continue
            try:
                text = read_text(file_path)
            except UnicodeDecodeError:
                continue
            orig = text

            # 1. 将官方 GitHub Releases 地址替换为用户的仓库 Releases 地址
            if "github.com/rustdesk/rustdesk/releases" in text:
                text = text.replace(
                    "https://github.com/rustdesk/rustdesk/releases",
                    target_releases_url,
                )
                text = text.replace(
                    "github.com/rustdesk/rustdesk/releases",
                    f"github.com/{target_repo}/releases",
                )

            if "api.github.com/repos/rustdesk/rustdesk/releases" in text:
                text = text.replace(
                    "https://api.github.com/repos/rustdesk/rustdesk/releases",
                    target_api_releases_url,
                )

            # 2. 在 src/common.rs 与 src/updater.rs 中，防止其优先请求官方 api.rustdesk.com/version/latest
            #    导致获取到官方版本号或官方下载链接，强制其走 GitHub Releases 重定向解析
            if file_path.name in ("common.rs", "updater.rs"):
                text = re.sub(
                    r'https://api\.rustdesk\.com/version/latest[^\s"]*',
                    f"{target_releases_url}/latest",
                    text,
                )
                if api_server:
                    text = text.replace("https://admin.rustdesk.com", api_server)

            if text != orig:
                write_text(file_path, text)
                patched_files += 1
                print(f"[INFO] 自动更新地址: 已将 {file_path.relative_to(root)} 指向 {target_repo}")

    print(f"[INFO] 自动更新地址替换完成，共修改 {patched_files} 个文件。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch RustDesk source for silent CM popup & custom GitHub Release auto-update.")
    parser.add_argument(
        "--root",
        default=".",
        help="RustDesk 源码根目录路径 (默认: 当前目录)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="用于自动更新的目标 GitHub 仓库，格式为 owner/repo (默认读取环境变量 GITHUB_REPOSITORY)",
    )
    parser.add_argument(
        "--id-server",
        default=os.environ.get("RENDEZVOUS_SERVER", ""),
        help="可选：内置自建 ID 服务器 (hbbs) 地址",
    )
    parser.add_argument(
        "--relay-server",
        default=os.environ.get("RELAY_SERVER", ""),
        help="可选：内置自建中继服务器 (hbbr) 地址",
    )
    parser.add_argument(
        "--api-server",
        default=os.environ.get("API_SERVER", ""),
        help="可选：内置自建 API 服务器地址",
    )
    parser.add_argument(
        "--pub-key",
        default=os.environ.get("RS_PUB_KEY", ""),
        help="可选：内置自建服务器 Base64 公钥 (Key)",
    )

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if not args.repo:
        print("[ERROR] 请通过 --repo owner/repo 或环境变量 GITHUB_REPOSITORY 指定你的项目仓库地址！", file=sys.stderr)
        sys.exit(1)

    print(f"=== 开始执行 RustDesk 自定义补丁 (目标仓库: {args.repo}) ===")
    patch_config_rs(
        root=root,
        id_server=args.id_server.strip(),
        relay_server=args.relay_server.strip(),
        api_server=args.api_server.strip(),
        pub_key=args.pub_key.strip(),
    )
    patch_hide_cm_popup(root=root)
    patch_update_urls(root=root, target_repo=args.repo.strip(), api_server=args.api_server.strip())
    print("=== RustDesk 补丁执行完毕 ===")


if __name__ == "__main__":
    main()
```
