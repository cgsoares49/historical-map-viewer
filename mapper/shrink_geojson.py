"""
shrink_geojson.py
Shrinks a GeoJSON FeatureCollection for easier sharing (e.g. email attachment
size limits), two independent, combinable levers:

  --precision N   Round every coordinate to N decimal places (lossless if N
                   is already >= the source's real precision -- just removes
                   float-formatting/whitespace bloat; lossy if smaller).
  --simplify TOL  Douglas-Peucker polygon simplification (shapely, degrees;
                   ~0.001 = ~111m at the equator), reduces vertex count.
                   Only applied to Polygon/MultiPolygon geometry; Point/
                   MultiPoint pass through unchanged. 0 (default) = off.

Also writes compact JSON (no separator whitespace) regardless of the above --
that alone is a real, lossless size cut on a file this large.

Usage:
  python shrink_geojson.py in.geojson out.geojson --precision 4
  python shrink_geojson.py in.geojson out.geojson --precision 4 --simplify 0.002
"""
import json
import argparse

from shapely.geometry import shape, mapping


def round_coords(obj, ndigits):
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, list):
        return [round_coords(x, ndigits) for x in obj]
    return obj


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source')
    ap.add_argument('out')
    ap.add_argument('--precision', type=int, default=4)
    ap.add_argument('--simplify', type=float, default=0.0)
    args = ap.parse_args()

    with open(args.source, encoding='utf-8') as f:
        data = json.load(f)

    simplified_count = 0
    for feat in data['features']:
        geom = feat.get('geometry')
        if not geom:
            continue
        if args.simplify > 0 and geom['type'] in ('Polygon', 'MultiPolygon'):
            shp = shape(geom).simplify(args.simplify, preserve_topology=True)
            geom = mapping(shp)
            feat['geometry'] = geom
            simplified_count += 1
        geom['coordinates'] = round_coords(geom['coordinates'], args.precision)

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    print(f"{len(data['features'])} features written, {simplified_count} simplified. Wrote {args.out}")


if __name__ == '__main__':
    main()
