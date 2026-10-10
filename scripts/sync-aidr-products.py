"""Generate checked-in product catalogs for offline Go and UI bundles."""
import argparse
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = (root / 'backend/aidr_products.json').read_bytes()
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
for relative in ('scanner/internal/aidr/catalog/products.json', 'web/src/aidr-products.json',
                 'client/desktop/src/aidr-products.js'):
    path = root / relative
    content = b'window.aidrProducts = ' + data.rstrip() + b';\n' if path.suffix == '.js' else data
    if args.check:
        if not path.exists() or path.read_bytes() != content:
            raise SystemExit(f'Catalog out of date: {relative}')
    else:
        path.write_bytes(content)
