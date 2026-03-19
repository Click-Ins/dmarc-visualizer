# DMARC Visualizer

A self-hosted DMARC report analysis stack. Automatically ingests DMARC aggregate reports from Google Drive, parses them with [parsedmarc](https://github.com/domainaware/parsedmarc), indexes them into Elasticsearch, and visualizes them in Grafana.

Forked from [debricked/dmarc-visualizer](https://github.com/debricked/dmarc-visualizer).

---

## Architecture

```
Google Drive (Shared Drive folder)
       ↓  Drive API polling every 5 minutes
  gdrive-poller         — downloads new reports, stages atomically
       ↓  writes to ./files/
  parsedmarc            — parses reports every 30s, moves to ./processed/
       ↓  indexes to
  Elasticsearch 9.3.1   — stores parsed DMARC data
       ↓  queries
  Grafana 12.x          — dashboard visualization
```

---

## Project Structure

```
dmarc-visualizer/
├── docker-compose.yml
├── .env                          # secrets (not committed)
├── parsedmarc/
│   ├── Dockerfile
│   ├── parsedmarc.ini            # parsedmarc configuration
│   ├── run.sh                    # processing loop script
│   └── GeoLite2-Country.mmdb     # GeoIP database
├── grafana/
│   ├── Dockerfile
│   └── grafana-provisioning/
│       └── dashboards/
│           └── all.yml           # dashboard provisioning config
├── gdrive_poller/
│   ├── Dockerfile
│   └── poll.py                   # Google Drive polling script
├── creds/
│   └── gdrive_sa.json            # Google service account key (not committed)
├── files/                        # staging area for downloaded reports
├── processed/                    # reports successfully parsed (auto-cleaned after 7 days)
├── gdrive_state/
│   └── seen.json                 # tracks processed Drive file IDs
├── elastic_data/                 # Elasticsearch data volume
└── output_files/                 # parsedmarc JSON/CSV output
```

---

## Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine + Compose plugin (Linux)
- A Google Cloud project with Drive API enabled
- A Google Service Account with access to the shared Drive folder
- A Google Apps Script uploading DMARC reports to a Shared Drive folder

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-org/dmarc-visualizer.git
cd dmarc-visualizer
```

### 2. Create a Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Enable **Google Drive API**
2. Create a **Service Account** and download the JSON key
3. Place the key at `./creds/gdrive_sa.json`
4. In your Google Drive folder → Share → add the service account email (`...@...iam.gserviceaccount.com`) with **Viewer** access

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
GDRIVE_FOLDER_ID=your_shared_drive_folder_id_here
POLL_INTERVAL=300
```

The folder ID is the string at the end of your Drive folder URL:
`https://drive.google.com/drive/folders/THIS_PART`

### 4. Start the stack

```bash
docker compose up -d
```

Elasticsearch takes ~30–45 seconds to become healthy. The other services wait for it automatically via `depends_on: condition: service_healthy`.

### 5. Access Grafana

Open [http://localhost:3000](http://localhost:3000) — anonymous access is enabled by default.

---

## Configuration

### parsedmarc (`parsedmarc/parsedmarc.ini`)

Configure Elasticsearch connection, DNS resolvers, and output options. Refer to the [parsedmarc documentation](https://domainaware.github.io/parsedmarc/).

### Poll interval

Set `POLL_INTERVAL` in `.env` (seconds). Default: `300` (5 minutes).

### Processed file retention

Files in `./processed/` are automatically deleted after 7 days by `run.sh`. To change this, edit the `find -mtime +7` value in `parsedmarc/run.sh`.

---

## Changes from Original (`debricked/dmarc-visualizer`)

### `docker-compose.yml`

| Change | Reason |
|--------|--------|
| Upgraded Elasticsearch from `7.17.5` to `9.3.1` | Latest stable version |
| Added `xpack.security.enabled=false` to Elasticsearch | ES 8+ enables TLS/auth by default, which breaks the parsedmarc Python client |
| Added `healthcheck` to Elasticsearch | Prevents parsedmarc and Grafana from starting before ES is ready — fixes `Connection refused` race condition |
| Changed `depends_on` to `condition: service_healthy` on all services | Proper startup ordering tied to ES health |
| Changed parsedmarc `restart: on-failure` to `unless-stopped` | parsedmarc now runs in a continuous loop and should not be treated as a one-shot job |
| Changed parsedmarc `command` from single run to `/run.sh` loop | Enables continuous processing of new files every 30 seconds |
| Added `./processed:/input/processed` volume to parsedmarc | Persists processed files to host so they survive container restarts |
| Added `gdrive-poller` service | New service — automatically downloads DMARC reports from Google Drive |
| Removed `files` input volume read-only flag (`:ro`) | parsedmarc needs write access to move files to `processed/` |

### `grafana/grafana-provisioning/dashboards/all.yml`

| Change | Reason |
|--------|--------|
| Added `apiVersion: 1` top-level key | Required by Grafana 8+, causes nil pointer panic in Grafana 12 if missing |
| Wrapped config under `providers:` key | Grafana provisioning format requires this wrapper — bare list is not valid |
| Fixed `options.path` key (was `folder`) | Correct key name for file provider |
| Added `updateIntervalSeconds: 30` | Enables live dashboard reload |

### `parsedmarc/Dockerfile`

| Change | Reason |
|--------|--------|
| Added `COPY run.sh /run.sh` | Bakes the processing loop script into the image |
| Added `RUN chmod +x /run.sh` | Makes the script executable |

### `parsedmarc/run.sh` _(new file)_

New shell script that runs inside the parsedmarc container. Replaces the original one-shot command with a continuous loop:

- Runs `parsedmarc` every 30 seconds against all report files in `/input/`
- After each run, uses `find` to move processed files to `/input/processed/` (avoids glob expansion issues with `mv`)
- Auto-deletes processed files older than 7 days
- Only processes files with known extensions (`.xml`, `.gz`, `.zip`) — ignores `.staging/` directory and temp files

### `gdrive_poller/` _(new directory)_

Entirely new service not present in the original. Consists of:

**`gdrive_poller/Dockerfile`**
- Python 3.11 slim base image
- Installs `google-auth`, `google-auth-httplib2`, `google-api-python-client`

**`gdrive_poller/poll.py`**
- Authenticates to Google Drive API using a service account JSON key mounted at `/creds/gdrive_sa.json`
- Polls a configured Shared Drive folder every `POLL_INTERVAL` seconds
- Paginates through all Drive results (`pageSize=1000` with `nextPageToken`) — the default API limit is 100 files per request
- Tracks processed file IDs in `/state/seen.json` to avoid re-downloading
- Downloads files atomically: writes to `/input/.staging/` first, then renames into `/input/` — prevents parsedmarc from seeing incomplete files
- Supports Shared Drives via `supportsAllDrives=True` and `includeItemsFromAllDrives=True`

---

## Operational Notes

### Viewing logs

```bash
# All services
docker compose logs -f

# Individual services
docker compose logs -f parsedmarc
docker compose logs -f gdrive-poller
docker compose logs -f elasticsearch
docker compose logs -f grafana
```

### Resetting the poller state

If you need to re-download all files from Drive:

```bash
docker compose stop gdrive-poller
rm ./gdrive_state/seen.json
docker compose start gdrive-poller
```

### Checking Elasticsearch index health

```bash
curl http://localhost:9200/_cat/indices?v
```

### Rebuilding after config changes

```bash
# Rebuild a single service
docker compose up -d --build --force-recreate parsedmarc

# Rebuild everything
docker compose down
docker compose up -d --build
```

### Elasticsearch version upgrades

Elasticsearch indexes are not forward-compatible across major versions (Lucene format changes). When upgrading ES major versions (e.g. 7→9), the `./elastic_data/` directory must be wiped. Back it up first with a temporary ES 7.x container and `elasticdump` if data needs to be preserved.

---

## Security Notes

- Never commit `.env`, `creds/`, or `gdrive_state/` to version control — add them to `.gitignore`
- The service account should have **Viewer** access only to the specific Drive folder, not the entire Drive
- Elasticsearch runs without authentication (`xpack.security.enabled=false`) — do not expose port 9200 publicly
- Grafana anonymous access is enabled — do not expose port 3000 publicly without additional authentication

---

## .gitignore

```gitignore
.env
creds/
elastic_data/
gdrive_state/
files/
processed/
output_files/
```


# Original dmarc-visualizer README

Analyse and visualize DMARC results using open-source tools.

* [parsedmarc](https://github.com/domainaware/parsedmarc) for parsing DMARC reports,
* [Elasticsearch](https://www.elastic.co/) to store aggregated data.
* [Grafana](https://grafana.com/) to visualize the aggregated reports.

See the full blog post with instructions at https://debricked.com/blog/2020/05/14/analyse-and-visualize-dmarc-results-using-open-source-tools/.

## Screenshot

![Screenshot of Grafana dashboard](/big_screenshot.png?raw=true)
