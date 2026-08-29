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

Open `http://localhost:5000/` to see live updates.

If port 5000 is already in use, start the app on another port:

```powershell
$env:PORT = "5001"
.\.venv\Scripts\python.exe app.py
```

Then open `http://localhost:5001/`.

## Ingest a catalog

The format is accepted as `?format=` or `X-Catalog-Format`. The upload field is `file`.

```powershell
curl.exe -X POST "http://localhost:5000/api/v1/ingest?format=csv" -F "file=@catalog.csv"
```

Response: `202 Accepted` with a `task_id`. Check processing with:

```powershell
curl.exe http://localhost:5000/api/v1/tasks/<task_id>
```

## Supplier webhooks

Supplier events are signed with HMAC-SHA256 over the exact request body. Send the
hex digest, optionally prefixed with `sha256=`, in `X-Supplier-Signature`. The
secret defaults to `mock-supplier-webhook-secret` and can be changed with
`SUPPLIER_SECRET_WEBHOOK_KEY`.

Supported events are `inventory.changed` and `price.changed`. Event data may be
under `data` or `product` and must include `id` (or `product_id`/`sku`) plus the
event-specific value:

```json
{"event_type":"inventory.changed","data":{"product_id":"abc","inventory":12}}
```

POST these payloads to `/api/v1/webhooks/supplier`. Accepted events are placed
on the `priority_updates` queue (configurable with `REDIS_PRIORITY_QUEUE`) and
return `202 Accepted`. Start Redis locally with `docker compose up -d redis`.

CSV requires `id,title,price,qty`. JSON-LD accepts Schema.org `Product` objects with `sku` or `productID`, `name`, and `offers.price`. XML expects `<products><product>...</product></products>` with `id`, `name`/`title`, `price`, and `inventory`/`qty` fields.

## Production notes

Run multiple worker processes for throughput and deploy the SocketIO app behind a compatible eventlet/gevent setup. Restrict `SOCKETIO_CORS_ALLOWED_ORIGINS`, put Redis on a private network with authentication/TLS, and add authentication, rate limits, durable task retry/dead-letter handling, metrics, and structured logging before exposing ingestion publicly.
