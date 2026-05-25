#!/usr/bin/env python3
"""
Stihl IPL part matrix builder.

Fetches parts from ssc.stihl.com and builds a model x part-category CSV.

Get your Bearer token from the Stihl dealer portal:
  1. Open DevTools -> Console
  2. Run: localStorage.getItem('access_token')
  3. Copy the value

Usage:
  export STIHL_TOKEN="eyJ..."
  python stihl_ipl.py dump "BR 800"      # inspect raw parts list for a model
  python stihl_ipl.py matrix             # build full CSV matrix
  python stihl_ipl.py matrix --out my_matrix.csv
"""

import os
import sys
import json
import csv
import argparse
import requests

# ---------------------------------------------------------------------------
# CONFIG — edit these two dicts
# ---------------------------------------------------------------------------

# Model display name -> Stihl material number (the numeric ID used in the API)
# To find a material number: open the model's IPL page, check the URL or
# run: dump mode on a known material number to verify it's the right model.
MODELS = {
    "BR 800": "42830111610",
    # "FS 132": "45120111610",
    # "HL 94": "...",
}

# Part category display name -> list of keywords to match against part names
# Matching is case-insensitive substring search. First match per category wins.
# Add more keywords to catch alternate naming.
TARGET_PARTS = {
    "Air Filter":   ["air filter"],
    "Spark Plug":   ["spark plug"],
    "Pickup Body":  ["pickup body", "pickup tube", "suction head"],
    "Fuel Filter":  ["fuel filter"],
    "Pre-Filter":   ["pre-filter", "prefilter", "foam filter"],
    "Primer Bulb":  ["primer bulb", "primer"],
    "Carburetor":   ["carburetor", "carburettor"],
    "Recoil Spring":["recoil spring", "return spring"],
}

# ---------------------------------------------------------------------------

BASE_URL = "https://ssc.stihl.com/backend/api"
COUNTRY  = "US"
LANG     = "en"


def get_token():
    token = os.environ.get("STIHL_TOKEN", "").strip()
    if not token:
        print("ERROR: Set STIHL_TOKEN environment variable.")
        print("  Get it from Stihl portal DevTools Console:")
        print("  > localStorage.getItem('access_token')")
        sys.exit(1)
    return token


def fetch_parts(material_number: str, token: str) -> dict:
    resp = requests.post(
        f"{BASE_URL}/v2/spareParts",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "materialNumbers": [material_number],
            "country": COUNTRY,
            "preferredLanguage": LANG,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def extract_all_parts(data: dict) -> list[dict]:
    """Flatten all parts out of whatever nested structure the API returns."""
    parts = []

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            # A part-like object has a part number field
            pn = (
                obj.get("partNumber")
                or obj.get("part_number")
                or obj.get("materialNumber")
                or obj.get("itemNumber")
            )
            name = (
                obj.get("name")
                or obj.get("description")
                or obj.get("partName")
                or ""
            )
            if pn and name:
                parts.append({
                    "pn":           str(pn).strip(),
                    "name":         str(name).strip(),
                    "serialFrom":   obj.get("serialFrom") or obj.get("fromSerial") or obj.get("validFrom") or "",
                    "serialTo":     obj.get("serialTo")   or obj.get("toSerial")   or obj.get("validTo")   or "",
                    "qty":          obj.get("quantity") or obj.get("qty") or "",
                    "raw":          obj,
                })
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(data)
    # deduplicate by part number (keep first occurrence)
    seen = set()
    unique = []
    for p in parts:
        if p["pn"] not in seen:
            seen.add(p["pn"])
            unique.append(p)
    return unique


def serial_note(part: dict) -> str:
    f, t = str(part["serialFrom"]).strip(), str(part["serialTo"]).strip()
    if f and t:
        return f"serial {f} – {t}"
    if f:
        return f"from serial {f}"
    if t:
        return f"up to serial {t}"
    return ""


def find_part(parts: list[dict], keywords: list[str]) -> dict | None:
    """Return the first part whose name contains any keyword (case-insensitive)."""
    for kw in keywords:
        kw_lower = kw.lower()
        for p in parts:
            if kw_lower in p["name"].lower():
                return p
    return None


def cmd_dump(args):
    token = get_token()
    model_name = args.model
    material_number = MODELS.get(model_name)

    if not material_number:
        # Allow passing a raw material number directly
        if model_name.isdigit():
            material_number = model_name
            model_name = f"Material {material_number}"
        else:
            known = ", ".join(f'"{k}"' for k in MODELS)
            print(f"ERROR: Unknown model '{model_name}'. Known models: {known}")
            print("Or pass a raw material number (digits only).")
            sys.exit(1)

    print(f"Fetching parts for {model_name} ({material_number})...")
    data = fetch_parts(material_number, token)

    if args.raw:
        print(json.dumps(data, indent=2))
        return

    parts = extract_all_parts(data)
    print(f"\n{len(parts)} parts found:\n")
    print(f"{'Part Number':<20} {'Serial From':<14} {'Serial To':<14} Name")
    print("-" * 80)
    for p in parts:
        print(f"{p['pn']:<20} {str(p['serialFrom']):<14} {str(p['serialTo']):<14} {p['name']}")


def cmd_matrix(args):
    token = get_token()
    out_path = args.out or "stihl_parts_matrix.csv"

    # Build header row
    headers = ["Model"]
    for cat in TARGET_PARTS:
        headers.append(cat)
        headers.append(f"{cat} Note")

    rows = []
    for model_name, material_number in MODELS.items():
        print(f"Fetching {model_name} ({material_number})...", end=" ", flush=True)
        try:
            data  = fetch_parts(material_number, token)
            parts = extract_all_parts(data)
            print(f"{len(parts)} parts")
        except requests.HTTPError as e:
            print(f"ERROR {e}")
            parts = []

        row = [model_name]
        for cat, keywords in TARGET_PARTS.items():
            match = find_part(parts, keywords)
            if match:
                row.append(match["pn"])
                row.append(serial_note(match))
            else:
                row.append("")
                row.append("")
        rows.append(row)

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"\nMatrix written to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Stihl IPL part matrix builder")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="Print all parts for one model")
    p_dump.add_argument("model", help='Model name (e.g. "BR 800") or raw material number')
    p_dump.add_argument("--raw", action="store_true", help="Print raw JSON response")
    p_dump.set_defaults(func=cmd_dump)

    p_matrix = sub.add_parser("matrix", help="Build model x part-category CSV")
    p_matrix.add_argument("--out", help="Output CSV path (default: stihl_parts_matrix.csv)")
    p_matrix.set_defaults(func=cmd_matrix)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
