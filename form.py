#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import csv
import time
import random
from datetime import datetime
import requests

# ---------------------- util: simple .env loader ----------------------
def load_env(path=".env"):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            # remove optional surrounding quotes
            v = v.strip().strip('"').strip("'")
            env[k] = v
    return env

ENV = load_env(".env")

def getenv(key, default=None, cast=str):
    val = ENV.get(key, os.getenv(key, default))
    if cast is None:
        return val
    if val is None:
        return None
    try:
        if cast is bool:
            return str(val).lower() in ["1","true","yes","y","on"]
        if cast is int:
            return int(val)
        if cast is float:
            return float(val)
        return str(val)
    except Exception:
        return default

def parse_csv_list(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else []

# ---------------------- config dari .env ----------------------
FORM_RESPONSE_URL   = getenv("FORM_RESPONSE_URL", "")
REFERER_URL         = getenv("REFERER_URL", "")
USER_AGENT          = getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                                             "Chrome/141.0.0.0 Safari/537.36")

ADDRESS_FILE        = getenv("ADDRESS_FILE", "address.txt")
OUTPUT_CSV          = getenv("OUTPUT_CSV", "results.csv")

BASE_USERNAME       = getenv("BASE_USERNAME", "bebas")
DELAY_SECONDS       = getenv("DELAY_SECONDS", 2.0, float)
MAX_RETRIES         = getenv("MAX_RETRIES", 2, int)
TIMEOUT             = getenv("TIMEOUT", 30, int)

FVV                 = getenv("FVV", "1")
PAGE_HISTORY        = getenv("PAGE_HISTORY", "0")
FBZX                = getenv("FBZX", "")  # opsional
PARTIAL_RESPONSE    = getenv("PARTIAL_RESPONSE", "")  # kalau kosong & FBZX ada, akan di-derive

# mapping entry.* (optional = bisa kosong)
ENTRY_USERNAME      = getenv("ENTRY_USERNAME", "")       # contoh: entry.691849408
ENTRY_ADDRESS       = getenv("ENTRY_ADDRESS", "")        # contoh: entry.1798315485 (legacy 1 field)
ENTRY_YES           = getenv("ENTRY_YES", "")            # contoh: entry.1770906845
ENTRY_DONE          = getenv("ENTRY_DONE", "")           # contoh: entry.1820253169

VALUE_YES           = getenv("VALUE_YES", "Yes")
VALUE_DONE          = getenv("VALUE_DONE", "Done")

# sentinel opsional (isi nama key persis: entry.xxxxx_sentinel)
ENTRY_YES_SENTINEL  = getenv("ENTRY_YES_SENTINEL", "")   # contoh: entry.1770906845_sentinel
ENTRY_DONE_SENTINEL = getenv("ENTRY_DONE_SENTINEL", "")  # contoh: entry.1820253169_sentinel

# cookies opsional (kalau form perlu login)
SESSION_COOKIES     = getenv("SESSION_COOKIES", "")

# === fitur baru: multi-address & checkbox ===
ADDRESS_KEYS                 = parse_csv_list(getenv("ADDRESS_KEYS", ""))   # "entry.974...,entry.984...,entry.109..."
CHECKBOX_KEYS                = parse_csv_list(getenv("CHECKBOX_KEYS", ""))  # "entry.1048...,entry.9525...,entry.2289..."
CHECKBOX_VALUE               = getenv("CHECKBOX_VALUE", "Completed")
AUTO_SENTINEL_FOR_CHECKBOX   = getenv("AUTO_SENTINEL_FOR_CHECKBOX", True, bool)

# Hingga N field tambahan opsional: EXTRA_FIELD_1_KEY, EXTRA_FIELD_1_VALUE, dst.
def extra_fields_from_env(max_n=20):
    extras = {}
    for i in range(1, max_n+1):
        k = getenv(f"EXTRA_FIELD_{i}_KEY", "")
        v = getenv(f"EXTRA_FIELD_{i}_VALUE", "")
        if k and v is not None:
            extras[k] = v
    return extras

EXTRA_FIELDS = extra_fields_from_env(20)

# ---------------------- helper ----------------------
def gen_username(prefix=BASE_USERNAME):
    return f"{prefix}{random.randint(1000,9999)}"

def read_addresses(path):
    items = []
    if not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                items.append(s)
    return items

