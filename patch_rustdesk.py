#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RustDesk Windows (x86_64) Automated Patch Script (patch_rustdesk.py)
Features:
  1. Completely hide the controlled-side Connection Manager (CM) popup window (0ms, never shown on screen)
     WITHOUT breaking the CM process lifecycle or disconnecting the session:
     - Patches Rust `hide_cm()` / `allow-hide-cm` in `libs/hbb_common/src/password_security.rs`.
     - In Flutter `showCmWindow({bool isStartup = false})` (`flutter/lib/main.dart`), keeps the normal window
       initialization (`windowManager.show()`, `setSizeAlignment`, `_isCmReadyToShow = true`) intact so the
       CM IPC session never exits, while changing `windowManager.setOpacity(1)` to `windowManager.setOpacity(0)`
       so the window is 100% transparent (invisible) during the initial 3 seconds as well.
  2. Clean/Pure UI: Remove official "self-host server tip" banner, remove "Account" & "About" tabs in Settings,
     disable Address Book / Accessible Devices / Help Cards by default, and clear official admin API URL.
  3. Rename displayed software name to "本地互联" across Flutter UI, Win32 window title, tray, and Chinese lang pack
     (while keeping internal binary/updater filename compatibility).
  4. Redirect client version check and Windows auto-update URLs to your GitHub repository Releases,
     inject the fork update public key, and require signed rustdesk-update.json sidecars from that repo.
  5. Set a custom Android applicationId (default com.s1oz.bendihulian) and Android display labels.
