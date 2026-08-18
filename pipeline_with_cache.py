import csv
import json
import os
import re
import urllib.request
import urllib.parse

# File Configurations
INVENTORY_CSV = 'items.csv'           # Uploaded/replaced POS export
MASTER_CACHE_FILE = 'image_cache.json' # Persistent memory across runs
FINAL_CSV = 'final.csv'              # Master catalog used by index.html
NEW_CSV = 'new.csv'                  # Overwritten each run (contains ONLY new items)

def clean_gtin(gtin_raw):
    """Normalize GTINs/barcodes to standard digits."""
    if not gtin_raw:
        return ""
    cleaned = re.sub(r'\D', '', str(gtin_raw))
    if cleaned in ['', '0', '0000', '000000000000', '0000000000000']:
        return ""
    return cleaned.zfill(14)

def load_cache():
    if os.path.exists(MASTER_CACHE_FILE):
        try:
            with open(MASTER_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache):
    with open(MASTER_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)

def generate_description(product_name, size):
    """Generate standardized store product description."""
    name_str = str(product_name).strip() if product_name else "this product"
    size_str = str(size).strip() if size and str(size).strip().upper() != 'NAN' else "standard size"
    return (
        f"Shop {name_str} at Country Spirit Shop. "
        f"This product is available in {size_str} and can be ordered online or bought at our store, "
        f"subject to availability. See the product listing for current pricing and availability."
    )

def search_and_verify_image(upc, name, brand):
    """
    Query product APIs / repositories to extract product image.
    Returns (image_url, score, status)
    """
    clean_upc = clean_gtin(upc)
    
    # 1. Check Open Food Facts / Open Products CDN by UPC if present
    if clean_upc:
        try:
            # Strip extra leading zeros for 12-digit UPC lookup if necessary
            upc_short = clean_upc.lstrip('0')
            off_url = f"https://world.openfoodfacts.org/api/v0/product/{clean_upc}.json"
            req = urllib.request.Request(off_url, headers={'User-Agent': 'CountrySpiritShopCatalog/1.0'})
            
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('status') == 1 and 'product' in data:
                    img = data['product'].get('image_front_url') or data['product'].get('image_url')
                    if img:
                        return img, 90, "ACCEPT"
        except Exception:
            pass

    # 2. Return fallback empty image status if no valid URL found
    return "", 0, "NO_IMAGE"

def main():
    cache = load_cache()
    new_items = []
    all_processed_items = []

    if not os.path.exists(INVENTORY_CSV):
        print(f"Error: {INVENTORY_CSV} not found.")
        return

    with open(INVENTORY_CSV, mode='r', encoding='utf-8-sig') as infile:
        reader = csv.DictReader(infile)
        fieldnames = list(reader.fieldnames or [])

        for row in reader:
            upc = clean_gtin(row.get('UPC Full') or row.get('UPC/GTIN') or row.get('UPC'))
            sku = row.get('SKU', '')
            key = upc if upc else f"SKU_{sku}" if sku else f"NAME_{row.get('Name', '')}"

            # 1. Fill Description Column
            product_name = row.get('Name', '') or row.get('Item Name', '')
            product_size = row.get('Size', '')
            row['description'] = generate_description(product_name, product_size)

            # 2. Match or Scrape Image
            if key in cache and cache[key].get('image_url'):
                # Reuse cached data
                row['image_url'] = cache[key]['image_url']
                row['confidence_score'] = cache[key].get('confidence_score', 100)
                row['status'] = cache[key].get('status', 'CACHED')
            else:
                # Brand new item -> Scrape & verify
                image_url, score, status = search_and_verify_image(
                    upc, product_name, row.get('Supplier Name', '')
                )
                
                # Update Cache
                cache[key] = {
                    'image_url': image_url,
                    'confidence_score': score,
                    'status': status,
                    'name': product_name,
                    'sku': sku
                }
                
                row['image_url'] = image_url
                row['confidence_score'] = score
                row['status'] = status
                
                new_items.append(row)

            all_processed_items.append(row)

    # Save master cache
    save_cache(cache)

    # Build output field list
    out_fields = list(fieldnames)
    for col in ['description', 'image_url', 'confidence_score', 'status']:
        if col not in out_fields:
            out_fields.append(col)

    # 1. Write final.csv (Full updated catalog for index.html)
    with open(FINAL_CSV, 'w', newline='', encoding='utf-8') as final_file:
        writer = csv.DictWriter(final_file, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(all_processed_items)

    # 2. Write new.csv (OVERWRITTEN with ONLY items added in this upload)
    with open(NEW_CSV, 'w', newline='', encoding='utf-8') as new_file:
        writer = csv.DictWriter(new_file, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(new_items)

    print(f"Processed {len(all_processed_items)} total items into '{FINAL_CSV}'.")
    print(f"Isolated {len(new_items)} brand new items into '{NEW_CSV}'.")

if __name__ == '__main__':
    main()