def build_payload(username, address):
    payload = {}

    # username opsional: hanya dikirim kalau ENTRY_USERNAME diset
    if ENTRY_USERNAME and username:
        payload[ENTRY_USERNAME] = username

    # 1 field address lama (opsional)
    if ENTRY_ADDRESS and address:
        payload[ENTRY_ADDRESS] = address

    # multi-field address baru (semua diisi nilai address yang sama)
    for k in ADDRESS_KEYS:
        payload[k] = address

    # centang checkbox (bisa banyak)
    for k in CHECKBOX_KEYS:
        payload[k] = CHECKBOX_VALUE
        if AUTO_SENTINEL_FOR_CHECKBOX:
            payload[f"{k}_sentinel"] = ""

    # flag Yes/Done (opsional/backward compatible)
    if ENTRY_YES:
        payload[ENTRY_YES] = VALUE_YES
        if ENTRY_YES_SENTINEL:
            payload[ENTRY_YES_SENTINEL] = ""
    if ENTRY_DONE:
        payload[ENTRY_DONE] = VALUE_DONE
        if ENTRY_DONE_SENTINEL:
            payload[ENTRY_DONE_SENTINEL] = ""

    # extras
    for k, v in EXTRA_FIELDS.items():
        payload[k] = v

    # param tambahan yang sering ada di Google Form
    if FVV:
        payload["fvv"] = str(FVV)
    if PAGE_HISTORY:
        payload["pageHistory"] = str(PAGE_HISTORY)
    if FBZX:
        payload["fbzx"] = FBZX

    pr = PARTIAL_RESPONSE
    if not pr and FBZX:
        pr = f'[null,null,"{FBZX}"]'
    if pr:
        payload["partialResponse"] = pr

    return payload

def mk_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": REFERER_URL or FORM_RESPONSE_URL,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    if SESSION_COOKIES:
        # "a=1; b=2" -> dict
        cookie_pairs = [c.strip() for c in SESSION_COOKIES.split(";") if c.strip()]
        cookie_dict = {}
        for p in cookie_pairs:
            if "=" in p:
                k,v = p.split("=",1)
                cookie_dict[k.strip()] = v.strip()
        s.cookies.update(cookie_dict)
        print(f"[INFO] Cookies set: {len(cookie_dict)} item(s)")
    return s

def submit_with_retries(session, payload):
    last_exc = None
    for attempt in range(1, MAX_RETRIES+1):
        try:
            r = session.post(FORM_RESPONSE_URL, data=payload, timeout=TIMEOUT, allow_redirects=True)
            return r
        except requests.RequestException as e:
            print(f"[WARN] attempt {attempt}/{MAX_RETRIES} failed: {e}")
            last_exc = e
            time.sleep(1 + attempt)
    raise last_exc or RuntimeError("request failed")

# ---------------------- main ----------------------
def main():
    # sanity checks minimal
    if not FORM_RESPONSE_URL:
        print("[ERROR] FORM_RESPONSE_URL belum diset di .env")
        return

    # minimal harus ada SALAH SATU: (username/address/yes/done/ADDRESS_KEYS/CHECKBOX_KEYS/EXTRA_FIELDS)
    if not (ENTRY_USERNAME or ENTRY_ADDRESS or ENTRY_YES or ENTRY_DONE or ADDRESS_KEYS or CHECKBOX_KEYS or EXTRA_FIELDS):
        print("[ERROR] Tidak ada field entry.* yang diset. Set minimal satu dari ENTRY_USERNAME / ENTRY_ADDRESS / ADDRESS_KEYS / CHECKBOX_KEYS / dsb.")
        return

    addresses = read_addresses(ADDRESS_FILE)
    if not addresses:
        print(f"[ERROR] {ADDRESS_FILE} kosong atau tidak ditemukan")
        return

    s = mk_session()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp","username","address","status_code","ok","resp_snippet"
        ])
        writer.writeheader()

        total = len(addresses)
        for i, addr in enumerate(addresses, start=1):
            # hanya generate username kalau dipakai
            username = gen_username() if ENTRY_USERNAME else ""
            payload  = build_payload(username, addr)

            print(f"[{i}/{total}] submit username={username or '-'} address={addr}")
            try:
                resp = submit_with_retries(s, payload)
                ok   = 200 <= resp.status_code < 400
                snippet = (resp.text or "")[:400].replace("\n"," ")
                print(f"   -> HTTP {resp.status_code} ok={ok}")
                writer.writerow({
                    "timestamp": datetime.utcnow().isoformat(),
                    "username": username,
                    "address": addr,
                    "status_code": resp.status_code,
                    "ok": ok,
                    "resp_snippet": snippet
                })
            except Exception as e:
                print(f"   -> ERROR: {e}")
                writer.writerow({
                    "timestamp": datetime.utcnow().isoformat(),
                    "username": username,
                    "address": addr,
                    "status_code": "ERR",
                    "ok": False,
                    "resp_snippet": str(e)[:400]
                })

            time.sleep(DELAY_SECONDS)

    print(f"Selesai. Lihat {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