"""

import argparse
import base64
import os
import re
import sys
from pathlib import Path

# Fork update-metadata signing identity (public half is safe to commit).
DEFAULT_UPDATE_KEY_ID = "s1oz-ed25519-main"
DEFAULT_UPDATE_PUBLIC_KEY_B64 = "OoPZqSuSqAOjCo0qrEw+I6ewTe8ZTfMoQQ1/Hz5srBY="
DEFAULT_APPLICATION_ID = "com.s1oz.bendihulian"

# Force UTF-8 on Windows consoles (avoids cp1252 UnicodeEncodeError on GitHub Actions Windows runners)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def require_existing(path: Path) -> Path:
    if not path.is_file():
        fail(f"required file not found: {path}")
    return path


def replace_required(path: Path, old: str, new: str, label: str, expected: int | None = 1) -> int:
    text = read_text(path)
    count = text.count(old)
    if expected is not None and count != expected:
        fail(f"{label}: expected {expected} occurrence(s) of target in {path}, found {count}")
    if expected is None and count < 1:
        fail(f"{label}: target not found in {path}")
    write_text(path, text.replace(old, new))
    print(f"[INFO] {label}: replaced {count} occurrence(s) in {path.name}")
    return count


def decode_public_key_b64(pub_b64: str) -> bytes:
    pub_b64 = pub_b64.strip()
    try:
        raw = base64.b64decode(pub_b64, validate=True)
    except Exception as exc:
        fail(f"invalid update public key base64: {exc}")
    if len(raw) != 32:
        fail(f"update public key must be 32 bytes, got {len(raw)}")
    if base64.b64encode(raw).decode("ascii") != pub_b64:
        fail("update public key must be canonical base64")
    return raw


def rust_u8_array(data: bytes, indent: str = "        ") -> str:
    parts = [str(b) for b in data]
    lines = [", ".join(parts[i:i + 8]) for i in range(0, len(parts), 8)]
    joiner = "," + "\n" + indent
    return joiner.join(lines)


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
    Hide the Connection Manager (--cm) popup window from 0ms WITHOUT breaking the CM lifecycle:
      1. Force hide_cm() / allow_hide_cm() in Rust (password_security.rs) to return true.
      2. In Flutter `showCmWindow({bool isStartup = false})` (`flutter/lib/main.dart`), DO NOT call
         `windowManager.hide()` and DO NOT zero out `Duration(milliseconds: ...)` or window sizes
         (which causes `--cm` to exit and drops the session with "manually closed").
         Instead, keep `windowManager.show()` intact and simply change `windowManager.setOpacity(1)`
         to `windowManager.setOpacity(0)` inside `showCmWindow`, matching the exact state RustDesk
         uses after the 3-second hide timer.
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

    for dart_file in flutter_dir.rglob("*.dart"):
        try:
            text = read_text(dart_file)
        except UnicodeDecodeError:
            continue
        orig = text

        # Surgical patch on `showCmWindow`: keep `windowManager.show()` and window sizes intact so the CM process
        # stays alive, and only change `setOpacity(1)` -> `setOpacity(0)` so it is 100% transparent from 0ms.
        if "showCmWindow" in text and "_isCmReadyToShow" in text:
            def patch_show_cm_fn(match: re.Match) -> str:
                block = match.group(0)
                # Replace setOpacity(1) with setOpacity(0)
                block = re.sub(
                    r'windowManager\.setOpacity\s*\(\s*1(?:\.0)?\s*\)',
                    'windowManager.setOpacity(0)',
                    block,
                )
                # Replace focus() inside Future.wait with setOpacity(0) so it doesn't steal focus
                block = re.sub(
                    r'windowManager\.show\(\)\s*,\s*windowManager\.focus\(\)',
                    'windowManager.setOpacity(0), windowManager.show()',
                    block,
                )
                # Prevent the `else if (_isCmReadyToShow)` branch from bringing the window back to top
                block = block.replace(
                    "else if (_isCmReadyToShow)",
                    "else if (false && _isCmReadyToShow)",
                )
                return block

            text = re.sub(
                r'(?m)^(?:Future<void>\s+|void\s+)?showCmWindow\s*\([\s\S]*?^\}',
                patch_show_cm_fn,
                text,
            )

        if text != orig:
            write_text(dart_file, text)
            print(f"[INFO] Hide CM Popup (Flutter): Set opacity=0 in showCmWindow in {dart_file.relative_to(root)}")


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

    # 5. Android launcher / accessibility labels (safe no-op if the tree has no Android sources)
    def xml_escape(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    android_name = xml_escape(app_name)
    strings_xml = root / "flutter" / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml"
    if strings_xml.is_file():
        replace_required(
            strings_xml,
            "<string name=\"app_name\">RustDesk</string>",
            f"<string name=\"app_name\">{android_name}</string>",
            "Android strings.xml app_name",
        )
        # Keep accessibility copy readable with the custom display name when it mentions RustDesk.
        text = read_text(strings_xml)
        if "RustDesk" in text:
            write_text(strings_xml, text.replace("RustDesk", android_name))
            print(f"[INFO] App Name: Replaced remaining 'RustDesk' in {strings_xml.relative_to(root)}")

    manifest = root / "flutter" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    if manifest.is_file():
        replace_required(
            manifest,
            '        android:label="RustDesk"',
            f'        android:label="{android_name}"',
            "AndroidManifest application label",
        )
        replace_required(
            manifest,
            '            android:label="RustDesk Input"',
            f'            android:label="{android_name} Input"',
            "AndroidManifest input service label",
        )


def patch_application_id(root: Path, application_id: str) -> None:
    """Change Android applicationId so the APK can be installed beside official RustDesk.

    Only applicationId is changed. The Gradle namespace and Kotlin package stay
    com.carriez.flutter_hbb so R/BuildConfig imports keep compiling.
    """
    application_id = (application_id or "").strip()
    if not application_id:
        return
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+", application_id):
        fail(f"invalid Android applicationId: {application_id}")
    if application_id == "com.carriez.flutter_hbb":
        fail("applicationId must not be the official RustDesk id com.carriez.flutter_hbb")
    gradle = require_existing(root / "flutter" / "android" / "app" / "build.gradle")
    replace_required(
        gradle,
        '        applicationId "com.carriez.flutter_hbb"',
        f'        applicationId "{application_id}"',
        "Android applicationId",
    )


def patch_update_urls(root: Path, target_repo: str, api_server: str) -> None:
    """Redirect RustDesk version check and auto-update download URLs to target_repo (owner/repo)."""
    if not target_repo or "/" not in target_repo:
        fail(f"Invalid target repository: {target_repo} (expected owner/repo)")

    _owner, repo_name = target_repo.split("/", 1)
    if not _owner or not repo_name or "/" in repo_name:
        fail(f"Invalid target repository: {target_repo} (expected owner/repo)")

    target_releases_url = f"https://github.com/{target_repo}/releases"
    target_api_releases_url = f"https://api.github.com/repos/{target_repo}/releases"

    required_url_files = [
        root / "src" / "updater" / "artifact.rs",
        root / "src" / "common.rs",
    ]
    for path in required_url_files:
        require_existing(path)
        text = read_text(path)
        if (
            "https://github.com/rustdesk/rustdesk/releases" not in text
            and "github.com/rustdesk/rustdesk/releases" not in text
        ):
            fail(f"expected official GitHub releases URL not found in {path}")

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

    for path in required_url_files:
        text = read_text(path)
        if f"github.com/{target_repo}/releases" not in text:
            fail(f"failed to redirect official releases URL in {path}")

    print(f"[INFO] Auto-Update URL patching complete ({patched_files} files modified).")


def patch_update_trust_and_version_check(
    root: Path,
    target_repo: str,
    update_key_id: str,
    update_public_key_b64: str,
) -> None:
    """Point version checks, artifact URL allowlists, and trusted update keys at this fork."""
    owner, repo_name = target_repo.split("/", 1)
    pub_raw = decode_public_key_b64(update_public_key_b64)
    pub_array = rust_u8_array(pub_raw)

    # 1. Embedded trusted public key in the client
    metadata_rs = require_existing(root / "src" / "update_metadata.rs")
    metadata = read_text(metadata_rs)
    key_pattern = re.compile(
        r"const TRUSTED_UPDATE_KEYS: &\[TrustedUpdateKey\] = &\[TrustedUpdateKey \{"
        r"\s*key_id: \"[^\"]+\","
        r"\s*algorithm: SIGNATURE_ALGORITHM,"
        r"\s*public_key: \[.*?\],"
        r"\s*\}\];",
        re.S,
    )
    replacement = (
        "const TRUSTED_UPDATE_KEYS: &[TrustedUpdateKey] = &[TrustedUpdateKey {\n"
        f'    key_id: "{update_key_id}",\n'
        "    algorithm: SIGNATURE_ALGORITHM,\n"
        "    public_key: [\n"
        f"        {pub_array},\n"
        "    ],\n"
        "}];"
    )
    metadata, n = key_pattern.subn(replacement, metadata, count=1)
    if n != 1:
        fail(f"TRUSTED_UPDATE_KEYS block not found in {metadata_rs}")
    write_text(metadata_rs, metadata)
    print(f"[INFO] Update trust: injected key_id={update_key_id} into src/update_metadata.rs")

    # 2. Signing script key id (used later in CI to sign rustdesk-update.json)
    gen_script = require_existing(root / "res" / "update" / "generate_update_metadata.py")
    replace_required(
        gen_script,
        'KEY_ID = "2026-ed25519-main"',
        f'KEY_ID = "{update_key_id}"',
        "Update signing KEY_ID",
    )

    # 3. release_id_from_update_url() must accept this fork's tag URLs
    common_rs = require_existing(root / "src" / "common.rs")
    replace_required(
        common_rs,
        '        ["rustdesk", "rustdesk", "releases", "tag", release_id] => *release_id,\n'
        '        ["rustdesk", "rustdesk", "releases", "tag", release_id, ""] => *release_id,',
        f'        ["{owner}", "{repo_name}", "releases", "tag", release_id] => *release_id,\n'
        f'        ["{owner}", "{repo_name}", "releases", "tag", release_id, ""] => *release_id,',
        "release_id_from_update_url path match",
    )

    # 4. Downloaded artifact URLs must be allowlisted for this fork
    artifact_rs = require_existing(root / "src" / "updater" / "artifact.rs")
    replace_required(
        artifact_rs,
        '    if owner != "rustdesk"\n        || repo != "rustdesk"',
        f'    if owner != "{owner}"\n        || repo != "{repo_name}"',
        "get_update_download_file_from_url owner/repo allowlist",
    )

    # 5. Version check: query GitHub Releases API instead of api.rustdesk.com
    hbb_lib = require_existing(root / "libs" / "hbb_common" / "src" / "lib.rs")
    replace_required(
        hbb_lib,
        '    const URL: &str = "https://api.rustdesk.com/version/latest";',
        f'    const URL: &str = "https://api.github.com/repos/{target_repo}/releases/latest";',
        "version_check_request URL",
    )
    helper = (
        "\n"
        "pub fn release_tag_url_from_github_latest(bytes: &[u8]) -> ResultType<String> {\n"
        "    #[derive(Deserialize)]\n"
        "    struct GithubReleaseLatest {\n"
        "        tag_name: String,\n"
        "    }\n"
        "    let rel: GithubReleaseLatest = serde_json::from_slice(bytes)?;\n"
        "    let tag = rel.tag_name.trim();\n"
        "    if tag.is_empty()\n"
        "        || tag == \".\"\n"
        "        || tag == \"..\"\n"
        "        || tag.contains([' ', '/', '\\\\', '?', '#', '%'])\n"
        "    {\n"
        "        bail!(\"invalid GitHub release tag: {}\", rel.tag_name);\n"
        "    }\n"
        f'    Ok(format!("https://github.com/{target_repo}/releases/tag/{{tag}}"))\n'
        "}\n"
        "\n"
    )
    # Insert helper immediately after version_check_request, before time_based_rand
    marker = "pub fn time_based_rand() -> u32 {"
    lib_text = read_text(hbb_lib)
    if "fn release_tag_url_from_github_latest(" in lib_text:
        print("[INFO] Version check: release_tag_url_from_github_latest already present")
    else:
        if marker not in lib_text:
            fail(f"insertion marker not found in {hbb_lib}: {marker}")
        write_text(hbb_lib, lib_text.replace(marker, helper + marker, 1))
        print("[INFO] Version check: added release_tag_url_from_github_latest() in libs/hbb_common/src/lib.rs")

    # 6. do_check_software_update: GET the GitHub API and convert {tag_name} into a tag URL
    replace_required(
        common_rs,
        "    let (request, url) =\n        hbb_common::version_check_request(hbb_common::VER_TYPE_RUSTDESK_CLIENT.to_string());",
        "    let (_request, url) =\n        hbb_common::version_check_request(hbb_common::VER_TYPE_RUSTDESK_CLIENT.to_string());",
        "do_check_software_update unused request binding",
    )
    replace_required(
        common_rs,
        "client.post(&url).json(&request).send().await",
        'client.get(&url).header("User-Agent", "s1oz-rustdesk_patch-update-check").header("Accept", "application/vnd.github+json").send().await',
        "do_check_software_update GitHub GET",
        expected=2,
    )
    replace_required(
        common_rs,
        "    let result = response_bytes.and_then(process_software_update_check_response);",
        "    let result = response_bytes.and_then(|bytes| {\n"
        "        let tag_url = hbb_common::release_tag_url_from_github_latest(&bytes)?;\n"
        "        let payload = serde_json::to_vec(&hbb_common::VersionCheckResponse { url: tag_url })?;\n"
        "        process_software_update_check_response(payload.into())\n"
        "    });",
        "do_check_software_update GitHub response conversion",
    )

def patch_optional_virtual_display_copy(root: Path) -> None:
    """Do not fail the Windows build if dylib_virtual_display.dll is absent from cargo deps."""
    build_py = require_existing(root / "build.py")
    old = (
        "    shutil.copy2('target/release/deps/dylib_virtual_display.dll',\n"
        "                 flutter_build_dir_2)\n"
    )
    new = (
        "    _virtual_display_dll = os.path.join('target', 'release', 'deps', 'dylib_virtual_display.dll')\n"
        "    if os.path.exists(_virtual_display_dll) and os.path.isdir(flutter_build_dir_2):\n"
        "        shutil.copy2(_virtual_display_dll, flutter_build_dir_2)\n"
        "    else:\n"
        "        print(\n"
        "            '[WARN] skip copying dylib_virtual_display.dll '\n"
        "            f'(src exists={os.path.exists(_virtual_display_dll)}, dest dir={flutter_build_dir_2})'\n"
        "        )\n"
    )
    replace_required(build_py, old, new, "optional dylib_virtual_display.dll copy")


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch RustDesk source for silent CM popup, pure UI, custom app name & GitHub Release auto-update.")
    parser.add_argument("--root", default=".", help="RustDesk source root directory")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="Target GitHub repository (owner/repo)")
    parser.add_argument("--app-name", default=os.environ.get("CUSTOM_APP_NAME", "本地互联"), help="Custom displayed software name (default: 本地互联)")
    parser.add_argument("--id-server", default=os.environ.get("RENDEZVOUS_SERVER", ""), help="Optional custom ID server (hbbs)")
    parser.add_argument("--relay-server", default=os.environ.get("RELAY_SERVER", ""), help="Optional custom relay server (hbbr)")
    parser.add_argument("--api-server", default=os.environ.get("API_SERVER", ""), help="Optional custom API server")
    parser.add_argument("--pub-key", default=os.environ.get("RS_PUB_KEY", ""), help="Optional custom server Base64 public key")
    parser.add_argument(
        "--update-key-id",
        default=os.environ.get("RUSTDESK_UPDATE_KEY_ID", DEFAULT_UPDATE_KEY_ID),
        help="Update metadata signature key id",
    )
    parser.add_argument(
        "--update-public-key",
        default=os.environ.get("RUSTDESK_UPDATE_ED25519_PUBLIC_KEY", DEFAULT_UPDATE_PUBLIC_KEY_B64),
        help="Canonical base64 of the 32-byte ed25519 update public key",
    )
    parser.add_argument(
        "--application-id",
        default=os.environ.get("APPLICATION_ID", DEFAULT_APPLICATION_ID),
        help="Android applicationId (default: com.s1oz.bendihulian)",
    )

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if not args.repo:
        print("[ERROR] Please specify --repo owner/repo or set GITHUB_REPOSITORY environment variable!", file=sys.stderr)
        sys.exit(1)

    print(f"=== Starting RustDesk Custom Patch (Target Repo: {args.repo}, App Name: {args.app_name}, Application ID: {args.application_id}) ===")
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
    patch_update_trust_and_version_check(
        root=root,
        target_repo=args.repo.strip(),
        update_key_id=args.update_key_id.strip(),
        update_public_key_b64=args.update_public_key.strip(),
    )
    patch_optional_virtual_display_copy(root=root)
    patch_application_id(root=root, application_id=args.application_id.strip())
    print("=== RustDesk Custom Patch Completed Successfully ===")


if __name__ == "__main__":
    main()
