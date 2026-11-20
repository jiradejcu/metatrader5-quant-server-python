# Architecture — MT5 Quant Server

เอกสารนี้อธิบายว่าระบบมี component อะไรบ้าง ใครคุยกับใคร เข้าทางไหนได้บ้าง และเส้นไหนมี/ไม่มี authentication

ข้อมูลทั้งหมดอ้างอิงจาก `docker-compose.yml` และโค้ดใน `backend/` ณ วันที่ 2026-09-17
สถานะ auth ที่ระบุคือ **สิ่งที่ config กำหนดไว้** ยังไม่ได้รวมชั้นป้องกันภายนอก (WAF / firewall / Cloudflare) ที่อาจมีอยู่บน prod

---

## 1. ภาพรวม

ระบบมี **18 service** แบ่งเป็น 2 กลุ่มตาม compose profile

| กลุ่ม | จำนวน | service |
|---|---|---|
| **แกนหลัก** (ขึ้นเสมอ) | 6 | `traefik`, `mt5`, `django`, `control-api`, `postgres`, `redis` |
| **เสริม** (ต้องระบุ profile) | 12 | `frontend` (admin) · `celery`, `celery-beat` (worker) · `grafana`, `prometheus`, `cadvisor`, `node-exporter`, `alertmanager`, `uncomplicated-alert-receiver`, `loki`, `promtail` (monitor) · `n8n` (automation) |

คำสั่ง `docker compose up` เฉย ๆ จะได้แค่ 6 ตัวแรก ต้อง `--profile worker --profile monitor` ถึงจะได้ตัวที่เหลือ

---

## 2. แผนผัง

```
                            INTERNET
                                │
                                │ :80 → redirect → :443
                                ▼
                  ┌──────────────────────────────┐
                  │   traefik  (reverse proxy)   │  ← เปิดพอร์ตออก host ตัวเดียว
                  │   publish 80:80, 443:443     │
                  └──────────────┬───────────────┘
                                 │ แยกตาม Host: header
        ┌────────────┬───────────┼───────────┬────────────┬──────────┐
        ▼            ▼           ▼           ▼            ▼          ▼
    mt5-api      mt5-vnc    mt5-django  arbitrage-   arbitrage-   mt5-grafana
    :5001        :3000        :8000     monitor:80   control:7777   mt5-n8n
   ✗ NO AUTH   ~ VNC pwd    ~ ผสม      (frontend)   ✗ NO AUTH    ✗ anon admin
        │                       │                        │
        │  network: traefik-public (ออกเน็ต)             │
   ─────┼───────────────────────┼────────────────────────┼──────────────
        │  network: default (ภายในล้วน)                  │
        │                       │                        │
        ▼                       ▼                        │
   ┌─────────┐   http://mt5:5001    ┌──────────┐         │
   │   mt5   │◄─────────────────────│  django  │◄────────┘
   │ (Wine)  │                      │  (quant) │  http (ผ่านเน็ต — ดูข้อ 6)
   └────┬────┘                      └────┬─────┘
        │                                │
        ▼                          ┌─────┴─────┐
   MetaTrader5                     ▼           ▼
   terminal → broker          postgres      redis
                                              ▲
                                              │
                                      celery / celery-beat
```

---

## 3. ใครเป็น reverse proxy

**`traefik`** (image `traefik:3.0`) เป็น edge router ตัวเดียวของระบบ และเป็น **container เดียวที่ควรเปิดพอร์ตออก host** (`80:80`, `443:443`)

หน้าที่:

1. **รวมทางเข้า** — service อื่นไม่ต้อง publish port ออก host เลย
2. **แยกปลายทางด้วย `Host:` header** — IP เดียวพอร์ต 443 เดียว รองรับ 7 โดเมน
3. **ออกใบรับรอง TLS อัตโนมัติ** — Let's Encrypt ACME tlsChallenge เก็บใน volume `traefik-public-certificates`
4. **Service discovery จาก Docker socket** — mount `/var/run/docker.sock:ro` แล้วอ่าน label ของแต่ละ container สด ๆ ไม่มีไฟล์ config กลาง

### network มีสองวง — จุดที่สับสนบ่อยที่สุด

| network | ความหมาย | สมาชิก |
|---|---|---|
| `traefik-public` (external) | **"ตัวนี้ออกอินเทอร์เน็ต"** | traefik, mt5, django, control-api, frontend, grafana, n8n |
| `default` (bridge) | ภายในล้วน เข้าจากนอกไม่ได้ | postgres, redis, celery, celery-beat, prometheus, loki, ... |

