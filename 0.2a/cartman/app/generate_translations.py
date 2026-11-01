
from pathlib import Path
import copy
import hashlib
import json
import time
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = Path(__file__).resolve().parent
TRANSLATIONS_DIR = BASE_DIR / "static" / "translations"
EN_FILE = TRANSLATIONS_DIR / "en.json"

MAX_WORKERS = 3
MAX_RETRIES = 3
REQUEST_DELAY = 0.1
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
LANGUAGES = {
    "tr": "tr", "de": "de", "fr": "fr", "es": "es",
    "nl": "nl", "pl": "pl", "it": "it", "ja": "ja",
    "pt-BR": "pt", "ar": "ar", "zh-CN": "zh", "ru": "ru",
    "el": "el", "bcs": "bs", "he": "he", "sq": "sq",
    "cs": "cs", "lt": "lt", "sv": "sv", "no": "no",
    "da": "da", "fi": "fi", "az": "az", "id": "id",
    "ms": "ms", "et": "et", "hu": "hu", "ko": "ko",
}

DEFAULT_ENGLISH = {
    "overview": "Overview",
    "welcome": "Welcome back, Kaan",
    "intro": "Manage your endpoints, infrastructure and operations from one place.",
    "environment": "Environment overview",
    "environmentSub": "A quick look at your workspace.",
    "refresh": "↻ Refresh",
    "devices": "Devices",
    "inventory": "Inventory",
    "software": "Software",
    "remote": "Remote Access",
    "monitoring": "Monitoring",
    "ticketing": "Ticketing",
    "knowledge": "Knowledge Base",
    "tasks": "Tasks & Automation",
    "services": "Services",
    "identity": "Identity & Access",
    "policies": "Policies",
    "audit": "Audit Logs",
    "settings": "Settings",
    "terminal": "Terminal",
    "lightMode": "Light mode",
    "darkMode": "Dark mode",
    "switchToDark": "Switch to dark theme",
    "switchToLight": "Switch to light theme",
    "modules": "Management modules",
    "modulesSub": "Explore the Cartman workspace.",
    "searchPlaceholder": "Search modules...",
    "noResults": "No matching modules found.",
    "backHome": "← Back to overview",
    "openTerminal": "Open terminal",
    "currentSession": "Current session",
    "modulePreview": "Module preview",
    "previewDescription": (
        "This module is part of the Cartman roadmap. "
        "Its live backend and device operations have not been implemented yet."
    ),
    "translationLoadError": "Could not load this language. Check its JSON file.",
    "apiChecking": "Checking...",
    "apiOnline": "Online",
    "apiOffline": "Offline",
    "dashboardRefreshed": (
        "Dashboard status refreshed. Displayed dashboard values are sample data."
    ),
    "moduleDescriptions": {
        "Devices": "Manage enrolled Windows, macOS and Linux endpoints.",
        "Inventory": "Review hardware specifications and asset information.",
        "Software": "Review software inventory and deployment workflows.",
        "Remote Access": "Review authorized endpoint remote-access workflows.",
        "Monitoring": "Inspect system health, performance and alerts.",
        "Ticketing": "Review incident and service-request workflows.",
        "Knowledge Base": "Browse troubleshooting guides and support articles.",
        "Tasks & Automation": "Review task and automation workflows.",
        "Services": "Inspect operating system services.",
        "Identity & Access": "Review users, roles and access permissions.",
        "Policies": "Review centralized endpoint policies.",
        "Audit Logs": "Review recorded administrative actions and events.",
        "Settings": "Configure Cartman application preferences."
    },
    "terminalMessages": {
        "title": "Cartman CLI — preview mode",
        "availableCommands": "Available commands:",
        "help": "Show this help",
        "clear": "Clear terminal output",
        "status": "Check the Cartman API",
        "devices": "Show demo inventory status",
        "tickets": "Show demo ticket counts",
        "modules": "List available modules",
        "whoami": "Show demo session",
        "date": "Show local date and time",
        "open": "Open a module",
        "noRemoteCommands": "Remote device commands are not implemented.",
        "user": "Kaan Yaşar · Administrator (demo UI)",
        "openedOverview": "Opened Overview.",
        "opened": "Opened",
        "moduleNotFound": "Module not found. Type 'modules'.",
        "checkingApi": "Checking Cartman API...",
        "apiUnavailable": "API unavailable. Check the backend server.",
        "demoInventory": (
            "Demo inventory: 24 devices, 21 healthy, 2 warning, 1 offline."
        ),
        "sampleData": "These are sample values, not live endpoint data.",
        "demoTickets": (
            "Demo ticket queue: 5 open, 3 in progress, 12 resolved."
        ),
        "ticketingOffline": "Ticketing backend is not connected.",
        "unknownCommand": (
            "Unknown command. Type 'help' for available commands."
        )
    }
}


def read_json(path):
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp_path.replace(path)


