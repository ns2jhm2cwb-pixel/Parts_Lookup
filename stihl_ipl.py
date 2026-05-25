#!/usr/bin/env python3
"""
Stihl Parts Matrix Builder
Run with: python3 stihl_ipl.py
No arguments needed.
"""

import os, sys, json, csv, textwrap, subprocess, platform, re
import requests

STATE_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stihl_state.json")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stihl_parts_matrix.csv")
BASE_URL    = "https://ssc.stihl.com/backend/api"

# Part categories to look for. Add/remove rows here to change CSV columns.
TARGET_PARTS = {
    "Air Filter":    ["air filter"],
    "Pre-Filter":    ["pre-filter", "prefilter", "foam filter"],
    "Spark Plug":    ["spark plug"],
    "Fuel Filter":   ["fuel filter"],
    "Pickup Body":   ["pickup body", "pickup tube", "suction head"],
    "Primer Bulb":   ["primer bulb", "primer"],
    "Carburetor":    ["carburetor", "carburettor"],
}

# ── persistence ──────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            pass
    return {"models": {}}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w"), indent=2)

# ── display helpers ───────────────────────────────────────────────────────────

def hr(char="─", width=60):
    print(char * width)

def header(title):
    print(); hr(); print(f"  {title}"); hr()

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

# ── auth ──────────────────────────────────────────────────────────────────────

def prompt_token(state):
    header("Login — get your Stihl token")
    print(textwrap.dedent("""
        1. Open Chrome and log in to the Stihl dealer portal
        2. Press F12  →  click the "Console" tab
        3. Click in the console, paste this line, press Enter:

               localStorage.getItem('access_token')

        4. A long string appears — select all of it and copy it
           (it starts with  eyJ  and is hundreds of characters)
    """))
    saved = state.get("token", "")
    if saved:
        print("  You have a saved token. Press Enter to reuse it,")
        print("  or paste a new one if you're getting errors.\n")
    token = input("  Paste token (or Enter to reuse): ").strip().strip('"')
    if not token:
        if saved:
            print("  Using saved token.")
            return saved
        print("  No token — exiting.")
        sys.exit(1)
    state["token"] = token
    save_state(state)
    return token

# ── model search ──────────────────────────────────────────────────────────────

SEARCH_ENDPOINTS = [
    # Try the most likely patterns; first one that works gets cached.
    ("GET",  "/v2/products",             {"search": "{q}", "country": "US", "preferredLanguage": "en"}),
    ("GET",  "/v1/products",             {"search": "{q}", "country": "US", "preferredLanguage": "en"}),
    ("GET",  "/v2/models",               {"search": "{q}", "country": "US", "preferredLanguage": "en"}),
    ("POST", "/v2/products/search",      {"search": "{q}", "country": "US", "preferredLanguage": "en"}),
    ("POST", "/v2/models/search",        {"query":  "{q}", "country": "US", "preferredLanguage": "en"}),
    ("GET",  "/v2/spareParts/products",  {"search": "{q}", "country": "US", "preferredLanguage": "en"}),
]

def _auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def _working_search_endpoint(state, token):
    """Return the cached working endpoint, or discover it."""
    cached = state.get("search_endpoint")
    if cached:
        return cached

    print("  (Discovering search endpoint — one-time only...)", flush=True)
    for method, path, params in SEARCH_ENDPOINTS:
        filled = {k: v.replace("{q}", "BR") for k, v in params.items()}
        try:
            if method == "GET":
                r = requests.get(BASE_URL + path, headers=_auth_headers(token),
                                 params=filled, timeout=10)
            else:
                r = requests.post(BASE_URL + path, headers=_auth_headers(token),
                                  json=filled, timeout=10)
            if r.status_code == 200:
                results = _parse_search_results(r.json())
                if results is not None:
                    ep = {"method": method, "path": path, "params": params}
                    state["search_endpoint"] = ep
                    save_state(state)
                    return ep
        except Exception:
            continue
    return None  # no search endpoint found


