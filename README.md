# DMARC Visualizer

A self-hosted DMARC report analysis stack. Automatically ingests DMARC aggregate reports from Google Drive, parses them with [parsedmarc](https://github.com/domainaware/parsedmarc), indexes them into Elasticsearch, and visualizes them in Grafana.

Forked from [debricked/dmarc-visualizer](https://github.com/debricked/dmarc-visualizer).

---

# DMARC Reports Extraction

## 1. Overview
This solution automates the extraction and storage of DMARC (Domain-based Message Authentication, Reporting, and Conformance) reports. It continuously monitors a designated Gmail inbox for incoming reports, extracts the attached `.zip` or `.gz` files, and routes them directly into a centralized Google Shared Drive for the IT/Security team to analyze, eliminating manual data entry.

## 2. System Components
The architecture relies entirely on native Google Workspace serverless components, requiring no external servers or third-party APIs:

* **Data Source (Gmail):** Receives the raw DMARC XML reports from various email providers.
* **Processing Engine (Google Apps Script):** A cloud-based JavaScript runtime that executes the extraction logic. 
* **Storage (Google Shared Drive):** The secure, centralized repository where the extracted attachments are permanently stored.
* **State Management (Gmail Labels):** Used as a tracking mechanism to ensure the script is idempotent (prevents duplicate downloads).
* **Scheduler (Time-Driven Triggers):** Google's native cron-like scheduling system that executes the script automatically at defined intervals.

## 3. Workflow and Data Flow
The automation follows a strict, step-by-step execution cycle:

1. **Trigger Initiation:** The Apps Script Time-Driven trigger fires (e.g., every hour).
2. **Targeted Query:** The script queries the Gmail API using a highly specific search string: `has:attachment (dmarc OR subject:"Report domain:") -label:DMARC-Processed`. 
3. **Batch Processing:** To respect Google's execution limits, the script fetches a strictly limited batch of email threads (e.g., 50 at a time).
4. **Extraction:** The script iterates through the unread threads, parses the messages, and extracts the file attachments in memory.
5. **File Routing:** The script connects to the designated Google Shared Drive using a hardcoded `Folder ID` and generates the files directly into that directory.
6. **State Update:** Once the files are safely in Drive, the script applies the `DMARC-Processed` label to the Gmail thread.
7. **Termination:** The script ends successfully. The next time it runs, the query naturally filters out the newly labeled emails, ensuring files are never downloaded twice.

## 4. Performance and Limit Mitigation
Google Apps Script enforces a strict **6-minute maximum execution time** per run. Because processing attachments is resource-intensive, a large backlog of emails will cause the script to time out. 

To mitigate this, the architecture relies on two safety mechanisms:

* **Micro-Batching:** The script uses pagination logic (`GmailApp.search(query, start, max)`) to force the script to stop after a safe number of emails (e.g., 50).
* **High-Frequency Triggers:** By running the script on a two-hours cadence, the workload is distributed into small, easily digestible chunks that always process within the 6-minute window.

## 5. Security and Permissions
Because this script runs internally on Google's infrastructure, no data ever leaves the Google Workspace environment. The script requires the following OAuth scopes authorized by the deploying administrator:

* `https://www.googleapis.com/auth/gmail.modify` (To read emails and apply labels)
* `https://www.googleapis.com/auth/drive` (To read the Folder ID and write new files to the Shared Drive)


# DMARC Reports Download and Processing

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
3. In your Google Drive folder → Share → add the service account email (`...@...iam.gserviceaccount.com`) with **Viewer** access

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
GCP_SERVICE_ACCOUNT_KEY = 'THE_SERVICE_ACCOUNT_KEY_FULL_JSON_CONTENT_IS_HERE'
GDRIVE_FOLDER_ID=your_shared_drive_folder_id_here
POLL_INTERVAL=300
```

The folder ID is the string at the end of your Drive folder URL:
`https://drive.google.com/drive/folders/THIS_PART`

### 4. Start the stack

```bash
docker compose up -d
```

Elasticsearch takes ~90 seconds to become healthy. The other services wait for it automatically via `depends_on: condition: service_healthy`.

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
- Authenticates to Google Drive API using a service account JSON key
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

If you need to re-download all files from Drive (`can be done in exceptional cases only since the process may take weeks!`):

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

### Maintaining the GeoLite database for IP2Country Lookups

MaxMind's GeoLite2 Country can be directly downloaded from the following links which are frequently updated:

URL1:
https://git.io/GeoLite2-Country.mmdb

URL2:
https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb

The database file, once downloaded, must be put inside the parsedmarc container (or the service should be rebuilt with the new file to update the reverse lookup database)


### Elasticsearch version upgrades

Elasticsearch indexes are not forward-compatible across major versions (Lucene format changes). When upgrading ES major versions (e.g. 7→9), the `./elastic_data/` directory must be wiped. Back it up first with a temporary ES 7.x container and `elasticdump` if data needs to be preserved.

---

## Security Notes

- Never commit `.env` to version control — add them to `.gitignore`
- The service account should have **Viewer** access only to the specific Drive folder, not the entire Drive
- Elasticsearch runs without authentication (`xpack.security.enabled=false`) — do not expose port 9200 publicly
- Grafana anonymous access is enabled — do not expose port 3000 publicly without additional authentication

---

## .gitignore

```gitignore
.env
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