> ⚠️ **`docker ps` ไม่โชว์พอร์ตของ service ที่อยู่หลัง Traefik** เพราะไม่ได้ publish ออก host — Traefik เข้าถึงผ่าน docker network โดยตรง
> การที่ `docker ps` ไม่เห็น `5001` **ไม่ได้แปลว่า MT5 API ปิด** ต้องทดสอบด้วย `curl` จากเครื่องนอกเท่านั้น

> ⚠️ `EXPOSE` ใน Dockerfile เป็น metadata เชิงเอกสาร ไม่เปิดพอร์ตจริง

---

## 4. แต่ละ component ให้บริการอะไร

### แกนหลัก

#### `traefik` — reverse proxy + TLS
ดูข้อ 3 · dashboard ที่ `mt5-traefik.vatanutanon.me` (มี basic auth)

#### `mt5` — driver ครอบ MetaTrader5 terminal
`backend/mt5` · Flask · พอร์ต 5001 · image KasmVNC + Wine (lib `MetaTrader5` รันได้เฉพาะ Windows)

**เป็น service เดียวที่คุยกับ broker ได้** ไม่มี business logic ไม่มี DB แปลง HTTP → `mt5.order_send()` ตรง ๆ

| กลุ่ม | endpoint |
|---|---|
| Health | `GET /health`, `GET /account_info` |
| Symbol | `GET /symbol_info_tick/<symbol>`, `GET /symbol_info/<symbol>` |
| Market data | `GET /fetch_data_pos`, `GET /fetch_data_range` |
| **Order** | `POST /order` |
| **Position** | `POST /close_position`, `POST /close_all_positions`, `POST /modify_sl_tp`, `GET /get_positions`, `GET /positions_total` |
| History | `GET /get_deal_from_ticket`, `GET /get_order_from_ticket`, `GET /history_deals_get`, `GET /history_orders_get` |
| **Fund** | `GET /account_balance`, `POST /withdraw` |
| Error | `GET /last_error`, `GET /last_error_str` |
| Docs | `GET /apidocs/` (Swagger UI), `GET /apispec_1.json` |

กลไกภายใน ([`app/state.py`](../backend/mt5/app/state.py)):
- background thread poll ทุก **0.5 วินาที** เก็บ position + tick ลง in-memory cache
- symbol ถูก register ตอนเรียก `/symbol_info_tick` ครั้งแรก → **ครั้งแรกได้ 404 เสมอ** ต้องยิงซ้ำ
- `mt5_lock` serialise ทุก MT5 call · order route รอสูงสุด 15 วินาที ไม่ได้ก็คืน `503`
- watchdog `os._exit(1)` ถ้า poll ค้างเกิน 30 วินาที แล้วให้ `restart: unless-stopped` พากลับมา

> 📌 `type` ใน `POST /order` ต้องเป็น **ตัวเลข `0` (BUY) / `1` (SELL)** ไม่ใช่ string
> Swagger เขียน `enum: [BUY, SELL]` ไว้ผิด — โค้ดเทียบกับ `mt5.ORDER_TYPE_BUY` ตรง ๆ
> `volume` หน่วยเป็น **lot** ไม่ใช่ USD — เช็ค `volume_min`/`volume_step` จาก `/symbol_info/<symbol>` ก่อน

#### `django` — สมองของระบบ
`backend/django` · พอร์ต 8000 · ต่อ postgres + redis

เป็นเจ้าของ business logic ทั้งหมด **ไม่มีทางคุยกับ MT5 ตรง ๆ ต้องผ่าน HTTP ไปหา `mt5` เสมอ**

REST endpoint:

| path | ให้บริการ |
|---|---|
| `/v1/trades/`, `/v1/trades/<pk>/` | อ่าน trade history (read-only, filter + pagination) |
| `/v1/send_market_order/` | ยิง market order แล้วบันทึกลง DB |
| `/v1/modify_sl_tp/` | แก้ SL/TP |
| `/v1/price_alert/` | รับ price alert เข้า celery task |
| `/displays/`, `/displays/summary/`, `/displays/pause/` | หน้า health check + สรุป arbitrage |
| `/admin/` | Django admin |

**background loop 7 ตัวที่สตาร์ตตอน boot** ([`quant/apps.py`](../backend/django/app/quant/apps.py)) — ตัวนี้คือหัวใจ ไม่ได้รอให้คนมากดเรียก:
`subscribe` · `position_sync` · `net_position` · `price_diff` · `grid_bot` · `prediction_bot` · `health_monitor`