def _parse_search_results(data):
    """
    Try to pull a list of {name, materialNumber} from a search response.
    Returns a list (possibly empty) or None if the structure is unrecognised.
    """
    if not isinstance(data, (dict, list)):
        return None

    candidates = []

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            mn = (obj.get("materialNumber") or obj.get("material_number") or
                  obj.get("id") or obj.get("productId") or "")
            name = (obj.get("name") or obj.get("productName") or
                    obj.get("designation") or obj.get("title") or "")
            if mn and str(mn).isdigit() and name:
                candidates.append({"name": str(name).strip(),
                                   "materialNumber": str(mn).strip()})
            else:
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        walk(v)

    walk(data)
    return candidates if candidates else None


def search_models(query, state, token):
    ep = _working_search_endpoint(state, token)
    if ep is None:
        return None  # search not available

    filled = {k: v.replace("{q}", query) for k, v in ep["params"].items()}
    try:
        if ep["method"] == "GET":
            r = requests.get(BASE_URL + ep["path"], headers=_auth_headers(token),
                             params=filled, timeout=15)
        else:
            r = requests.post(BASE_URL + ep["path"], headers=_auth_headers(token),
                              json=filled, timeout=15)
        r.raise_for_status()
        return _parse_search_results(r.json())
    except Exception:
        return None

# ── material number extraction from URL ──────────────────────────────────────

def extract_material_from_url(url):
    """Pull the first long numeric sequence from a Stihl portal URL."""
    nums = re.findall(r'\b(\d{8,15})\b', url)
    return nums[0] if nums else None

# ── add model flow ────────────────────────────────────────────────────────────

def add_model(state, token):
    header("Add a model")
    print("  Type a model name to search, OR paste the URL from the")
    print("  Stihl portal page for that model.\n")
    entry = input("  Model name or URL: ").strip()
    if not entry:
        print("  Cancelled.")
        return

    # If they pasted a URL, try extracting the material number directly
    if entry.startswith("http"):
        mn = extract_material_from_url(entry)
        if mn:
            print(f"\n  Found material number {mn} in URL.")
            _confirm_and_save_model(mn, state, token)
        else:
            print("  Couldn't find a material number in that URL.")
            print("  Try copying just the number from the URL instead.")
        return

    # Otherwise treat it as a search query
    print(f"\n  Searching for '{entry}'...", flush=True)
    results = search_models(entry, state, token)

    if results is None:
        # Search endpoint not available — fall back to manual entry
        print(textwrap.dedent("""
          Automatic search isn't available for your account.

          To find the material number manually:
            1. Open the model's IPL page on the Stihl portal
            2. Copy the URL from your browser address bar
            3. Re-run "Add a model" and paste the full URL

          Or, in DevTools → Network (Fetch/XHR), click any
          /spareParts request and look for the material number
          in the request body (it's the long number in "materialNumbers").
        """))
        mn = input("  Paste material number (digits only): ").strip()
        if mn.isdigit():
            _confirm_and_save_model(mn, state, token, name_hint=entry)
        else:
            print("  Cancelled.")
        return

    if not results:
        print(f"  No results found for '{entry}'. Try a shorter search term.")
        return

    print(f"\n  Results:\n")
    for i, r in enumerate(results[:10], 1):
        print(f"    {i}. {r['name']}  ({r['materialNumber']})")
    print()
    choice = input("  Enter number to add (or Enter to cancel): ").strip()
    if not choice:
        return
    try:
        picked = results[int(choice) - 1]
        _confirm_and_save_model(picked["materialNumber"], state, token,
                                name_hint=picked["name"])
    except (ValueError, IndexError):
        print("  Invalid choice.")


def _confirm_and_save_model(material_number, state, token, name_hint=""):
    print(f"\n  Verifying {material_number}...", end=" ", flush=True)
    try:
        data  = fetch_parts(material_number, token)
        parts = extract_parts(data)
        if not parts:
            print("no parts returned — double-check the material number.")
            return
        # Try to get a model name from the response if we don't have one
        model_name_from_api = _model_name_from_data(data)
        print(f"OK — {len(parts)} parts")
    except requests.HTTPError as e:
        if "401" in str(e):
            print("token expired — re-run and paste a fresh token.")
        else:
            print(f"error {e}")
        return

    suggested = model_name_from_api or name_hint or material_number
    name = input(f"  Save as (press Enter for '{suggested}'): ").strip()
    if not name:
        name = suggested
    state.setdefault("models", {})[name] = material_number
    save_state(state)
    print(f"  Saved '{name}'.")


