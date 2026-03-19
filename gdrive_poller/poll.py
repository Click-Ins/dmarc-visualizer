# gdrive_poller/poll.py
import os, time, json
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

#CREDS_FILE    = os.environ.get("GDRIVE_CREDS_FILE", "/creds/gdrive_sa.json")
FOLDER_ID     = os.environ["GDRIVE_FOLDER_ID"]
OUTPUT_DIR    = Path("/input")
STATE_FILE    = Path("/state/seen.json")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))
STAGING_DIR   = OUTPUT_DIR / ".staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

def get_service():
    
    #creds = service_account.Credentials.from_service_account_file(
    #    CREDS_FILE, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    #)
    creds_dict = json.loads(os.environ["GCP_SERVICE_ACCOUNT_KEY"])

    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )

    return build("drive", "v3", credentials=creds)

def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()

def save_seen(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(list(seen)))

def list_files(service):
    """List all files in folder, paginating through all pages."""
    all_files = []
    page_token = None

    while True:
        kwargs = dict(
            q=f"'{FOLDER_ID}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.files().list(**kwargs).execute()
        all_files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")

        if not page_token:
            break

    return all_files

def download_file(service, file_id, dest_path):
    """Download to staging area first, then atomically move to /input."""
    tmp_path = STAGING_DIR / dest_path.name
    request = service.files().get_media(
        fileId=file_id,
        supportsAllDrives=True
    )
    with open(tmp_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    # Atomic rename — same filesystem guaranteed since staging is inside /input
    tmp_path.rename(dest_path)

def main():
    service = get_service()
    seen = load_seen()
    print(f"Poller started. Watching folder {FOLDER_ID}, interval {POLL_INTERVAL}s")

    while True:
        try:
            files = list_files(service)
            new_files = [f for f in files if f["id"] not in seen]
            print(f"Found {len(files)} total files, {len(new_files)} new.")

            for f in new_files:
                dest = OUTPUT_DIR / f["name"]
                print(f"Downloading: {f['name']}")
                download_file(service, f["id"], dest)
                seen.add(f["id"])
                save_seen(seen)
                print(f"Saved: {dest.name}")

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