client ที่คุยกับ mt5 อยู่ใน [`app/utils/api/`](../backend/django/app/utils/api/) 5 ไฟล์ (`data`, `order`, `positions`, `ticket`, `error`) ถูก import ต่อไปยังโมดูล quant 12+ จุด

นอกจาก MT5 ยังมี connector ไปยัง exchange อื่นใน [`app/connectors/`](../backend/django/app/connectors/) (binance, bybit) — พวกนี้เป็น **outbound client** ไม่ใช่ API ที่เรียกเข้ามาได้

#### `control-api` — แผงควบคุมสำหรับ frontend
`backend/control-api` · Flask · พอร์ต 7777 · mount docker socket **แบบเขียนได้**

| endpoint | ให้บริการ |
|---|---|
| `GET /get-django-status`, `GET /user-info`, `GET /get-arbitrage-summary` | สถานะระบบ + ข้อมูลบัญชี |
| `GET /prediction-settings`, `GET`/`POST /trading-sessions` | อ่าน/ตั้งค่า |
| `POST /stop-quant`, `/pause-position-sync` | หยุด/พักกลยุทธ์ |
| `POST /toggle-grid-bot`, `/toggle-prediction-bot`, `/set-grid-channel`, `/set-prediction-channel` | เปิดปิดและตั้งค่า bot |
| `POST /restart` | **restart container ตามชื่อที่ส่งมาใน body** |
| `GET /stream/quants` | SSE stream (ไม่ใช่ REST ปกติ) |

#### `postgres` — PostgreSQL 15 · เก็บ trade, mutation, config · `default` เท่านั้น · bind `127.0.0.1:5432` (เข้าจากนอกไม่ได้)

#### `redis` — Redis 6 · celery broker + shared state ระหว่าง django/control-api · `default` เท่านั้น

### เสริม

| service | profile | ให้บริการ |
|---|---|---|
| `frontend` | `admin` | Web UI เรียก control-api |
| `celery` / `celery-beat` | `worker` | async task / scheduler |
| `grafana` | `monitor` | dashboard (metrics + logs) |
| `prometheus` + `cadvisor` + `node-exporter` | `monitor` | เก็บ metrics |
| `loki` + `promtail` | `monitor` | เก็บ log |
| `alertmanager` + `uncomplicated-alert-receiver` | `monitor` | แจ้งเตือน |
| `n8n` | `automation` | workflow automation |

---

## 5. เส้นไหนมี auth เส้นไหนไม่มี

### เส้นทางจากอินเทอร์เน็ต

| โดเมน | → | auth | สถานะ |
|---|---|---|---|
| `mt5-traefik.vatanutanon.me` | traefik dashboard | **HTTP Basic Auth** (`admin-auth`) | 🟢 |
| `mt5-vnc.vatanutanon.me` | mt5:3000 | password ของ KasmVNC (env `PASSWORD`) | 🟡 ไม่มี middleware ที่ Traefik |
| `mt5-django.vatanutanon.me` | django:8000 | **ผสม — ดูตารางถัดไป** | 🟡 |
| `arbitrage-monitor.vatanutanon.me` | frontend:80 | ไม่มี (เป็น static UI) | 🟡 |
| **`mt5-api.vatanutanon.me`** | **mt5:5001** | **ไม่มีเลย** | 🔴 **ยืนยันแล้วว่าตอบ 200** |
| **`arbitrage-control.vatanutanon.me`** | **control-api:7777** | **ไม่มีเลย** | 🔴 |
| `mt5-grafana.vatanutanon.me` | grafana:3000 | `GF_AUTH_ANONYMOUS_ENABLED=true` + `ORG_ROLE=Admin` | 🔴 (เฉพาะเมื่อเปิด profile `monitor`) |
| `mt5-n8n.vatanutanon.me` | n8n:5678 | ไม่พบตัวแปร basic auth ใน `.env` | 🔴 (เฉพาะเมื่อเปิด profile `automation`) |

middleware ที่ Traefik มีให้ใช้คือ `https-redirect` (แค่ redirect ไม่ใช่ auth) และ `admin-auth` (basic auth จริง แต่ผูกกับ dashboard ตัวเดียว)

### รายละเอียดฝั่ง Django

`REST_FRAMEWORK` ใน `settings.py` **ไม่ได้ตั้ง `DEFAULT_PERMISSION_CLASSES`** → default ของ DRF คือ `AllowAny`

