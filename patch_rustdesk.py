### Gemini Canvas: Patch Rustdesk

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RustDesk Windows (x86_64) Automated Patch Script (patch_rustdesk.py)
Features:
  1. Hide the controlled-side Connection Manager (CM) popup window immediately upon connection.
  2. Redirect client version check and Windows auto-update URLs to your GitHub repository Releases.
  3. Enable Windows auto-update (allow-auto-update=Y) and startup update check (enable-check-update=Y) by default.
  4. Optionally inject custom self-hosted server settings (RENDEZVOUS_SERVER / RS_PUB_KEY / API_SERVER) if set.
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
    """Patch libs/hbb_common/src/config.rs to inject default options for hiding CM popup and enabling auto-update."""
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
            print("[INFO] config.rs: Injected allow-hide-cm=Y and allow-auto-update=Y into Config2::load() (simple form)")
        else:
            pattern_mut = re.compile(r'(let\s+mut\s+config\s*=\s*Config::load_::<Config2>\("2"\);)')
            if pattern_mut.search(content):
                content = pattern_mut.sub(r'\1' + "\n" + config2_inject_block, content, count=1)
                print("[INFO] config.rs: Injected allow-hide-cm=Y and allow-auto-update=Y into Config2::load() (mut form)")

    # 3. Inject default options into LocalConfig::load()
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
            r'\1' + '\n    ("allow-hide-cm", "Y"),\n    ("allow-auto-update", "Y"),',
            content,
            count=1,
        )
        print("[INFO] config.rs: Injected allow-hide-cm=Y and allow-auto-update=Y into DEFAULT_SETTINGS")

    if content != original:
        write_text(config_path, content)


def patch_hide_cm_popup(root: Path) -> None:
    """
    Patch Rust and Flutter Connection Manager (CM) popup logic:
      1. Force hide_cm() / allow_hide_cm() in libs/hbb_common/src/password_security.rs and src/ to return true.
      2. Replace any qualified or unqualified option2bool("allow-hide-cm", ...) call with true.
      3. Remove the multi-second popup delay in Flutter cm_page.dart and hide the CM window immediately.
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
        # Match optional module prefix (e.g. crate::config::option2bool) so we don't produce crate::config::true
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
        if "cm" not in dart_file.name.lower() and "main" not in dart_file.name.lower():
            continue
        try:
            text = read_text(dart_file)
        except UnicodeDecodeError:
            continue
        orig = text

        if "windowManager.hide" in text or "hide_cm" in text or "hideCm" in text:
            text = re.sub(
                r'Duration\(\s*seconds\s*:\s*[1-9]\d*\s*\)',
                'Duration(milliseconds: 0)',
                text,
            )
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
            print(f"[INFO] Hide CM Popup (Flutter): Patched {dart_file.relative_to(root)}")


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
    parser = argparse.ArgumentParser(description="Patch RustDesk source for silent CM popup & custom GitHub Release auto-update.")
    parser.add_argument("--root", default=".", help="RustDesk source root directory")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="Target GitHub repository (owner/repo)")
    parser.add_argument("--id-server", default=os.environ.get("RENDEZVOUS_SERVER", ""), help="Optional custom ID server (hbbs)")
    parser.add_argument("--relay-server", default=os.environ.get("RELAY_SERVER", ""), help="Optional custom relay server (hbbr)")
    parser.add_argument("--api-server", default=os.environ.get("API_SERVER", ""), help="Optional custom API server")
    parser.add_argument("--pub-key", default=os.environ.get("RS_PUB_KEY", ""), help="Optional custom server Base64 public key")

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if not args.repo:
        print("[ERROR] Please specify --repo owner/repo or set GITHUB_REPOSITORY environment variable!", file=sys.stderr)
        sys.exit(1)

    print(f"=== Starting RustDesk Custom Patch (Target Repo: {args.repo}) ===")
    patch_config_rs(
        root=root,
        id_server=args.id_server.strip(),
        relay_server=args.relay_server.strip(),
        api_server=args.api_server.strip(),
        pub_key=args.pub_key.strip(),
    )
    patch_hide_cm_popup(root=root)
    patch_update_urls(root=root, target_repo=args.repo.strip(), api_server=args.api_server.strip())
    print("=== RustDesk Custom Patch Completed Successfully ===")


if __name__ == "__main__":
    main()
```
