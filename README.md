# Product Catalog Webhook Layer

A Flask and Redis service that queues supplier catalogs, normalizes JSON-LD, CSV, and XML products, persists them as Redis hashes, and streams changes to Socket.IO clients.

## Structure

- `app.py`: Flask application factory, routes, SocketIO setup, and update bridge
- `routes/ingest.py`: upload, task-status, and supplier webhook endpoints
- `transformers.py`: supplier event validation and mapping
- `workers.py`: priority event and bulk task processors
- `sockets.py`: SocketIO room handlers and event fan-out
- `parsers/`: format-specific catalog parsers
- `services/`: parsing dispatch, normalization, and persistence
- `worker.py`: lightweight Redis list worker
- `templates/index.html`: live update test client

## Run locally

Prerequisites: Python 3.10+ and a Redis server listening on `localhost:6379`.

On Windows, install Redis through WSL, then start it in a WSL terminal:

```bash
sudo apt update
sudo apt install redis-server
sudo service redis-server start
redis-cli ping
```

Alternatively, install a native Windows Redis-compatible service such as Memurai and start its service.

```powershell
python -m venv .venv
\.\.venv\Scripts\python.exe -m pip install -r requirements.txt
\.\.venv\Scripts\python.exe app.py
```

In a second terminal, run the worker with the same interpreter:

```powershell
\.\.venv\Scripts\python.exe worker.py
```

If you prefer activation, use PowerShell's process-scoped policy and dot-source the script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.venv\Scripts\Activate.ps1
python app.py
```

Open `http://localhost:5001/` to see live updates.

## Stress simulator and operations dashboard

With Redis, the worker, and the app running, open
`http://localhost:5001/dashboard` for live throughput, rejection, and latency
charts. The dashboard receives `event_processed` and `event_rejected` telemetry
over Socket.IO; it keeps a 30-second window and uses non-animated chart updates
for high event rates.

In a fourth terminal (with the same virtual environment active), run the Faker
supplier simulator. It signs every webhook with `SUPPLIER_SECRET_WEBHOOK_KEY`,
uses a deliberately small product pool to force contention, and injects older
versions to exercise stale/tombstone decisions:

```bash
python simulator.py --rate 150 --workers 24 --pool-size 20
```

Use `Ctrl+C` to stop it. Set `--duration 60` for a bounded one-minute run, or
override the destination and secret with `SIMULATOR_URL` and
`SUPPLIER_SECRET_WEBHOOK_KEY`.

To override the default port 5001, set `PORT` before starting the app:

```powershell
$env:PORT = "5002"
.\.venv\Scripts\python.exe app.py
```

Then open `http://localhost:5002/`.

## Ingest a catalog

The format is accepted as `?format=` or `X-Catalog-Format`. The upload field is `file`.

```powershell
curl.exe -X POST "http://localhost:5001/api/v1/ingest?format=csv" -F "file=@catalog.csv"
```

Response: `202 Accepted` with a `task_id`. Check processing with:

```powershell
curl.exe http://localhost:5001/api/v1/tasks/<task_id>
```

## Supplier webhooks

Supplier events are signed with HMAC-SHA256 over the exact request body. Send the
hex digest, optionally prefixed with `sha256=`, in `X-Supplier-Signature`. The
secret defaults to `mock-supplier-webhook-secret` and can be changed with
`SUPPLIER_SECRET_WEBHOOK_KEY`.

Supported events are `product.created`, `price.changed`, `inventory.changed`,
`metadata.changed`, `category.moved`, and `product.deleted`. Event data may be
under `data` or `product` and must include `id` (or `product_id`/`sku`) plus the
event-specific value. Send `version` or ISO-8601 `updated_at` on every event: a
Redis optimistic transaction rejects older updates, and a deletion tombstone
prevents an older create from resurrecting a hard-deleted product.

```json
{"event_type":"inventory.changed","data":{"product_id":"abc","inventory":12}}
```

POST these payloads to `/api/v1/webhooks/supplier`. Accepted events are placed
on the `priority_updates` queue (configurable with `REDIS_PRIORITY_QUEUE`) and
return `202 Accepted`. Start Redis locally with `docker compose up -d redis`.

The page at `/` is a mock supplier client. It joins the `default` category room,
offers create/price/inventory/delete controls, and signs each test request with
the secret in its input. Clicking **Mock create** first lets the page join that
product's room; subsequent price and inventory changes flash the card.

CSV requires `id,title,price,qty`. JSON-LD accepts Schema.org `Product` objects with `sku` or `productID`, `name`, and `offers.price`. XML expects `<products><product>...</product></products>` with `id`, `name`/`title`, `price`, and `inventory`/`qty` fields.

## Production notes

Run multiple worker processes for throughput and deploy the SocketIO app behind a compatible eventlet/gevent setup. Restrict `SOCKETIO_CORS_ALLOWED_ORIGINS`, put Redis on a private network with authentication/TLS, and add authentication, rate limits, durable task retry/dead-letter handling, metrics, and structured logging before exposing ingestion publicly.
