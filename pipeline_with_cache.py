import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request

CACHE_FILE = "image_cache.json"
INPUT_CSV = "inventory.csv"
OUTPUT_CSV = "final.csv"

def clean_gtin(gtin):
    """Normalize GTIN/UPC barcode strings."""
    if not gtin:
        return ""
    gtin_str = str(gtin).strip().split('.')[0]
    gtin_str = re.sub(r'\D', '', gtin_str)
    if len(gtin_str) < 12 and len(gtin_str) > 0:
        gtin_str = gtin_str.zfill(12)
    return gtin_str

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading cache: {e}")
    return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Error saving cache: {e}")

def search_and_verify_image(upc, name, brand):
    """Query product APIs / repositories to extract product image.
    
    Returns (image_url, score, status)
    """
    clean_upc = clean_gtin(upc)

    # 1. Check Open Food Facts API
    if clean_upc:
        try:
            off_url = f"https://world.openfoodfacts.org/api/v0/product/{clean_upc}.json"
            req = urllib.request.Request(
                off_url, 
                headers={'User-Agent': 'CountrySpiritShopCatalog/1.0'}
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('status') == 1 and 'product' in data:
                    img = data['product'].get('image_front_url') or data['product'].get('image_url')
                    if img:
                        return img, 90, "ACCEPT"
        except Exception:
            pass

    # 2. Fallback: Query DuckDuckGo Image Web Scraper
    try:
        query = f"{name} {brand} bottle".strip()
        ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(
            ddg_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
            }
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            html = resp.read().decode('utf-8')
            urls = re.findall(r'//external-content\.duckduckgo\.com/iu/\?u=(http[s]?://[^&"\']+)', html)
            if urls:
                image_url = urllib.parse.unquote(urls[0])
                return image_url, 75, "SCRAPED"
    except Exception:
        pass

    return "", 0, "NO_IMAGE"

def process_pipeline():
    cache = load_cache()
    if not os.path.exists(INPUT_CSV):
        print(f"Input file {INPUT_CSV} not found.")
        return

    with open(INPUT_CSV, "r", encoding="utf-8-sig") as infile:
        reader = csv.DictReader(infile)
        fieldnames = list(reader.fieldnames or [])
        if "image_url" not in fieldnames:
            fieldnames.append("image_url")

        rows = []
        updated_count = 0

        for row in reader:
            upc = row.get("upc", "").strip()
            name = row.get("name", "").strip()
            brand = row.get("brand", "").strip()
            
            cache_key = upc if upc else f"{name}_{brand}"

            if cache_key in cache and cache[cache_key].get("image_url"):
                row["image_url"] = cache[cache_key]["image_url"]
            else:
                print(f"Searching image for: {name} ({brand})...")
                img_url, score, status = search_and_verify_image(upc, name, brand)
                row["image_url"] = img_url
                cache[cache_key] = {
                    "image_url": img_url,
                    "score": score,
                    "status": status,
                    "updated_at": time.time()
                }
                updated_count += 1
                time.sleep(0.5)  # Respectful API delay

            rows.append(row)

    save_cache(cache)

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Pipeline finished! Processed {len(rows)} products ({updated_count} new lookups).")

if __name__ == "__main__":
    process_pipeline()