def fill_missing(existing, defaults):
    for key, value in defaults.items():
        if key not in existing:
            existing[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(existing[key], dict):
            fill_missing(existing[key], value)


def load_english():
    # İngilizce kaynak dosyasını otomatik değiştirme.
    english = read_json(EN_FILE)
    if english is None:
        raise RuntimeError("en.json eksik veya geçersiz; otomatik oluşturulmadı.")
    return english

def collect_strings(value, result):
    if isinstance(value, dict):
        for child in value.values():
            collect_strings(child, result)
    elif isinstance(value, list):
        for child in value:
            collect_strings(child, result)
    elif isinstance(value, str) and value.strip():
        if value not in result:
            result.append(value)


def build_translation_map(source, existing):
    result = {}

    def walk(src, dst):
        if isinstance(src, dict):
            dst = dst if isinstance(dst, dict) else {}
            for key, value in src.items():
                walk(value, dst.get(key))
        elif isinstance(src, list):
            dst = dst if isinstance(dst, list) else []
            for i, value in enumerate(src):
                walk(value, dst[i] if i < len(dst) else None)
        elif isinstance(src, str) and src.strip():
            if isinstance(dst, str) and dst.strip() and dst != src:
                result[src] = dst

    walk(source, existing or {})
    return result


def apply_translations(source, translated):
    if isinstance(source, dict):
        return {
            key: apply_translations(value, translated)
            for key, value in source.items()
        }
    if isinstance(source, list):
        return [apply_translations(value, translated) for value in source]
    if isinstance(source, str):
        return translated.get(source, source)
    return source


def translate_text(text, target_language):
    global _LAST_REQUEST_AT

    query = urllib.parse.urlencode({
        "q": text,
        "langpair": f"en|{target_language}",
    })
    url = urllib.parse.urlunsplit((
        "https", "api.mymemory.translated.net", "/get", query, ""
    ))
    request = urllib.request.Request(
        url, headers={"User-Agent": "CartmanTranslationTool/1.0"}
    )

    with _REQUEST_LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST_AT
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        _LAST_REQUEST_AT = time.monotonic()

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("responseStatus") != 200:
        raise RuntimeError(
            data.get("responseDetails", "Translation API request failed")
        )

    result = data.get("responseData", {}).get("translatedText")
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError("The API returned an empty translation")
    return result.strip()

def translate_with_retry(original, target):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return translate_text(original, target), None
        except Exception as error:
            if attempt == MAX_RETRIES:
                return None, str(error)

            # Back off after errors instead of hammering the API.
            time.sleep(2 * attempt)

    return None, "Unknown translation error"


def translate_language(language, target, english):
    output_file = TRANSLATIONS_DIR / f"{language}.json"
    progress_dir = BASE_DIR / "translation_progress_clean_v1"
    progress_file = progress_dir / f"{language}.json"
    progress_dir.mkdir(parents=True, exist_ok=True)

    source_hash = hashlib.sha256(
        json.dumps(english, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    saved = read_json(progress_file) or {}
    stored = saved.get("translations", {})
    if saved.get("_source_hash") != source_hash or not isinstance(stored, dict):
        translated = {}
    else:
        translated = stored

    strings = []
    collect_strings(english, strings)
    valid = set(strings)
    translated = {
        key: value for key, value in translated.items()
        if key in valid and isinstance(value, str) and value.strip()
    }
    missing = [item for item in strings if item not in translated]

    def save_progress():
        write_json(progress_file, {
            "_source_hash": source_hash,
            "translations": translated,
        })
        write_json(output_file, apply_translations(english, translated))

    save_progress()
    if not missing:
        return f"{output_file.name}: clean progress is complete."

    print(f"\n[{language}] {len(missing)} strings to translate.")
    failed = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        jobs = {
            pool.submit(translate_with_retry, item, target): item
            for item in missing
        }
        for index, future in enumerate(as_completed(jobs), start=1):
            item = jobs[future]
            result, error = future.result()

            if isinstance(result, str) and result.strip():
                translated[item] = result.strip()
            else:
                failed.append(item)
                print(f"  [{language}] Failed: {item!r} — {error or 'Empty result'}")

            save_progress()
            print(f"  [{language}] {index}/{len(missing)} saved")

    return (
        f"{output_file.name}: {len(missing) - len(failed)} translated, "
        f"{len(failed)} failed; rerun to retry failures."
    )

def main():
    english = load_english()

    print("=" * 55)
    print("CARTMAN TRANSLATION GENERATOR")
    print("=" * 55)
    print(f"Directory: {TRANSLATIONS_DIR}")
    print("Provider: MyMemory")
    print(f"Concurrent requests: {MAX_WORKERS}")
    print("Progress is saved incrementally.")
    print("=" * 55)

    for language, target in LANGUAGES.items():
        try:
            print(f"\nProcessing {language}...")
            print(translate_language(language, target, english))
        except KeyboardInterrupt:
            print("\nStopped. Saved translations are preserved.")
            return
        except Exception as error:
            print(f"[ERROR] {language}: {error}")

    print("\nFinished. Review the generated translations.")


if __name__ == "__main__":
    main()
