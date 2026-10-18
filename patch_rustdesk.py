#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RustDesk Windows (x86_64) Automated Patch Script (patch_rustdesk.py)
Features:
  1. Completely hide the controlled-side Connection Manager (CM) popup window (0ms, never shown on screen).
     - Patches Rust `hide_cm()` / `allow-hide-cm` in `libs/hbb_common/src/password_security.rs`.
     - Patches Flutter `showCmWindow({bool isStartup = false})` in `flutter/lib/main.dart` (the actual function
       that sets opacity=1 and shows the CM window on startup & connection) to keep opacity=0, Size.zero,
       skipTaskbar=true, and hidden from the very first frame.
     - Patches `server_page.dart`, `server_model.dart`, and `consts.dart`.
  2. Clean/Pure UI: Remove official "self-host server tip" banner, remove "Account" & "About" tabs in Settings,
     disable Address Book / Accessible Devices / Help Cards by default, and clear official admin API URL.
  3. Rename displayed software name to "本地互联" across Flutter UI, Win32 window title, tray, and Chinese lang pack
     (while keeping internal binary/updater filename compatibility).
  4. Redirect client version check and Windows auto-update URLs to your GitHub repository Releases.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Force UTF-8 on Windows consoles (avoids cp1252 UnicodeEncodeError on GitHub Actions Windows runners)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def patch_config_rs(root: Path, id_server: str, relay_server: str, api_server: str, pub_key: str) -> None:
    """Patch libs/hbb_common/src/config.rs to inject default options for hiding CM popup, pure UI, and auto-update."""
    config_path = root / "libs" / "hbb_common" / "src" / "config.rs"
    if not config_path.exists():
        print(f"[WARN] File not found: {config_path} (ensure git submodule libs/hbb_common is initialized)", file=sys.stderr)
        return

    content = read_text(config_path)
    original = content

    # 1. Optional: Replace RENDEZVOUS_SERVERS and RS_PUB_KEY if provided via env/args
    if id_server:
        content, n = re.subn(
            r"(pub\s+const\s+RENDEZVOUS_SERVERS\s*:\s*&(?:'static\s+)?\[&(?:'static\s+)?str\]\s*=\s*&\[)[^\]]*(\];)",
            rf'\1"{id_server}"\2',
            content,
            count=1,
        )
        print(f"[INFO] config.rs: Replaced RENDEZVOUS_SERVERS -> {id_server} (matched {n})")

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
        print(f"[INFO] config.rs: Replaced RS_PUB_KEY (matched {n})")

    # 2. Inject default options into Config2::load()
    config2_inject_lines = [
        '        let mut store = false;',
        '        for (k, v) in [',
        '            ("allow-hide-cm", "Y"),',
        '            ("allow-auto-update", "Y"),',
        '            ("enable-udp-punch", "Y"),',
        '            ("enable-ipv6-punch", "Y"),',
        '            ("disable-ab", "Y"),',
        '            ("disable-account", "Y"),',
        '            ("disable-group-panel", "Y"),',
        '            ("hide-help-cards", "Y"),',
        '            ("remove-preset-password-warning", "Y"),',
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

    if 'Config::load_::<Config2>("2")' in content and '"allow-hide-cm", "Y"' not in content:
        pattern_simple = re.compile(
            r'(fn\s+load\s*\(\s*\)\s*->\s*Config2\s*\{\s*)Config::load_::<Config2>\("2"\)\s*(\})'
        )
        if pattern_simple.search(content):
            content = pattern_simple.sub(
                r'\1let mut config = Config::load_::<Config2>("2");' + "\n" + config2_inject_block + "\n        config\n    " + r'\2',
                content,
                count=1,
            )
            print("[INFO] config.rs: Injected default options into Config2::load() (simple form)")
        else:
            pattern_mut = re.compile(r'(let\s+mut\s+config\s*=\s*Config::load_::<Config2>\("2"\);)')
            if pattern_mut.search(content):
                content = pattern_mut.sub(r'\1' + "\n" + config2_inject_block, content, count=1)
                print("[INFO] config.rs: Injected default options into Config2::load() (mut form)")

    # 3. Inject default options into LocalConfig::load()
    local_inject_block = "\n".join([
        '        let mut store_custom = false;',
        '        for (k, v) in [',
        '            ("allow-hide-cm", "Y"),',
        '            ("hide-cm-window", "Y"),',
        '            ("enable-check-update", "Y"),',
        '            ("allow-auto-update", "Y"),',
        '            ("show-scam-warning", "N"),',
        '            ("hide-help-cards", "Y"),',
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
            print("[INFO] config.rs: Injected hide-cm-window=Y and enable-check-update=Y into LocalConfig::load() (simple form)")
        else:
            pattern_local_mut = re.compile(r'(let\s+mut\s+config\s*=\s*Config::load_::<LocalConfig>\("_local"\);)')
            if pattern_local_mut.search(content):
                content = pattern_local_mut.sub(r'\1' + "\n" + local_inject_block, content, count=1)
                print("[INFO] config.rs: Injected hide-cm-window=Y and enable-check-update=Y into LocalConfig::load() (mut form)")

    # 4. Also inject into DEFAULT_SETTINGS if present
    if "DEFAULT_SETTINGS" in content and '"allow-hide-cm"' not in content:
        content = re.sub(
            r'(const\s+DEFAULT_SETTINGS\s*:\s*&\[\(&str,\s*&str\)\]\s*=\s*&\[)',
            r'\1' + '\n    ("allow-hide-cm", "Y"),\n    ("allow-auto-update", "Y"),\n    ("disable-ab", "Y"),\n    ("disable-account", "Y"),\n    ("disable-group-panel", "Y"),\n    ("hide-help-cards", "Y"),',
            content,
            count=1,
        )
        print("[INFO] config.rs: Injected options into DEFAULT_SETTINGS")

    if content != original:
        write_text(config_path, content)


def patch_hide_cm_popup(root: Path) -> None:
    """
    Completely hide the Connection Manager (--cm) popup window on the controlled computer (0ms, never shown):
      1. Force hide_cm() / allow_hide_cm() in Rust (password_security.rs, cm_interface.rs) to always return true.
      2. Patch `showCmWindow({bool isStartup = false})` in `flutter/lib/main.dart` (which is what actually calls
         `windowManager.show()`, `windowManager.setOpacity(1)`, and `windowOnTop(null)` at t=0s before `hideCmWindow`
         fires 3 seconds later!) so that `showCmWindow` sets `opacity = 0`, `Size.zero`, `setSkipTaskbar(true)`,
         and `windowManager.hide()` right from startup.
      3. Shrink `kConnectionManagerWindowSizeClosedChat` / `kConnectionManagerWindowSizeOpenChat` to `Size(0, 0)`.
      4. Patch `server_page.dart` and `server_model.dart` to zero out any delay timers and keep CM hidden.
    """
    rust_candidates = []
    if (root / "src").exists():
        rust_candidates.extend((root / "src").rglob("*.rs"))
    if (root / "libs").exists():
        rust_candidates.extend((root / "libs").rglob("*.rs"))

    for rs_file in rust_candidates:
        try:
            text = read_text(rs_file)
        except UnicodeDecodeError:
            continue
        orig = text

        # Force pub fn hide_cm() -> bool and pub fn allow_hide_cm() -> bool to return true immediately
        text = re.sub(
            r'(pub\s+fn\s+(?:allow_)?hide_cm\s*\([^)]*\)\s*->\s*bool\s*\{)',
            r'\1 #[allow(unreachable_code)] return true;',
            text,
        )
        # Match optional module prefix (e.g. crate::config::option2bool)
        if '"allow-hide-cm"' in text or 'OPTION_ALLOW_HIDE_CM' in text:
            text = re.sub(
                r'(?:[a-zA-Z0-9_]+::)*option2bool\(\s*"allow-hide-cm"\s*,\s*&(?:[a-zA-Z0-9_]+::)*Config::get_option\(\s*"allow-hide-cm"\s*\)\s*\)',
                'true',
                text,
            )
            text = re.sub(
                r'(?:[a-zA-Z0-9_]+::)*option2bool\(\s*(?:[a-zA-Z0-9_]+::)*OPTION_ALLOW_HIDE_CM\s*,\s*&(?:[a-zA-Z0-9_]+::)*Config::get_option\(\s*(?:[a-zA-Z0-9_]+::)*OPTION_ALLOW_HIDE_CM\s*\)\s*\)',
                'true',
                text,
            )

        if text != orig:
            write_text(rs_file, text)
            print(f"[INFO] Hide CM Popup (Rust): Patched {rs_file.relative_to(root)}")

    flutter_dir = root / "flutter" / "lib"
    if not flutter_dir.exists():
        return

    cm_target_files = {"server_page.dart", "server_model.dart", "cm_page.dart"}
    for dart_file in flutter_dir.rglob("*.dart"):
        fname = dart_file.name
        try:
            text = read_text(dart_file)
        except UnicodeDecodeError:
            continue
        orig = text

        # 1. Patch `showCmWindow` wherever it is defined (typically in flutter/lib/main.dart)
        if "showCmWindow" in text and "_isCmReadyToShow" in text:
            # Disable the `else if (_isCmReadyToShow)` branch that re-shows and focuses the CM window on connection
            text = text.replace(
                "else if (_isCmReadyToShow)",
                "else if (false && _isCmReadyToShow)",
            )
            # In the `if (isStartup)` block of `showCmWindow`, replace show/focus/setOpacity(1) inside Future.wait
            text = re.sub(
                r'windowManager\.show\(\)\s*,\s*windowManager\.focus\(\)\s*,\s*windowManager\.setOpacity\(\s*1(?:\.0)?\s*\)',
                'windowManager.hide(), windowManager.setSkipTaskbar(true), windowManager.setOpacity(0)',
                text,
            )
            # Ensure right before `_isCmReadyToShow = true;` we force opacity=0, skipTaskbar=true, and hide()
            text = re.sub(
                r'_isCmReadyToShow\s*=\s*true\s*;',
                'await windowManager.setOpacity(0); await windowManager.setSkipTaskbar(true); await windowManager.hide(); _isCmReadyToShow = true;',
                text,
            )
            # Also patch inside `showCmWindow` function block if any other show/setOpacity(1) remains
            def patch_show_cm_fn(match: re.Match) -> str:
                block = match.group(0)
                block = re.sub(r'windowManager\.show\s*\(\s*\)', 'windowManager.hide()', block)
                block = re.sub(r'windowManager\.focus\s*\(\s*\)', 'windowManager.hide()', block)
                block = re.sub(r'windowManager\.setOpacity\s*\(\s*1(?:\.0)?\s*\)', 'windowManager.setOpacity(0)', block)
                block = re.sub(r'alwaysOnTop\s*:\s*true', 'alwaysOnTop: false', block)
                block = re.sub(r'windowOnTop\s*\(\s*null\s*\)', 'windowManager.hide()', block)
                return block

            text = re.sub(
                r'(?m)^(?:Future<void>\s+|void\s+)?showCmWindow\s*\([\s\S]*?^\}',
                patch_show_cm_fn,
                text,
            )

        # 2. Shrink kConnectionManagerWindowSizeClosedChat & kConnectionManagerWindowSizeOpenChat to Size.zero
        if "kConnectionManagerWindowSize" in text:
            text = re.sub(
                r'(kConnectionManagerWindowSize(?:Closed|Open)Chat\s*=\s*(?:const\s+)?)Size\s*\([^)]*\)',
                r'\1Size(0, 0)',
                text,
            )

        # 3. Patch server_page.dart, server_model.dart, and cm_page.dart
        if fname in cm_target_files:
            # Zero out any multi-second or millisecond delay timers (e.g. Duration(seconds: 3) -> Duration(milliseconds: 0))
            text = re.sub(
                r'Duration\(\s*(?:seconds|milliseconds)\s*:\s*[1-9]\d*\s*\)',
                'Duration(milliseconds: 0)',
                text,
            )
            # Replace windowManager.show() / focus() / setOpacity(1) / windowOnTop(null)
            text = re.sub(r'windowManager\.show\s*\(\s*\)', 'windowManager.hide()', text)
            text = re.sub(r'windowManager\.focus\s*\(\s*\)', 'windowManager.hide()', text)
            text = re.sub(r'windowManager\.setOpacity\s*\(\s*1(?:\.0)?\s*\)', 'windowManager.setOpacity(0)', text)
            text = re.sub(r'windowOnTop\s*\(\s*null\s*\)', 'windowManager.hide()', text)
            # Replace any call `showCmWindow()` in server_page.dart / server_model.dart with `hideCmWindow()`
            text = re.sub(r'\bshowCmWindow\s*\(\s*\)', 'hideCmWindow()', text)
            # Force _hideCm default state to true if present
            text = re.sub(r'bool\s+_hideCm\s*=\s*false\s*;', 'bool _hideCm = true;', text)
            text = re.sub(
                r"bind\.cmGetConfig\(\s*name\s*:\s*['\"]hide_cm['\"]\s*\)\s*==\s*['\"]true['\"]",
                'true',
                text,
            )

        if text != orig:
            write_text(dart_file, text)
            print(f"[INFO] Hide CM Popup (Flutter): Patched {dart_file.relative_to(root)}")


def patch_clean_ui(root: Path, api_server: str) -> None:
    """
    Pure / De-branded UI customization:
      1. Hide the bottom "If you need faster connection speed, you can choose to self-host server" banner
         in flutter/lib/desktop/pages/connection_page.dart (only inside boolean `&& _svcIsUsingPublicServer.value`
         check, never on left-hand side of `=`).
      2. Remove "Account" and "About" tabs from Settings in flutter/lib/desktop/pages/desktop_setting_page.dart.
      3. Clear official https://admin.rustdesk.com API URL in src/common.rs if no custom API_SERVER is set.
    """
    # 1. Hide bottom setup_server_tip banner in connection_page.dart
    conn_page = root / "flutter" / "lib" / "desktop" / "pages" / "connection_page.dart"
    if conn_page.exists():
        text = read_text(conn_page)
        orig = text
        # Only replace `_svcIsUsingPublicServer.value` when preceded by `&&` and NOT followed by `=`
        text = re.sub(
            r'&&\s*_svcIsUsingPublicServer\.value\b(?!\s*=)',
            '&& false',
            text,
        )
        text = text.replace("translate('setup_server_tip')", "''")
        if text != orig:
            write_text(conn_page, text)
            print("[INFO] Clean UI: Hidden bottom self-host server tip banner in connection_page.dart")

    # 2. Remove Account & About tabs in desktop_setting_page.dart
    setting_page = root / "flutter" / "lib" / "desktop" / "pages" / "desktop_setting_page.dart"
    if setting_page.exists():
        text = read_text(setting_page)
        orig = text
        text = re.sub(
            r'if\s*\(\s*!bind\.isDisableAccount\(\)\s*\)\s*SettingsTabKey\.account\s*,',
            '// SettingsTabKey.account removed',
            text,
        )
        text = re.sub(
            r'(?m)^\s*SettingsTabKey\.about\s*,',
            '    // SettingsTabKey.about removed',
            text,
        )
        if text != orig:
            write_text(setting_page, text)
            print("[INFO] Clean UI: Removed 'Account' and 'About' tabs in desktop_setting_page.dart")

    # 3. Clear official https://admin.rustdesk.com in src/common.rs when no custom api_server is provided
    common_rs = root / "src" / "common.rs"
    if common_rs.exists() and not api_server:
        text = read_text(common_rs)
        orig = text
        text = text.replace('"https://admin.rustdesk.com"', '""')
        if text != orig:
            write_text(common_rs, text)
            print("[INFO] Clean UI: Cleared official https://admin.rustdesk.com in src/common.rs")


def patch_app_name(root: Path, app_name: str) -> None:
    """
    Rename displayed software name (e.g. '本地互联') across Flutter UI, Win32 window title, tray, and lang files,
    while keeping internal binary/service/updater identifier 'RustDesk' intact so portable packing & auto-update work.
    """
    if not app_name:
        return

    # 1. Patch main_get_app_name() in src/flutter_ffi.rs so Flutter UI & window titlebar display app_name
    ffi_rs = root / "src" / "flutter_ffi.rs"
    if ffi_rs.exists():
        text = read_text(ffi_rs)
        orig = text
        text, n = re.subn(
            r'(pub\s+fn\s+main_get_app_name\s*\([^)]*\)\s*->\s*SyncReturn<String>\s*\{)[\s\S]*?(\n\})',
            rf'\1\n    SyncReturn("{app_name}".to_owned())\2',
            text,
            count=1,
        )
        if text != orig:
            write_text(ffi_rs, text)
            print(f"[INFO] App Name: Patched main_get_app_name() in src/flutter_ffi.rs -> {app_name} (matched {n})")

    # 2. Patch Win32 initial window title in flutter/windows/runner/main.cpp using UTF-16 escape sequences
    main_cpp = root / "flutter" / "windows" / "runner" / "main.cpp"
    if main_cpp.exists():
        text = read_text(main_cpp)
        orig = text
        utf16_escaped = "".join(f"\\u{ord(c):04x}" if ord(c) > 127 else c for c in app_name)
        text = text.replace('L"RustDesk"', f'L"{utf16_escaped}"')
        if text != orig:
            write_text(main_cpp, text)
            print(f"[INFO] App Name: Patched Win32 window title in flutter/windows/runner/main.cpp -> {app_name}")

    # 3. Patch system tray tooltip in src/tray.rs
    tray_rs = root / "src" / "tray.rs"
    if tray_rs.exists():
        text = read_text(tray_rs)
        orig = text
        text = text.replace("crate::get_app_name()", f'"{app_name}"')
        if text != orig:
            write_text(tray_rs, text)
            print(f"[INFO] App Name: Patched tray tooltip in src/tray.rs -> {app_name}")

    # 4. Patch Chinese localization files (src/lang/cn.rs, src/lang/tw.rs) to replace "RustDesk" with app_name in values
    for lang_file in [root / "src" / "lang" / "cn.rs", root / "src" / "lang" / "tw.rs"]:
        if not lang_file.exists():
            continue
        text = read_text(lang_file)
        orig = text

        # Clear setup_server_tip text
        text = re.sub(
            r'\(\s*"setup_server_tip"\s*,\s*"[^"]*"\s*\)',
            '("setup_server_tip", "")',
            text,
        )
        # Replace "RustDesk" with app_name only in the second element (translation value) of tuple ("key", "value")
        def replace_val(match: re.Match) -> str:
            prefix = match.group(1)
            val = match.group(2).replace("RustDesk", app_name)
            suffix = match.group(3)
            return f"{prefix}{val}{suffix}"

        text = re.sub(
            r'(\(\s*"[^"]*"\s*,\s*")([^"]*RustDesk[^"]*)("\s*\))',
            replace_val,
            text,
        )
        if text != orig:
            write_text(lang_file, text)
            print(f"[INFO] App Name & Clean UI: Replaced 'RustDesk' -> '{app_name}' in {lang_file.relative_to(root)}")


def patch_update_urls(root: Path, target_repo: str, api_server: str) -> None:
    """Redirect RustDesk version check and auto-update download URLs to target_repo (owner/repo)."""
    if not target_repo or "/" not in target_repo:
        print(f"[ERROR] Invalid target repository: {target_repo} (expected owner/repo)", file=sys.stderr)
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
                print(f"[INFO] Auto-Update URL: Redirected {file_path.relative_to(root)} -> {target_repo}")

    print(f"[INFO] Auto-Update URL patching complete ({patched_files} files modified).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch RustDesk source for silent CM popup, pure UI, custom app name & GitHub Release auto-update.")
    parser.add_argument("--root", default=".", help="RustDesk source root directory")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="Target GitHub repository (owner/repo)")
    parser.add_argument("--app-name", default=os.environ.get("CUSTOM_APP_NAME", "本地互联"), help="Custom displayed software name (default: 本地互联)")
    parser.add_argument("--id-server", default=os.environ.get("RENDEZVOUS_SERVER", ""), help="Optional custom ID server (hbbs)")
    parser.add_argument("--relay-server", default=os.environ.get("RELAY_SERVER", ""), help="Optional custom relay server (hbbr)")
    parser.add_argument("--api-server", default=os.environ.get("API_SERVER", ""), help="Optional custom API server")
    parser.add_argument("--pub-key", default=os.environ.get("RS_PUB_KEY", ""), help="Optional custom server Base64 public key")

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if not args.repo:
        print("[ERROR] Please specify --repo owner/repo or set GITHUB_REPOSITORY environment variable!", file=sys.stderr)
        sys.exit(1)

    print(f"=== Starting RustDesk Custom Patch (Target Repo: {args.repo}, App Name: {args.app_name}) ===")
    patch_config_rs(
        root=root,
        id_server=args.id_server.strip(),
        relay_server=args.relay_server.strip(),
        api_server=args.api_server.strip(),
        pub_key=args.pub_key.strip(),
    )
    patch_hide_cm_popup(root=root)
    patch_clean_ui(root=root, api_server=args.api_server.strip())
    patch_app_name(root=root, app_name=args.app_name.strip())
    patch_update_urls(root=root, target_repo=args.repo.strip(), api_server=args.api_server.strip())
    print("=== RustDesk Custom Patch Completed Successfully ===")


if __name__ == "__main__":
    main()
