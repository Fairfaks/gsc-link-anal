import os
import sys
import time
import glob
import csv
import platform
import datetime as dt
import pandas as pd
from urllib.parse import quote
from playwright.sync_api import sync_playwright

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def default_chrome_path():
    system = platform.system().lower()
    candidates = []
    if 'darwin' in sys.platform or system == 'darwin':
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chrome.app/Contents/MacOS/Google Chrome",
        ]
    elif system == 'windows':
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    else:  # linux
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/snap/bin/chromium",
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return input("❓ Путь к Chrome не найден. Укажи вручную: ").strip()

def suggest_user_data_dir():
    system = platform.system().lower()
    if 'darwin' in sys.platform or system == 'darwin':
        return os.path.expanduser("~/Library/Application Support/Google/Chrome_Playwright")
    elif system == 'windows':
        return os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Chrome_Playwright")
    else:
        return os.path.expanduser("~/.config/google-chrome/Chrome_Playwright")

def cleanup_singleton_lock(user_data_dir: str):
    """Удаляет файл-замок профиля, если остался после падения."""
    lock = os.path.join(user_data_dir, "SingletonLock")
    if os.path.exists(lock):
        try:
            os.remove(lock)
            print("🧹 Удалил SingletonLock в профиле.")
        except Exception as e:
            print(f"⚠️ Не смог удалить SingletonLock: {e}")

def pick_file_interactive(extensions):
    files = [f for ext in extensions for f in glob.glob(f"*{ext}")]
    if not files:
        print(f"❌ В папке нет файлов с расширениями {extensions}. Укажи путь вручную.")
        path = input("Путь к файлу: ").strip()
        if not os.path.exists(path):
            raise SystemExit("Файл не найден.")
        return path
    print("\n📂 Найденные файлы:")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f}")
    idx = int(input(f"Введите номер файла (1–{len(files)}): ").strip())
    return files[idx - 1]

def read_domains(file_path):
    print(f"📖 Загружаю домены из {file_path}...")
    if file_path.lower().endswith(".xlsx"):
        df = pd.read_excel(file_path)
    else:
        # подхват разных разделителей
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            sample = fh.read(4096)
        sep = ";" if sample.count(";") > sample.count(",") else ","
        df = pd.read_csv(file_path, sep=sep)
    # возьмём первый не пустой столбец как список доменов
    col = next((c for c in df.columns if df[c].notna().any()), df.columns[0])
    domains = (
        df[col].astype(str)
        .str.strip()
        .str.replace(r"^https?://", "", regex=True)
        .str.replace(r"/.*$", "", regex=True)
        .replace({"nan": None})
        .dropna()
        .unique()
        .tolist()
    )
    print(f"✅ Найдено доменов: {len(domains)}")
    return domains

def is_logged_in_gsc(page):
    try:
        if page.query_selector("a[aria-label*='Аккаунт'], a[aria-label*='account']"):
            return True
        if page.query_selector("img[alt*='Фото'], img[alt*='avatar']"):
            return True
    except Exception:
        pass
    return False

def ensure_logged_in(page):
    page.goto("https://search.google.com/search-console", timeout=60000)
    page.wait_for_selector("nav, #yDmH0d, [aria-label='Главное меню']", timeout=60000)
    if not is_logged_in_gsc(page):
        print("\n⚠️ В профиле нет активного входа в Google.")
        print("Открылось окно входа — войдите вручную (в нём же).")
        input("После входа нажмите Enter здесь, чтобы продолжить...")
        page.goto("https://search.google.com/search-console", timeout=60000)
        page.wait_for_selector("nav, #yDmH0d, [aria-label='Главное меню']", timeout=60000)
        if not is_logged_in_gsc(page):
            raise SystemExit("❌ Не удалось авторизоваться. Проверь вход в аккаунт.")

def expand_all_in_frames(page, tries=5):
    """Жмёт 'Показать ещё/Show more' внутри всех фреймов и в shadow DOM."""
    for _ in range(tries):
        clicked = False
        for frame in page.frames:
            try:
                did_click = frame.evaluate("""() => {
                    function deepFindAndClick(node) {
                        if (!node) return 0;
                        let cnt = 0;
                        const btns = node.querySelectorAll('button');
                        btns.forEach(b => {
                            const t = (b.innerText || '').trim().toLowerCase();
                            if (['показать ещё','show more','load more'].some(x => t.includes(x))) {
                                if (!b.disabled) { b.click(); cnt++; }
                            }
                        });
                        if (node.shadowRoot) cnt += deepFindAndClick(node.shadowRoot);
                        node.childNodes.forEach(n => { cnt += deepFindAndClick(n); });
                        return cnt;
                    }
                    return deepFindAndClick(document);
                }""")
                if did_click:
                    clicked = True
            except Exception:
                pass
        if not clicked:
            break
        time.sleep(1.2)