| endpoint | auth |
|---|---|
| `POST /v1/send_market_order/` | 🟢 `IsAuthenticated` |
| `POST /v1/modify_sl_tp/` | 🟢 `IsAuthenticated` |
| `GET /v1/trades/` | 🔴 AllowAny — trade history เปิดอ่านสาธารณะ |
| `POST /v1/price_alert/` | 🔴 AllowAny |
| `GET /displays/`, `/displays/summary/` | 🔴 AllowAny |
| `POST /displays/pause/` | 🔴 AllowAny |
| `/admin/` | 🟢 Django session login |

> ⚠️ `settings.py:31` ตั้ง `DEBUG = True` — เมื่อเกิด error Django จะคืนหน้า traceback ที่เผย settings และ env

### เส้นทางภายใน (container-to-container)

| เส้น | network | auth |
|---|---|---|
| `django` → `mt5:5001` | `default` | ไม่มี (ยอมรับได้ ไม่ออกเน็ต) |
| `django` → `postgres` / `redis` | `default` | password |
| `celery` → `redis` | `default` | password |

> 🔵 **CORS ≠ authentication** — `control-api` จำกัด CORS ไว้ที่ origin ของ frontend แต่ CORS เป็นกฎที่ *เบราว์เซอร์* บังคับ `curl` หรือ script ข้ามได้ทันที

---

## 6. ข้อสังเกตสำคัญสำหรับการแก้

**`control-api` เป็นตัวเดียวที่เรียก mt5 ผ่านโดเมนสาธารณะ**

[`routes/control.py:14,137`](../backend/control-api/app/routes/control.py#L137) ใช้ `os.getenv('API_DOMAIN')` แล้วยิง `https://mt5-api.vatanutanon.me/account_info` ทั้งที่ตัวเองอยู่บน network `default` ร่วมกับ `mt5` อยู่แล้ว — คือวิ่งอ้อมออกเน็ตแล้วกลับเข้ามาโดยไม่จำเป็น

ส่วน `django` ใช้ `MT5_API_URL=http://mt5:5001` ซึ่งเป็น internal DNS ถูกต้องอยู่แล้ว

**ผลที่ตามมา:** การถอด `traefik.enable` + router labels ของ `api-mt5` ออกจาก compose จะกระทบแค่ **endpoint เดียว** และแก้ได้ด้วยการเปลี่ยน `control.py:14` ให้ใช้ `http://mt5:5001` แบบเดียวกับ django

หลังจากนั้น `POST /withdraw`, `POST /order`, `POST /close_all_positions` จะเข้าถึงได้จากใน docker network เท่านั้น โดย **ไม่กระทบ arbitrage loop ทั้ง 7 ตัวที่รันอยู่**

### สรุปความเสี่ยงเรียงตามความรุนแรง

| # | ปัญหา | ผลกระทบ |
|---|---|---|
| 1 | `mt5-api` เปิดสาธารณะไม่มี auth | ถอนเงิน (`/withdraw`), ล้างพอร์ต (`/close_all_positions`), ยิง order ขนาดใดก็ได้ |
| 2 | `arbitrage-control` เปิดสาธารณะไม่มี auth + docker socket เขียนได้ | `POST /restart` สั่ง restart container ตามชื่อที่ส่งมา, ปิดกลยุทธ์ |
| 3 | `/apidocs/` เปิดสาธารณะ | แจกแผนที่ endpoint ทั้งหมดให้ผู้โจมตี |
| 4 | Grafana anonymous = Admin | เข้าถึง dashboard + datasource ได้เต็มสิทธิ์ (เมื่อเปิด profile `monitor`) |
| 5 | `DEBUG = True` | traceback เผย config เมื่อเกิด error |
| 6 | DRF default `AllowAny` | trade history อ่านได้สาธารณะ |

### แนวทางแก้ที่เสนอ

**ระดับ 1 — ปิดทันที ไม่กระทบระบบ**
ถอด `traefik.enable` + router labels ของ `api-mt5` และเปลี่ยน `control.py:14` เป็น `http://mt5:5001` (เก็บ router `vnc-mt5` ไว้เพราะยังต้องเข้าดูหน้าจอ terminal)

**ระดับ 2 — ปิดช่อง control-api**
ใส่ `admin-auth` middleware ที่ router `control-api-https` หรือทำ shared-token header — ต้องแก้ฝั่ง frontend ควบคู่ เพราะ basic auth จะทำให้ `fetch` จากเบราว์เซอร์พัง

**ระดับ 3 — เก็บงาน**
ตั้ง `DEFAULT_PERMISSION_CLASSES` ใน DRF · `DEBUG = False` · ปิด `/apidocs/` ใน production · ปิด Grafana anonymous · เปลี่ยน docker socket ของ control-api เป็น `:ro` ถ้าเลิกใช้ `/restart`
