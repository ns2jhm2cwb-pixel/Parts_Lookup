#!/usr/bin/env python3
"""
Run this on your machine: python3 fetch_parts.py
Results print to screen and save to stihl_results.csv
"""
import requests, json, csv, sys

TOKEN = "eyJ0eXAiOiJKV1QiLCJraWQiOiJ1SHJ3UG5RdUVZUVpWUHJhY0tabUdwYzNWSGc9IiwiYWxnIjoiUlMyNTYifQ.eyJzdWIiOiI1ZjFmYzYwNi1hNzczLTQxNjktYjk4ZS1mNGE5OTkyMDNhMjMiLCJjdHMiOiJPQVVUSDJfR1JBTlRfU0VUIiwiYXV0aF9sZXZlbCI6MSwiYXVkaXRUcmFja2luZ0lkIjoiZTkxMzg0YWYtZGJlYy00YTQ4LWFmZmUtMjNjNDQ3OWU3ZTdlLTEwODMwNDg3NiIsInN1Ym5hbWUiOiI1ZjFmYzYwNi1hNzczLTQxNjktYjk4ZS1mNGE5OTkyMDNhMjMiLCJpc3MiOiJodHRwczovL3N0aWhsLXNzby5jb206NDQzL2F1dGgvb2F1dGgyL2NvbnN1bWVyIiwidG9rZW5OYW1lIjoiYWNjZXNzX3Rva2VuIiwidG9rZW5fdHlwZSI6IkJlYXJlciIsImF1dGhHcmFudElkIjoiWGhxMG9ZcmNodEhvdG93SnEyejVPdnpCTVVvLkZFbE9Rb3ZXbkpDV2V3enQyR0p5U1VPN3NzbyIsImNsaWVudF9pZCI6InNzYyIsImF1ZCI6InNzYyIsIm5iZiI6MTc3OTc1ODUyMywiZ3JhbnRfdHlwZSI6InJlZnJlc2hfdG9rZW4iLCJzY29wZSI6WyJiMmIuY2FydDp3cml0ZSIsImRlYWxlck9yZyIsIm9wZW5pZCIsInByb2ZpbGUiLCJiMmIud2lzaGxpc3Q6d3JpdGUiLCJlbWFpbCJdLCJhdXRoX3RpbWUiOjE3Nzk3Mjc4NzAsInJlYWxtIjoiL2NvbnN1bWVyIiwiZXhwIjoxNzc5NzYyMTIzLCJpYXQiOjE3Nzk3NTg1MjMsImV4cGlyZXNfaW4iOjM2MDAsImp0aSI6IlhocTBvWXJjaHRIb3Rvd0pxMno1T3Z6Qk1Vby53MFpteFhZWm5VOEhrOVRDTDB3SWhJMGlaNVEifQ.4Pz9dqmQWUalEgThJOPFSfP6kHWuJPrqLFl3KuUHbREjzQSKjSUqsx9r9kxS-ueaapo989Dxfo-6CwqHMknRVLp4eUmdIFsUS37AskPoO9UNZ7VouZJTcP0OUzR_aoKgrdwpM1gGHkpArH3uSsGm6OoCEJBhydp73acagwNqvIiWkHl0X194ImXk3WCNI9n7hGUmDpubYpLBtOr9q_WyymXKwVNNjCdHZFYHTwOqmlZZeIquxzzncXs-d7_CStL53XZcIvu2BC0ikr5552_7KOCiAkSB-ecZJbaGI3hQyeX2NSGxAHhcqc2FggZM00SfvBko7boMhTr_4f5XnhysGM6uvuY4iZry5DA_qGqebj7W7nRzVn0FpgbYPPwJIyTyOAXTYvM3KWyKq9Fkg8kEHXBV0O9RjdgiAzMTDf5FDh0u7vMUWnFPPAc5CC9E4gGPD2Nwx2Sxik1RK4xsTlQklEDp1AKfCVHRXILb3l0ZZ-Wk1wVViCVsb2_ihcqkWCuBHV2RjbEraP4J2NUrTqqnImjHLEAqPcu7aygQFjvmArfXCXDDC_sb6xhBWEVFBT36ucx-VOeEXHDz-CbQdTHdvKssKdRy7f4VHervNQH9gSED9D7B8H_s5NCHOVrwCKIUodSnWkGodYFVTZLDqMSDMK0cQWjnC8bONXFbIcG_1ZE"

MODELS = ["FS 56", "FS 70", "FS 91", "FS 94", "FS 131", "FS 251"]

TARGET_PARTS = {
    "Air Filter":  ["air filter"],
    "Fuel Filter": ["fuel filter"],
    "Carburetor":  ["carburetor", "carburettor"],
}

BASE = "https://ssc.stihl.com/backend/api"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

