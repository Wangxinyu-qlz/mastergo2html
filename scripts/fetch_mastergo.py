#!/usr/bin/env python3
"""
Fetch MasterGo design data via API
"""
import json
import os
import sys
import urllib.parse
import requests
from datetime import datetime

def parse_mastergo_url(url):
    """Parse MasterGo URL to extract file_id, page_id, layer_id"""
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)

    file_id = parsed.path.split('/')[-1]
    page_id = params.get('page_id', [''])[0]
    layer_id = params.get('layer_id', [''])[0]

    return file_id, page_id, layer_id

def fetch_mastergo_data(file_id, layer_id, api_key):
    """Fetch design data from MasterGo API"""
    # Try different API endpoint formats
    endpoints = [
        f"https://mastergo.iflytek.com/api/file/{file_id}/node?ids={layer_id}",
        f"https://mastergo.iflytek.com/api/v1/files/{file_id}/nodes?ids={layer_id}",
        f"https://mastergo.iflytek.com/api/files/{file_id}/nodes/{layer_id}",
    ]

    headers = {
        'User-Agent': 'Mozilla/5.0',
        'X-Mastergo-Api-Key': api_key,
    }

    for api_url in endpoints:
        try:
            print(f"  Trying: {api_url}")
            response = requests.get(api_url, headers=headers, verify=False, timeout=30)

            if response.status_code == 200:
                print(f"  ✓ Success!")
                return response.json()
            else:
                print(f"  ✗ Status {response.status_code}: {response.text[:100]}")
        except Exception as e:
            print(f"  ✗ Error: {e}")

    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_mastergo.py <mastergo_url>")
        sys.exit(1)

    url = sys.argv[1]
    file_id, page_id, layer_id = parse_mastergo_url(url)

    print(f"Fetching MasterGo design:")
    print(f"  File ID: {file_id}")
    print(f"  Page ID: {page_id}")
    print(f"  Layer ID: {layer_id}")

    # Load config
    config_path = ".mastergo2html/config.json"
    if not os.path.exists(config_path):
        print(f"Error: Config file not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = json.load(f)

    api_key = config.get('mastergo_api_key')
    if not api_key:
        print("Error: mastergo_api_key not found in config", file=sys.stderr)
        sys.exit(1)

    # Fetch data
    print("\nFetching data from MasterGo API...")
    data = fetch_mastergo_data(file_id, layer_id, api_key)

    if not data:
        print("\nFailed to fetch data from API.", file=sys.stderr)
        print("You may need to manually export the design data from MasterGo.", file=sys.stderr)
        sys.exit(1)

    # Create prototype directory
    prototype_key = f"{file_id}__{layer_id.replace(':', '')}"
    prototype_dir = f".mastergo2html/prototypes/{prototype_key}"
    os.makedirs(prototype_dir, exist_ok=True)

    # Save raw DSL
    dsl_path = os.path.join(prototype_dir, "dsl_raw.json")
    with open(dsl_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Save metadata
    meta = {
        "file_id": file_id,
        "layer_id": layer_id,
        "prototype_key": prototype_key,
        "prototype_dir": prototype_dir,
        "source_url": url,
        "fetched_at": datetime.now().isoformat(),
        "dsl_size_bytes": os.path.getsize(dsl_path)
    }

    meta_path = os.path.join(prototype_dir, "fetch_meta.json")
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Data fetched successfully!")
    print(f"  Prototype key: {prototype_key}")
    print(f"  Saved to: {prototype_dir}")
    print(f"  DSL size: {meta['dsl_size_bytes']} bytes")

if __name__ == "__main__":
    main()
