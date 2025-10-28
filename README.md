# GSC Link Scraper

Утилита для выгрузки **реальных страниц-доноров** из Google Search Console для заданной целевой страницы.
Скрипт открывает GSC в реальном Chrome (через Playwright), переходит в раздел ссылок по каждому домену, автоматически нажимает **«Показать ещё»** и собирает **точные URL** страниц, где стоит ссылка на ваш URL. Поддерживаются **iframe** и **shadow DOM**.

---

## Что решает

* Даёт **не домены**, а **конкретные страницы-доноры** из GSC.
* Ускоряет аудит: быстро найти мусор/спам-страницы, подготовить выборку для краулинга/фильтрации.
* Масштабируется на сотни доменов без ручных кликов в интерфейсе GSC.

---

## Возможности

* Интерактивный запуск (без жёстких путей): выбор файла доменов (CSV/XLSX), целевого URL, ресурса в GSC, профиля Chrome.
* Поддержка поддоменов (`hostname.endsWith(domain)`).
* Автоклик по **«Показать ещё»**, корректная работа с динамическим UI GSC.
* Рекурсивный обход **shadow DOM** и всех **iframe** — устойчиво к верстке GSC.

---

## Входные данные

* **Целевая страница** (полный URL, на которую ссылаются), например:
  `https://example.com/receive-money/dengi-na-kartu/`
* **Ресурс в GSC** (корень сайта), например:
  `https://example.com/`
* **Список доменов** (CSV или XLSX, используется **первый столбец**), например:

  ```
  vimeo.com
  ozz.tv
  example.com
  ```

---

## Результат (CSV)

Колонки:

* `target_page` — целевая страница;
* `donor_domain` — домен из входного списка;
* `source_url` — реальная страница-донор из GSC.

Пример:

```csv
target_page,donor_domain,source_url
https://example.com/page/,vimeo.com,https://vimeo.com/11580492
https://example.com/page/,ozz.tv,http://forum.ozz.tv/memberlist.php?start=11375
```

---

## Быстрый старт

```bash
# 1) виртуальное окружение
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# 2) зависимости
pip install playwright pandas openpyxl

# 3) движок браузера для Playwright
python -m playwright install

# 4) запуск
python gsc_backlinks_anal.py
```

Скрипт спросит:

1. файл доменов;
2. целевой URL;
3. ресурс GSC (например, `https://example.com/`);
4. путь к Chrome и путь к профилю;
5. имя файла результата (`gsc_external_links_YYYY-MM-DD.csv` по умолчанию).

---

## Рекомендуется: копия профиля Chrome

Чтобы не конфликтовать с основным профилем, сделайте копию и войдите в Google **в окне, которое откроет скрипт**.

**macOS**

```bash
cp -R "$HOME/Library/Application Support/Google/Chrome/Default" \
      "$HOME/Library/Application Support/Google/Chrome_Playwright"
```

**Windows**

```powershell
xcopy "$env:LOCALAPPDATA\Google\Chrome\User Data\Default" `
      "$env:LOCALAPPDATA\Google\Chrome\User Data\Chrome_Playwright" /E /I
```

**Linux**

```bash
cp -R ~/.config/google-chrome/Default ~/.config/google-chrome/Chrome_Playwright
```

---

## Как это работает (кратко)

1. Запускает **Chrome** в persistent-режиме с указанным профилем.
2. Для каждого домена формирует прямой **drilldown-URL** раздела ссылок в GSC:

   ```
   https://search.google.com/search-console/links/drilldown?
   resource_id=<сайт>&type=EXTERNAL&target=<целевой>&domain=<домен>
   ```
3. Дожидается рендера, кликает **«Показать ещё»**, обходит **shadow DOM**/**iframe**.
4. Извлекает все ссылки из таблицы, фильтруя по домену (включая поддомены).
5. Сохраняет результат в CSV.

---

## Частые проблемы

* **Profile is already in use / SingletonLock**
  Закройте Chrome и удалите файл `SingletonLock` в папке копии профиля:

  * macOS: `~/Library/Application Support/Google/Chrome_Playwright/SingletonLock`
  * Windows: `%LOCALAPPDATA%\Google\Chrome\User Data\Chrome_Playwright\SingletonLock`
  * Linux: `~/.config/google-chrome/Chrome_Playwright/SingletonLock`

* **Просит войти в Google**
  Первый запуск в копии профиля: войдите в аккаунт в открывшемся окне, затем вернитесь в консоль и продолжайте.

* **Пустой результат**
  Увеличьте задержки ожидания (`time.sleep(4–6)`), проверьте доступ к сайту в GSC и наличие данных по ссылкам.

---

## Ограничения

* Нужен доступ к сайту в вашем аккаунте **Google Search Console**.
* Требуется установленный **Google Chrome**.
* Скорость зависит от отклика GSC и сети.

---

## Лицензия

MIT.
