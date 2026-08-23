"""
cliopatria_quicklook.py
Static, no-Jupyter-needed equivalent of the Cliopatria repo's
notebooks/map_functions.py::create_folium_map -- renders one year of the
colorized Cliopatria dataset (from convert_data.py) to a standalone HTML file
that opens directly in a browser with full Leaflet zoom/pan/click-popups.

Usage:
  python cliopatria_quicklook.py 1700
  python cliopatria_quicklook.py -500 --components --out exports/cliopatria_-500.html
"""
import os
import sys
import argparse

import folium
import geopandas as gpd

from quicklook_common import set_html_lang

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(MAPPER_DIR, 'exports', 'cliopatria_raw_v0.0.1_seshat_processed.geojson')


def build_map(gdf, year, components=False, container=None):
    """If `container` is given (a folium Map or FeatureGroup), features are
    added into it instead of a freshly-created Map -- lets a caller combine
    this layer with others (see mapper_cliopatria_compare.py). Returns
    (container_or_new_map, count)."""
    filtered = gdf[(gdf['FromYear'] <= year) & (gdf['ToYear'] >= year)]

    # Same logic as map_functions.py's shouldDisplayComponent duplication note
    if components:
        filtered = filtered[(filtered['Components'].isnull()) | (filtered['Components'] == '')]
    else:
        filtered = filtered[(filtered['MemberOf'].isnull()) | (filtered['MemberOf'] == '')]

    filtered = filtered.to_crs(epsg=4326)

    target = container
    if target is None:
        target = folium.Map(location=[20, 10], zoom_start=3,
                             tiles='https://a.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}.png',
                             attr='CartoDB')

    for _, row in filtered.iterrows():
        color = row['Color']
        gj = folium.GeoJson(
            row.geometry,
            style_function=lambda feature, color=color: {
                'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.5
            },
        )
        folium.Popup(f"{row['DisplayName']} ({int(row['FromYear'])} to {int(row['ToYear'])})").add_to(gj)
        gj.add_to(target)

    return target, len(filtered)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('year', type=int, help='Year to display (negative for BCE)')
    ap.add_argument('--source', default=DEFAULT_SOURCE)
    ap.add_argument('--components', action='store_true',
                     help='Show lowest-level components instead of top-level polities')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    out = args.out or os.path.join(MAPPER_DIR, 'exports', f'cliopatria_quicklook_{args.year}.html')

    print(f"Loading {args.source} ...")
    gdf = gpd.read_file(args.source)
    print(f"Loaded {len(gdf)} rows. Building map for year {args.year} "
          f"({'components' if args.components else 'polities'}) ...")

    m, n = build_map(gdf, args.year, args.components)
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    m.save(out)
    set_html_lang(out)
    print(f"{n} shape(s) active in {args.year}. Wrote {out}")


if __name__ == '__main__':
    main()