def _model_name_from_data(data):
    """Try to extract a human-readable model name from the API response."""
    for key in ("modelName", "productName", "designation", "name", "model"):
        if isinstance(data, dict):
            v = data.get(key, "")
            if v and isinstance(v, str) and len(v) < 60:
                return v.strip()
    # walk one level into common wrapper keys
    for wrapper in ("product", "model", "data", "result"):
        if isinstance(data, dict) and wrapper in data:
            inner = data[wrapper]
            if isinstance(inner, dict):
                for key in ("modelName", "productName", "designation", "name"):
                    v = inner.get(key, "")
                    if v and isinstance(v, str) and len(v) < 60:
                        return v.strip()
    return ""

# ── parts fetching ────────────────────────────────────────────────────────────

def fetch_parts(material_number, token):
    r = requests.post(
        f"{BASE_URL}/v2/spareParts",
        headers=_auth_headers(token),
        json={"materialNumbers": [material_number], "country": "US",
              "preferredLanguage": "en"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def extract_parts(data):
    parts, seen = [], set()

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            pn = (obj.get("partNumber") or obj.get("materialNumber") or
                  obj.get("itemNumber") or obj.get("part_number") or "")
            name = (obj.get("name") or obj.get("description") or
                    obj.get("partName") or "")
            if pn and name and str(pn) not in seen:
                seen.add(str(pn))
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

# ── matrix builder ────────────────────────────────────────────────────────────

def build_matrix(state, token):
    models = state.get("models", {})
    if not models:
        print("\n  No models saved yet — add some first (option 1).")
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
                print("\n  Token expired. Use option 5 to update it.")
                return
            parts = []

        row = [model_name]
        for cat, keywords in TARGET_PARTS.items():
            match = find_part(parts, keywords)
            row += [match["pn"] if match else "", serial_note(match) if match else ""]
        rows.append(row)

    with open(OUTPUT_FILE, "w", newline="") as f:
        csv.writer(f).writerows([col_headers] + rows)

    print(f"\n  Done! Saved to:\n  {OUTPUT_FILE}\n")
    open_file(OUTPUT_FILE)

# ── main menu ─────────────────────────────────────────────────────────────────

def remove_model(state):
    models = state.get("models", {})
    if not models:
        print("\n  No models saved yet.")
        return
    header("Remove a model")
    names = list(models.keys())
    for i, n in enumerate(names, 1):
        print(f"  {i}. {n}")
    choice = input("\n  Number to remove (or Enter to cancel): ").strip()
    if not choice:
        return
    try:
        name = names[int(choice) - 1]
        del models[name]
        save_state(state)
        print(f"  Removed '{name}'.")
    except (ValueError, IndexError):
        print("  Invalid choice.")

def list_models(state):
    models = state.get("models", {})
    header("Saved models")
    if not models:
        print("  (none yet)")
    else:
        for name, num in models.items():
            print(f"  {name:<24}  {num}")
    print()

def main():
    state = load_state()
    token = prompt_token(state)
    print("\n  Token saved. You won't need to re-enter it until it expires.")

    while True:
        header("Main Menu")
        n = len(state.get("models", {}))
        print(f"  Models saved: {n}\n")
        print("  1. Add a model")
        print("  2. Remove a model")
        print("  3. List saved models")
        print("  4. Build parts matrix  ← do this once your models are set up")
        print("  5. Update login token")
        print("  6. Quit")
        print()
        choice = input("  Choice: ").strip()
        if   choice == "1": add_model(state, token)
        elif choice == "2": remove_model(state)
        elif choice == "3": list_models(state)
        elif choice == "4": build_matrix(state, token)
        elif choice == "5": token = prompt_token(state)
        elif choice == "6": print(); break
        else: print("  Enter 1–6.")

if __name__ == "__main__":
    main()
