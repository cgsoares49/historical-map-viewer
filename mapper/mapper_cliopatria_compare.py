"""
mapper_cliopatria_compare.py
Overlays MAPPER's own quicklook (mapper_quicklook.py) and the Cliopatria
quicklook (cliopatria_quicklook.py) for the same year on one Leaflet map,
as two independently toggleable layers with their own opacity sliders --
for directly comparing resolution/coverage between the two datasets.

Usage:
  python mapper_cliopatria_compare.py -253
  python mapper_cliopatria_compare.py 1440 --mapper-all --out exports/compare_1440.html
"""
import os
import argparse

import folium
import geopandas as gpd

import mapper_quicklook
import cliopatria_quicklook
from quicklook_common import set_html_lang

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))


def add_opacity_controls(m, mapper_fg, cliopatria_fg):
    mapper_var = mapper_fg.get_name()
    clio_var = cliopatria_fg.get_name()
    html = f"""
    <div id="opacity-control" style="position: fixed; top: 10px; right: 10px; z-index: 9999;
         background: white; padding: 10px 14px; border-radius: 6px;
         box-shadow: 0 1px 6px rgba(0,0,0,0.4); font-family: sans-serif; font-size: 13px;
         color: #222;">
      <div style="margin-bottom:8px;">
        <button id="flip-btn" style="width:100%; padding:6px; font-size:13px; cursor:pointer;">
          Flip (space) -- showing: <span id="flip-label">Both</span>
        </button>
      </div>
      <div style="margin-bottom:8px;">
        <label>MAPPER opacity: <span id="mapper-val">80%</span></label><br>
        <input id="mapper-opacity" type="range" min="0" max="100" value="80" style="width:170px;">
      </div>
      <div>
        <label>Cliopatria opacity: <span id="clio-val">80%</span></label><br>
        <input id="clio-opacity" type="range" min="0" max="100" value="80" style="width:170px;">
      </div>
    </div>
    <script>
      window.addEventListener('load', function() {{
        function setGroupOpacity(group, v) {{
          group.eachLayer(function(layer) {{
            if (layer.setStyle) {{ layer.setStyle({{fillOpacity: v, opacity: v}}); }}
          }});
        }}
        var mapperGroup = {mapper_var};
        var clioGroup = {clio_var};
        var mapperSlider = document.getElementById('mapper-opacity');
        var clioSlider = document.getElementById('clio-opacity');
        var mapperVal = document.getElementById('mapper-val');
        var clioVal = document.getElementById('clio-val');
        var flipLabel = document.getElementById('flip-label');
        var flipShowingMapper = true;

        // Sync actual layer opacity to the sliders' starting values (the
        // style_function's default fillOpacity=0.5 wouldn't otherwise match).
        setGroupOpacity(mapperGroup, mapperSlider.value / 100);
        setGroupOpacity(clioGroup, clioSlider.value / 100);

        mapperSlider.addEventListener('input', function(e) {{
          var v = e.target.value / 100;
          setGroupOpacity(mapperGroup, v);
          mapperVal.innerText = e.target.value + '%';
        }});
        clioSlider.addEventListener('input', function(e) {{
          var v = e.target.value / 100;
          setGroupOpacity(clioGroup, v);
          clioVal.innerText = e.target.value + '%';
        }});

        function flip() {{
          flipShowingMapper = !flipShowingMapper;
          var mapperOn = flipShowingMapper ? 100 : 0;
          var clioOn = flipShowingMapper ? 0 : 100;
          mapperSlider.value = mapperOn;
          clioSlider.value = clioOn;
          setGroupOpacity(mapperGroup, mapperOn / 100);
          setGroupOpacity(clioGroup, clioOn / 100);
          mapperVal.innerText = mapperOn + '%';
          clioVal.innerText = clioOn + '%';
          flipLabel.innerText = flipShowingMapper ? 'MAPPER' : 'Cliopatria';
        }}
        document.getElementById('flip-btn').addEventListener('click', flip);
        document.addEventListener('keydown', function(e) {{
          if (e.code === 'Space' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') {{
            e.preventDefault();
            flip();
          }}
        }});
      }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(html))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('year', type=int, help='Year to display (negative for BCE)')
    ap.add_argument('--mapper-source', default=mapper_quicklook.DEFAULT_SOURCE)
    ap.add_argument('--clio-source', default=cliopatria_quicklook.DEFAULT_SOURCE)
    ap.add_argument('--mapper-type', action='append', default=None,
                     help=f'MAPPER Type(s) to include; repeatable. Default: {mapper_quicklook.DEFAULT_TYPES}')
    ap.add_argument('--mapper-all', action='store_true',
                     help='Include nested MAPPER rows too, not just top-level')
    ap.add_argument('--clio-components', action='store_true',
                     help='Show Cliopatria components instead of top-level polities')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    out = args.out or os.path.join(MAPPER_DIR, 'exports', f'compare_quicklook_{args.year}.html')
    mapper_types = args.mapper_type or mapper_quicklook.DEFAULT_TYPES

    m = folium.Map(location=[20, 10], zoom_start=3,
                    tiles='https://a.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}.png',
                    attr='CartoDB')

    clio_fg = folium.FeatureGroup(name='Cliopatria', show=True)
    mapper_fg = folium.FeatureGroup(name='MAPPER', show=True)

    print(f"Loading {args.clio_source} ...")
    gdf = gpd.read_file(args.clio_source)
    _, clio_n = cliopatria_quicklook.build_map(gdf, args.year, args.clio_components, container=clio_fg)
    print(f"Cliopatria: {clio_n} shape(s) active in {args.year}.")

    print(f"Scanning {args.mapper_source} ...")
    _, mapper_n, mapper_scanned = mapper_quicklook.build_map(
        args.mapper_source, args.year, mapper_types, args.mapper_all, container=mapper_fg)
    print(f"MAPPER: {mapper_n} shape(s) active in {args.year} (scanned {mapper_scanned} master lines).")

    # Cliopatria added first (below), MAPPER added second (drawn on top) --
    # MAPPER is the higher-resolution/authoritative layer where both have coverage.
    clio_fg.add_to(m)
    mapper_fg.add_to(m)
    add_opacity_controls(m, mapper_fg, clio_fg)
    folium.LayerControl(collapsed=False).add_to(m)

    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    m.save(out)
    set_html_lang(out)
    print(f"Wrote {out}")


if __name__ == '__main__':
    main()
