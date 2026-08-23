"""
mapper_quicklook.py
MAPPER-side counterpart to cliopatria_quicklook.py -- renders one year of
mapper/exports/cliopatria_master.geojsonl (MAPPER's own Cliopatria-schema
export pipeline, using its real ColorR/G/B rather than synthesized colors)
to a standalone HTML file, same Leaflet zoom/pan/popup behavior. Point of
this pair: open a MAPPER quicklook and a Cliopatria quicklook for the same
year side by side to compare coverage/resolution directly.

Streams the master line-by-line rather than loading it into a GeoDataFrame
(it's 360MB+/23K lines) -- same approach as export_master.py.

Usage:
  python mapper_quicklook.py -253
  python mapper_quicklook.py 1440 --all --out exports/mapper_1440_nested.html
  python mapper_quicklook.py -253 --type POLITY --type TRIBAL_AREA --type CITY
"""
import os
import json
import argparse

import folium

from quicklook_common import set_html_lang

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(MAPPER_DIR, 'exports', 'cliopatria_master.geojsonl')
DEFAULT_TYPES = ['POLITY', 'TRIBAL_AREA']
FALLBACK_COLOR = '#999999'  # rows where ColorR == "various component colors"


def resolve_hex(p):
    r, g, b = p.get('ColorR'), p.get('ColorG'), p.get('ColorB')
    if isinstance(r, str) or r is None or g is None or b is None:
        return FALLBACK_COLOR
    try:
        return '#{:02x}{:02x}{:02x}'.format(int(r), int(g), int(b))
    except (ValueError, TypeError):
        return FALLBACK_COLOR


def add_feature(m, feat, color):
    geom = feat['geometry']
    p = feat['properties']
    label = f"{p.get('Name')} [{p.get('Type')}] ({p.get('FromYear')} to {p.get('ToYear')})"
    gtype = geom['type']

    if gtype == 'Point':
        lon, lat = geom['coordinates']
        folium.CircleMarker([lat, lon], radius=5, color=color, fill=True,
                             fill_color=color, fill_opacity=0.8, popup=label).add_to(m)
    elif gtype == 'MultiPoint':
        for lon, lat in geom['coordinates']:
            folium.CircleMarker([lat, lon], radius=5, color=color, fill=True,
                                 fill_color=color, fill_opacity=0.8, popup=label).add_to(m)
    else:
        gj = folium.GeoJson(
            geom,
            style_function=lambda feature, color=color: {
                'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.5
            },
        )
        folium.Popup(label).add_to(gj)
        gj.add_to(m)


def build_map(source, year, types, show_all, container=None):
    """If `container` is given (a folium Map or FeatureGroup), features are
    added into it instead of a freshly-created Map -- lets a caller combine
    this layer with others (see mapper_cliopatria_compare.py).

    Draw order matters and is NOT source-file order: the live renderer
    (renderer.js) draws in strict phases per tile -- all political/tribal
    polygon FILLS first (_drawPoliticalFill, which also covers the
    circle-template dots -- see export_polity_polygons.py's
    find_circle_entries_by_predicate), then coordinate-dot markers
    (_drawDots), then cities (_drawCities) -- each phase always painted on
    top of the previous one, regardless of what order the underlying tiles
    happened to load in. Found 2026-08-22: this script instead added every
    feature to the map in raw master-file order, so a city (or a dot) that
    happened to appear before a polygon in the file could get visually
    buried underneath it -- reported by the user as Carthaginian coastal
    cities disappearing under the Masaesyli/Massaesyli territory fill.
    Fixed by buffering Polygon/MultiPolygon features separately from Point/
    MultiPoint ones and adding all polygons first, all points after --
    matches the live renderer's fills-before-points guarantee without
    needing to replicate its tile-batching internals, which don't apply
    here since the delivered GeoJSON has no tile concept left by this point
    in the pipeline anyway."""
    target = container
    if target is None:
        target = folium.Map(location=[20, 10], zoom_start=3,
                             tiles='https://a.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}.png',
                             attr='CartoDB')
    type_set = set(types)
    kept = 0
    scanned = 0
    polygon_feats = []
    point_feats = []
    with open(source, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            scanned += 1
            feat = json.loads(line)
            p = feat['properties']
            if p.get('Type') not in type_set:
                continue
            if p.get('FromYear', float('inf')) > year or p.get('ToYear', float('-inf')) < year:
                continue
            if not show_all and p.get('MemberOf'):
                continue
            bucket = point_feats if feat['geometry']['type'] in ('Point', 'MultiPoint') else polygon_feats
            bucket.append((feat, resolve_hex(p)))
            kept += 1
    for feat, color in polygon_feats:
        add_feature(target, feat, color)
    for feat, color in point_feats:
        add_feature(target, feat, color)
    return target, kept, scanned


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('year', type=int, help='Year to display (negative for BCE)')
    ap.add_argument('--source', default=DEFAULT_SOURCE)
    ap.add_argument('--type', action='append', default=None,
                     help=f'Type(s) to include; repeatable. Default: {DEFAULT_TYPES}')
    ap.add_argument('--all', action='store_true', dest='show_all',
                     help='Include nested (non-top-level) rows too, not just MemberOf-blank ones')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    types = args.type or DEFAULT_TYPES
    out = args.out or os.path.join(MAPPER_DIR, 'exports', f'mapper_quicklook_{args.year}.html')

    print(f"Scanning {args.source} for year {args.year}, types={types}, "
          f"{'all levels' if args.show_all else 'top-level only'} ...")
    m, kept, scanned = build_map(args.source, args.year, types, args.show_all)

    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    m.save(out)
    set_html_lang(out)
    print(f"{kept} shape(s) active in {args.year} (scanned {scanned} master lines). Wrote {out}")


if __name__ == '__main__':
    main()