SEARCH_ENDPOINTS = [
    ("GET",  f"{BASE}/v2/products",        {"country": "US", "preferredLanguage": "en"}),
    ("GET",  f"{BASE}/v2/models",          {"country": "US", "preferredLanguage": "en"}),
    ("GET",  f"{BASE}/v2/articles",        {"country": "US", "preferredLanguage": "en"}),
    ("POST", f"{BASE}/v2/products/search", {"country": "US", "preferredLanguage": "en"}),
]

def find_in(obj, keys):
    if isinstance(obj, list):
        for item in obj:
            r = find_in(item, keys)
            if r: return r
    elif isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k]: return str(obj[k]).strip()
        for v in obj.values():
            r = find_in(v, keys)
            if r: return r
    return ""

def parse_search(data):
    results = []
    seen = set()
    def walk(obj):
        if isinstance(obj, list): [walk(i) for i in obj]; return
        if not isinstance(obj, dict): return
        mn   = find_in(obj, ["materialNumber","material_number","productId","articleNumber","id"])
        name = find_in(obj, ["name","productName","designation","modelName","title"])
        if mn and str(mn).isdigit() and len(str(mn)) >= 8 and mn not in seen:
            seen.add(mn); results.append((name, mn))
        else:
            for v in obj.values():
                if isinstance(v, (dict,list)): walk(v)
    walk(data)
    return results

def search_model(query):
    for method, url, base_params in SEARCH_ENDPOINTS:
        try:
            params = {**base_params, "search": query}
            if method == "GET":
                r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            else:
                r = requests.post(url, headers=HEADERS, json=params, timeout=15)
            if r.status_code == 200:
                results = parse_search(r.json())
                if results:
                    return results
        except: pass
    return []

def fetch_parts(material_number):
    r = requests.post(f"{BASE}/v2/spareParts", headers=HEADERS,
        json={"materialNumbers": [material_number], "country": "US", "preferredLanguage": "en"},
        timeout=30)
    r.raise_for_status()
    return r.json()

def extract_parts(data):
    parts, seen = [], set()
    def walk(obj):
        if isinstance(obj, list): [walk(i) for i in obj]; return
        if not isinstance(obj, dict): return
        pn   = find_in(obj, ["partNumber","part_number","itemNumber"])
        name = find_in(obj, ["name","description","partName"])
        if pn and name and pn not in seen:
            seen.add(pn)
            parts.append({"pn": pn, "name": name,
                          "from": str(obj.get("serialFrom", obj.get("fromSerial",""))).strip(),
                          "to":   str(obj.get("serialTo",   obj.get("toSerial",  ""))).strip()})
        for v in obj.values():
            if isinstance(v, (dict,list)): walk(v)
    walk(data); return parts

def find_part(parts, keywords):
    for kw in keywords:
        for p in parts:
            if kw.lower() in p["name"].lower(): return p
    return None

def serial_note(p):
    if p["from"] and p["to"]: return f"serial {p['from']}–{p['to']}"
    if p["from"]: return f"from serial {p['from']}"
    if p["to"]:   return f"up to serial {p['to']}"
    return ""

print("Stihl Parts Lookup\n" + "="*50)
rows = []

for model in MODELS:
    print(f"\n{model}: searching...", end=" ", flush=True)
    candidates = search_model(model)

    if not candidates:
        print("NOT FOUND — check token or search endpoint")
        rows.append({"model": model, "status": "not found"})
        continue

    # Pick the best match — prefer exact model name match
    best = None
    for name, mn in candidates:
        if model.lower() in name.lower():
            best = (name, mn); break
    if not best:
        best = candidates[0]

    name, mn = best
    print(f"found '{name}' ({mn}), fetching parts...", end=" ", flush=True)

    try:
        data  = fetch_parts(mn)
        parts = extract_parts(data)
        print(f"{len(parts)} parts")

        row = {"model": model, "full_name": name, "material": mn}
        for cat, keywords in TARGET_PARTS.items():
            match = find_part(parts, keywords)
            row[cat] = match["pn"] if match else "NOT FOUND"
            row[f"{cat} note"] = serial_note(match) if match else ""
            found = match["pn"] if match else "—"
            print(f"  {cat:<14} {found}")

        rows.append(row)
    except Exception as e:
        print(f"ERROR: {e}")
        if "401" in str(e): print("  Token expired — get a fresh one and update it in the script")
        rows.append({"model": model, "status": f"error: {e}"})

# Write CSV
if rows:
    cats = list(TARGET_PARTS.keys())
    fields = ["model","full_name","material"] + [c for cat in cats for c in [cat, f"{cat} note"]]
    with open("stihl_results.csv","w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    print(f"\nSaved to stihl_results.csv")
