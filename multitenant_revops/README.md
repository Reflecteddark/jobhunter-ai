# 🏢 RevOps Platform V16.0 Enterprise Multi-Tenant Architecture

Модуль многотенантности, автоматического провижининга и DWH-моста для масштабирования платформы на десятки и сотни независимых B2B-клиентов.

---

## 🚀 Архитектурная модель: Hub & Spoke Provisioning

Вместо опасного смешивания чужих данных в одной книге или ненадежного `IMPORTRANGE`, платформа V16.0 реализует **Hub-and-Spoke модель**:

```mermaid
flowchart TD
    Master[🏆 Golden Master V16.0\nID: 1QnjrrbpqhYssofchee7G06szWrFvBCcOqGIVokjqdVc]
    Provisioner[⚙️ tenant_provisioner.py\n(Автоматический онбординг)]
    Registry[(📋 tenants_registry.json\nРеестр клиентов)]
    Updater[🚀 batch_updater.py\n(Каскадный OTA-апдейтер формул)]
    DWH[🗄️ ClickHouse / BigQuery\n(Cold Storage Archive)]

    Master -->|Клонирование эталона| Provisioner
    Provisioner -->|Запись ID тенанта + RBAC Lock| Client1[🏢 Клиент: ООО Альфа\nTNT-001]
    Provisioner -->|Запись ID тенанта + RBAC Lock| Client2[🏢 Клиент: АО Бета\nTNT-002]
    Provisioner -->|Запись ID тенанта + RBAC Lock| Client3[🏢 Клиент: Гамма SaaS\nTNT-003]

    Provisioner -->|Регистрация| Registry
    Registry -->|Список инстансов| Updater
    Updater -->|Over-the-Air обновление формул| Client1
    Updater -->|Over-the-Air обновление формул| Client2
    Updater -->|Over-the-Air обновление формул| Client3

    Client1 -->|Сброс закрытых сделок > 90 дней| DWH
    Client2 -->|Сброс закрытых сделок > 90 дней| DWH
```

---

## 🔒 1. Аппаратный RBAC (Hardware Enforcement)

На листе `🗄️ DWH_и_Безопасность` матрица доступа подкреплена **реальными блокировками Google Sheets API (`ProtectedRange`)**:
* Системные листы `calc_engine`, `raw_audit_log`, `changelog` аппаратно заблокированы от редактирования клиентами (`warningOnly = False`).
* Редактировать ядро расчётов может только **Service Account** платформы. Клиент не может случайно повредить формулы NRR, LTV/CAC и когортного анализа.

---

## 🛠️ 2. Утилиты управления тенантами

### 2.1. Автоматический провижининг нового клиента (`tenant_provisioner.py`)
Развертывание защищенного инстанса клиента за 20 секунд:
```bash
python tenant_provisioner.py --name "ООО Новые Технологии" --email "ceo@newtech.ru"
```
Скрипт:
1. Клонирует эталонный **Golden Master V16.0**.
2. Присваивает уникальный `TENANT_ID` (например, `TNT-001`) и имя компании в `⚙️ Настройки!D3:F5`.
3. Накладывает аппаратный RBAC-лок на системные листы.
4. Выдает клиенту права редактора.
5. Регистрирует инстанс в `tenants_registry.json`.

---

### 2.2. Централизованные обновления формул («по воздуху») (`batch_updater.py`)
Решение проблемы «расхождения версий у 30 клиентов»:
```bash
# Проверить статус доступности всех подключенных клиентов
python batch_updater.py --status

# Каскадно обновить формулу во всех 30+ клиентских файлах прямо из Golden Master
python batch_updater.py --sheet "calc_engine" --range "B20:B25"
```
Скрипт считывает эталонную формулу из Golden Master и мгновенно раскатывает её на все клиентские таблицы за 3–5 секунд.

---

### 2.3. Обход лимита 10k строк (`dwh_bridge.py` + `clickhouse_schema.sql`)
Google Sheets не замедляется и не превышает лимиты ячеек благодаря разделению на горячий и холодный слой:
* **Горячий слой (Google Sheets):** Активные сделки в работе воронки (< 2 000 строк). Максимальная скорость отрисовки дашбордов.
* **Холодный слой (ClickHouse DWH):** Закрытые сделки (Won/Lost) старше 90 дней переносятся в ClickHouse через `dwh_bridge.py`:
```bash
python dwh_bridge.py --tenant-id "TNT-001"
```
Схема таблиц ClickHouse находится в [clickhouse_schema.sql](clickhouse_schema.sql).
