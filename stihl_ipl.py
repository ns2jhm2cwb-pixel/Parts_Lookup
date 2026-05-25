#!/usr/bin/env python3
"""
Stihl Parts Matrix Builder
Run with: python3 stihl_ipl.py
No other arguments needed.
"""

import os, sys, json, csv, textwrap, subprocess, platform
import requests

STATE_FILE = os.path.join(os.path.dirname(__file__), "stihl_state.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "stihl_parts_matrix.csv")

BASE_URL = "https://ssc.stihl.com/backend/api"

# Part categories and the keywords used to find them in the parts list.
# Add more rows here if you want more columns in the output.
TARGET_PARTS = {
    "Air Filter":    ["air filter"],
    "Pre-Filter":    ["pre-filter", "prefilter", "foam filter"],
    "Spark Plug":    ["spark plug"],
    "Fuel Filter":   ["fuel filter"],
    "Pickup Body":   ["pickup body", "pickup tube", "suction head"],
    "Primer Bulb":   ["primer bulb", "primer"],
    "Carburetor":    ["carburetor", "carburettor"],
}

# ── helpers ─────────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            pass
    return {"models": {}}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w"), indent=2)

def hr(char="─", width=60):
    print(char * width)

def header(title):
    print()
    hr()
    print(f"  {title}")
    hr()

def open_file(path):
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception:
        pass

# ── token ────────────────────────────────────────────────────────────────────

def get_token(state):
    saved = state.get("token", "")
    header("Step 1 — Get your Stihl login token")
    print(textwrap.dedent("""
        Do this in Chrome while logged in to the Stihl dealer portal:

          1. Press F12  (opens DevTools)
          2. Click the "Console" tab
          3. Click in the console input at the bottom
          4. Type exactly this and press Enter:
                localStorage.getItem('access_token')
          5. A long string appears — select all of it and copy it

        The token starts with  eyJ  and is several hundred characters long.
        It expires after a while, so if you get errors later, re-run and
        paste a fresh one.
    """))
    if saved:
        print(f"  (You have a saved token. Press Enter to reuse it, or paste a new one.)")
    token = input("  Paste token here: ").strip().strip('"')
    if not token and saved:
        print("  Using saved token.")
        return saved
    if not token:
        print("  No token entered. Exiting.")
        sys.exit(1)
    state["token"] = token
    save_state(state)
    return token

# ── model management ─────────────────────────────────────────────────────────

def list_models(state):
    models = state.get("models", {})
    header("Your models")
    if not models:
        print("  (none yet)")
    else:
        for name, num in models.items():
            print(f"  {name:<20}  {num}")
    print()

def add_model(state, token):
    header("Add a model")
    print(textwrap.dedent("""
        You need the model's "material number" — a long numeric ID Stihl uses
        internally (different from the part number).

        Easiest way to find it:
          1. Go to the model's IPL page on the Stihl portal
          2. Open DevTools → Network tab → filter by "Fetch/XHR"
          3. Click on any  /spareParts  or  /repairManuals  request
          4. Look at the URL or request body for a number like  42830111610

        Or paste the full URL from your browser and the number is often in it.
    """))
    name = input("  Model name (e.g. BR 800): ").strip()
    if not name:
        print("  Cancelled.")
        return
    num = input("  Material number (digits only, e.g. 42830111610): ").strip()
    if not num.isdigit():
        print("  That doesn't look like a material number (should be digits only).")
        return

    # Quick validation
    print(f"\n  Checking {name} ({num})...", end=" ", flush=True)
    try:
        data = fetch_parts(num, token)
        parts = extract_parts(data)
        print(f"found {len(parts)} parts. ✓")
        state.setdefault("models", {})[name] = num
        save_state(state)
        print(f"  Saved.")
    except requests.HTTPError as e:
        print(f"ERROR — {e}")
        print("  Check the material number and try again.")

def remove_model(state):
    models = state.get("models", {})
    if not models:
        print("  No models saved yet.")
        return
    header("Remove a model")
    names = list(models.keys())
    for i, n in enumerate(names, 1):
        print(f"  {i}. {n}")
    choice = input("  Enter number to remove (or Enter to cancel): ").strip()
    if not choice:
        return
    try:
        name = names[int(choice) - 1]
        del models[name]
        save_state(state)
        print(f"  Removed {name}.")
    except (ValueError, IndexError):
        print("  Invalid choice.")

# ── fetching ─────────────────────────────────────────────────────────────────

def fetch_parts(material_number, token):
    resp = requests.post(
        f"{BASE_URL}/v2/spareParts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"materialNumbers": [material_number], "country": "US", "preferredLanguage": "en"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

def extract_parts(data):
    parts = []
    seen = set()

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            pn = (obj.get("partNumber") or obj.get("materialNumber") or
                  obj.get("itemNumber") or obj.get("part_number") or "")
            name = (obj.get("name") or obj.get("description") or
                    obj.get("partName") or "")
            if pn and name and pn not in seen:
                seen.add(pn)
                parts.append({
                    "pn":   str(pn).strip(),
                    "name": str(name).strip(),
                    "from": str(obj.get("serialFrom") or obj.get("fromSerial") or "").strip(),
                    "to":   str(obj.get("serialTo")   or obj.get("toSerial")   or "").strip(),
                })
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(data)
    return parts

def serial_note(p):
    f, t = p["from"], p["to"]
    if f and t:  return f"serial {f}–{t}"
    if f:        return f"from serial {f}"
    if t:        return f"up to serial {t}"
    return ""

def find_part(parts, keywords):
    for kw in keywords:
        for p in parts:
            if kw.lower() in p["name"].lower():
                return p
    return None

# ── matrix builder ───────────────────────────────────────────────────────────

def build_matrix(state, token):
    models = state.get("models", {})
    if not models:
        print("\n  No models added yet. Add some models first.")
        return

    header("Building parts matrix")
    col_headers = ["Model"]
    for cat in TARGET_PARTS:
        col_headers += [cat, f"{cat} Note"]

    rows = []
    for model_name, material_number in models.items():
        print(f"  Fetching {model_name}...", end=" ", flush=True)
        try:
            data  = fetch_parts(material_number, token)
            parts = extract_parts(data)
            print(f"{len(parts)} parts")
        except requests.HTTPError as e:
            print(f"ERROR {e}")
            if "401" in str(e):
                print("\n  Token expired — re-run the script and paste a fresh token.")
                return
            parts = []

        row = [model_name]
        for cat, keywords in TARGET_PARTS.items():
            match = find_part(parts, keywords)
            row += [match["pn"] if match else "", serial_note(match) if match else ""]
        rows.append(row)

    with open(OUTPUT_FILE, "w", newline="") as f:
        csv.writer(f).writerows([col_headers] + rows)

    print(f"\n  Done! Saved to: {OUTPUT_FILE}")
    print("  Opening file...")
    open_file(OUTPUT_FILE)

# ── main menu ────────────────────────────────────────────────────────────────

def main():
    state = load_state()
    token = get_token(state)

    while True:
        header("Main Menu")
        models = state.get("models", {})
        count = len(models)
        print(f"  Models saved: {count}")
        print()
        print("  1. Add a model")
        print("  2. Remove a model")
        print("  3. List saved models")
        print("  4. Build parts matrix CSV  ← do this when models are set up")
        print("  5. Change login token")
        print("  6. Quit")
        print()
        choice = input("  Choice: ").strip()

        if choice == "1":
            add_model(state, token)
        elif choice == "2":
            remove_model(state)
        elif choice == "3":
            list_models(state)
        elif choice == "4":
            build_matrix(state, token)
        elif choice == "5":
            token = get_token(state)
        elif choice == "6":
            print()
            break
        else:
            print("  Please enter 1–6.")

if __name__ == "__main__":
    main()