def parse_links(page, donor_domain):
    """
    Сбор URL из таблицы 'Страницы, ссылающиеся чаще всего'.
    Работает через рекурсивный обход shadow DOM в каждом frame.
    Фильтрует по домену (включая поддомены).
    """
    all_links = set()

    js_scraper = """(domain) => {
        function endsWithDomain(host, domain) {
            host = (host || '').toLowerCase();
            domain = (domain || '').toLowerCase();
            return host === domain || host.endsWith('.' + domain);
        }
        const found = new Set();
        function take(href) {
            try {
                const u = new URL(href);
                if (endsWithDomain(u.hostname, domain)) found.add(u.href);
            } catch (_) {}
        }
        function walk(node) {
            if (!node) return;
            if (node.querySelectorAll) {
                node.querySelectorAll('a[jsname="KJaPsd"][href^="http"]').forEach(a => take(a.getAttribute('href')));
                node.querySelectorAll('td[data-string-value^="http"]').forEach(td => take(td.getAttribute('data-string-value')));
            }
            if (node.shadowRoot) walk(node.shadowRoot);
            node.childNodes.forEach(walk);
        }
        walk(document);
        return Array.from(found);
    }"""

    time.sleep(2.5)
    for frame in page.frames:
        try:
            links = frame.evaluate(f"({js_scraper})", donor_domain)
            for l in links:
                all_links.add(l)
        except Exception:
            continue

    print(f"   → найдено {len(all_links)} URL в таблице.")
    return list(all_links)

# =========================== ОСНОВНАЯ ЛОГИКА ===========================

def main():
    # 1) входные данные
    domains_file = pick_file_interactive([".csv", ".xlsx"])
    domains = read_domains(domains_file)

    target_page = input("\n🔗 Введи ЦЕЛЕВУЮ страницу (куда ведут ссылки): ").strip()
    if not target_page.startswith("http"):
        raise SystemExit("Нужен полный URL (https://...).")

    site_url = input("🏠 Введи адрес ресурса в GSC (например, https://example.com/): ").strip()
    if not site_url.startswith("http"):
        raise SystemExit("Нужен полный URL (https://...).")

    # Chrome и профиль
    chrome_path = default_chrome_path()
    user_data_dir = input(f"👤 Путь к профилю Chrome [{suggest_user_data_dir()}]: ").strip() \
                    or suggest_user_data_dir()
    os.makedirs(user_data_dir, exist_ok=True)
    cleanup_singleton_lock(user_data_dir)

    # имя файла результатов
    default_out = f"gsc_external_links_{dt.date.today().isoformat()}.csv"
    out_file = input(f"📝 Имя файла результата [{default_out}]: ").strip() or default_out

    print(f"\n🌐 Chrome: {chrome_path}")
    print(f"👤 Профиль: {user_data_dir}")
    print(f"📄 Выгрузка: {out_file}\n")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            executable_path=chrome_path,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                "--disable-popup-blocking",
                "--disable-notifications",
            ],
        )

        page = browser.new_page()

        # 2) проверка логина
        ensure_logged_in(page)
        print("✅ Вход подтверждён — начинаю сбор...\n")

        # 3) цикл по доменам
        for i, domain in enumerate(domains, start=1):
            url = (
                "https://search.google.com/search-console/links/drilldown?"
                f"resource_id={quote(site_url)}&type=EXTERNAL&target={quote(target_page)}&domain={quote(domain)}"
            )
            print(f"[{i}/{len(domains)}] {domain} → {url}")
            try:
                page.goto(url, timeout=60000)
                time.sleep(4)                     # даём дорендериться
                expand_all_in_frames(page)        # если есть «Показать ещё»
                donor_links = parse_links(page, domain)

                print(f"  🔗 Найдено ссылок: {len(donor_links)}")
                for link in donor_links:
                    results.append({
                        "target_page": target_page,
                        "donor_domain": domain,
                        "source_url": link
                    })
            except Exception as e:
                print(f"⚠️ Ошибка для {domain}: {e}")
                continue

        browser.close()

    # 4) сохранить
    if results:
        pd.DataFrame(results).to_csv(out_file, index=False, encoding="utf-8")
        print(f"\n✅ Готово! Сохранено в {out_file}")
    else:
        print("\n⚠️ Ничего не собрано — проверь входные данные или авторизацию в GSC.")

if __name__ == "__main__":
    main()
