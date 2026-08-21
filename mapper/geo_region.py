"""
geo_region.py
Classifies a row's geometry into Seshat's own Region/Subregion taxonomy
(seshat-db.com/core/polities-light/ -- 10 regions, ~40 subregions), so our
GeoJSON/CSV exports can be filtered the same way Seshat's own polities can.

Method: reverse-geocode the geometry's centroid against modern country
boundaries (Natural Earth 110m admin-0, mapper/data/ne_110m_countries.geojson
-- 177 countries, fetched from the natural-earth-vector project), then map
the resolved country name to (Region, Subregion) via COUNTRY_TO_SESHAT_REGION
below. This is a coarse, modern-political approximation of a historical/
cultural geographic scheme -- the same simplification Seshat's own regions
are built on (a geographic filter, not a period-accurate political one).
Known limitation: a handful of very large countries (Russia, China, India,
USA, Canada, Brazil, Kazakhstan) genuinely span multiple Seshat subregions;
each is pinned to a single default subregion here rather than split further.

Usage:
    from geo_region import classify_region
    region, subregion = classify_region(some_shapely_geometry)
"""

import os
import json

from shapely.geometry import shape

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
COUNTRIES_PATH = os.path.join(MAPPER_DIR, 'data', 'ne_110m_countries.geojson')

# Countries with no meaningful historical-polity presence in this dataset --
# resolve to (None, None) rather than forcing a nonsensical region.
NO_REGION = {'Antarctica', 'Fr. S. Antarctic Lands'}

# Natural Earth country NAME -> (Seshat Region, Seshat Subregion).
# Taxonomy confirmed from seshat-db.com/core/polities-light/, 2026-08-21.
COUNTRY_TO_SESHAT_REGION = {
    'Afghanistan': ('Central and Northern Eurasia', 'Afghanistan'),
    'Albania': ('Europe', 'Southeastern Europe'),
    'Algeria': ('Africa', 'Maghreb'),
    'Angola': ('Africa', 'Central Africa'),
    'Argentina': ('South America and Caribbean', 'Southern South America'),
    'Armenia': ('Southwest Asia', 'Anatolia-Caucasus'),
    'Australia': ('Oceania-Australia', 'Australia'),
    'Austria': ('Europe', 'Central Europe'),
    'Azerbaijan': ('Southwest Asia', 'Anatolia-Caucasus'),
    'Bahamas': ('South America and Caribbean', 'Caribbean'),
    'Bangladesh': ('South Asia', 'Eastern South Asia'),
    'Belarus': ('Europe', 'Eastern Europe'),
    'Belgium': ('Europe', 'Western Europe'),
    'Belize': ('North America', 'Mexico'),
    'Benin': ('Africa', 'West Africa'),
    'Bhutan': ('South Asia', 'Eastern South Asia'),
    'Bolivia': ('South America and Caribbean', 'Andes'),
    'Bosnia and Herz.': ('Europe', 'Southeastern Europe'),
    'Botswana': ('Africa', 'Southern Africa'),
    'Brazil': ('South America and Caribbean', 'Amazonia'),
    'Brunei': ('Southeast Asia', 'Maritime Southeast Asia'),
    'Bulgaria': ('Europe', 'Southeastern Europe'),
    'Burkina Faso': ('Africa', 'Sahel'),
    'Burundi': ('Africa', 'East Africa'),
    'Cambodia': ('Southeast Asia', 'Mainland Southeast Asia'),
    'Cameroon': ('Africa', 'Central Africa'),
    'Canada': ('North America', 'Arctic America'),
    'Central African Rep.': ('Africa', 'Central Africa'),
    'Chad': ('Africa', 'Sahel'),
    'Chile': ('South America and Caribbean', 'Southern South America'),
    'China': ('East Asia', 'North China'),
    'Colombia': ('South America and Caribbean', 'Andes'),
    'Congo': ('Africa', 'Central Africa'),
    'Costa Rica': ('North America', 'Mexico'),
    'Croatia': ('Europe', 'Southeastern Europe'),
    'Cuba': ('South America and Caribbean', 'Caribbean'),
    'Cyprus': ('Southwest Asia', 'Levant'),
    'Czechia': ('Europe', 'Central Europe'),
    "Côte d'Ivoire": ('Africa', 'West Africa'),
    'Dem. Rep. Congo': ('Africa', 'Central Africa'),
    'Denmark': ('Europe', 'Northern Europe'),
    'Djibouti': ('Africa', 'Northeast Africa'),
    'Dominican Rep.': ('South America and Caribbean', 'Caribbean'),
    'Ecuador': ('South America and Caribbean', 'Andes'),
    'Egypt': ('Africa', 'Northeast Africa'),
    'El Salvador': ('North America', 'Mexico'),
    'Eq. Guinea': ('Africa', 'Central Africa'),
    'Eritrea': ('Africa', 'Northeast Africa'),
    'Estonia': ('Europe', 'Northern Europe'),
    'Ethiopia': ('Africa', 'Northeast Africa'),
    'Falkland Is.': ('South America and Caribbean', 'Southern South America'),
    'Fiji': ('Oceania-Australia', 'Polynesia'),
    'Finland': ('Europe', 'Northern Europe'),
    'France': ('Europe', 'Western Europe'),
    'Gabon': ('Africa', 'Central Africa'),
    'Gambia': ('Africa', 'West Africa'),
    'Georgia': ('Southwest Asia', 'Anatolia-Caucasus'),
    'Germany': ('Europe', 'Central Europe'),
    'Ghana': ('Africa', 'West Africa'),
    'Greece': ('Europe', 'Southern Europe'),
    'Greenland': ('North America', 'Arctic America'),
    'Guatemala': ('North America', 'Mexico'),
    'Guinea': ('Africa', 'West Africa'),
    'Guinea-Bissau': ('Africa', 'West Africa'),
    'Guyana': ('South America and Caribbean', 'Amazonia'),
    'Haiti': ('South America and Caribbean', 'Caribbean'),
    'Honduras': ('North America', 'Mexico'),
    'Hungary': ('Europe', 'Central Europe'),
    'Iceland': ('Europe', 'Northern Europe'),
    'India': ('South Asia', 'North India'),
    'Indonesia': ('Southeast Asia', 'Maritime Southeast Asia'),
    'Iran': ('Southwest Asia', 'Iran'),
    'Iraq': ('Southwest Asia', 'Mesopotamia'),
    'Ireland': ('Europe', 'Western Europe'),
    'Israel': ('Southwest Asia', 'Levant'),
    'Italy': ('Europe', 'Southern Europe'),
    'Jamaica': ('South America and Caribbean', 'Caribbean'),
    'Japan': ('East Asia', 'Northeast Asia'),
    'Jordan': ('Southwest Asia', 'Levant'),
    'Kazakhstan': ('Central and Northern Eurasia', 'Turkestan'),
    'Kenya': ('Africa', 'East Africa'),
    'Kosovo': ('Europe', 'Southeastern Europe'),
    'Kuwait': ('Southwest Asia', 'Arabia'),
    'Kyrgyzstan': ('Central and Northern Eurasia', 'Turkestan'),
    'Laos': ('Southeast Asia', 'Mainland Southeast Asia'),
    'Latvia': ('Europe', 'Northern Europe'),
    'Lebanon': ('Southwest Asia', 'Levant'),
    'Lesotho': ('Africa', 'Southern Africa'),
    'Liberia': ('Africa', 'West Africa'),
    'Libya': ('Africa', 'Maghreb'),
    'Lithuania': ('Europe', 'Northern Europe'),
    'Luxembourg': ('Europe', 'Western Europe'),
    'Madagascar': ('Africa', 'East Africa'),
    'Malawi': ('Africa', 'East Africa'),
    'Malaysia': ('Southeast Asia', 'Maritime Southeast Asia'),
    'Mali': ('Africa', 'Sahel'),
    'Mauritania': ('Africa', 'Sahel'),
    'Mexico': ('North America', 'Mexico'),
    'Moldova': ('Europe', 'Eastern Europe'),
    'Mongolia': ('Central and Northern Eurasia', 'Mongolia'),
    'Montenegro': ('Europe', 'Southeastern Europe'),
    'Morocco': ('Africa', 'Maghreb'),
    'Mozambique': ('Africa', 'Southern Africa'),
    'Myanmar': ('Southeast Asia', 'Mainland Southeast Asia'),
    'N. Cyprus': ('Southwest Asia', 'Levant'),
    'Namibia': ('Africa', 'Southern Africa'),
    'Nepal': ('South Asia', 'North India'),
    'Netherlands': ('Europe', 'Western Europe'),
    'New Caledonia': ('Oceania-Australia', 'New Guinea'),
    'New Zealand': ('Oceania-Australia', 'Polynesia'),
    'Nicaragua': ('North America', 'Mexico'),
    'Niger': ('Africa', 'Sahel'),
    'Nigeria': ('Africa', 'West Africa'),
    'North Korea': ('East Asia', 'Northeast Asia'),
    'North Macedonia': ('Europe', 'Southeastern Europe'),
    'Norway': ('Europe', 'Northern Europe'),
    'Oman': ('Southwest Asia', 'Arabia'),
    'Pakistan': ('South Asia', 'Pakistan'),
    'Palestine': ('Southwest Asia', 'Levant'),
    'Panama': ('North America', 'Mexico'),
    'Papua New Guinea': ('Oceania-Australia', 'New Guinea'),
    'Paraguay': ('South America and Caribbean', 'Southern South America'),
    'Peru': ('South America and Caribbean', 'Andes'),
    'Philippines': ('Southeast Asia', 'Maritime Southeast Asia'),
    'Poland': ('Europe', 'Central Europe'),
    'Portugal': ('Europe', 'Southern Europe'),
    'Puerto Rico': ('South America and Caribbean', 'Caribbean'),
    'Qatar': ('Southwest Asia', 'Arabia'),
    'Romania': ('Europe', 'Southeastern Europe'),
    'Russia': ('Central and Northern Eurasia', 'Siberia'),
    'Rwanda': ('Africa', 'East Africa'),
    'S. Sudan': ('Africa', 'Northeast Africa'),
    'Saudi Arabia': ('Southwest Asia', 'Arabia'),
    'Senegal': ('Africa', 'West Africa'),
    'Serbia': ('Europe', 'Southeastern Europe'),
    'Sierra Leone': ('Africa', 'West Africa'),
    'Slovakia': ('Europe', 'Central Europe'),
    'Slovenia': ('Europe', 'Central Europe'),
    'Solomon Is.': ('Oceania-Australia', 'New Guinea'),
    'Somalia': ('Africa', 'Northeast Africa'),
    'Somaliland': ('Africa', 'Northeast Africa'),
    'South Africa': ('Africa', 'Southern Africa'),
    'South Korea': ('East Asia', 'Northeast Asia'),
    'Spain': ('Europe', 'Southern Europe'),
    'Sri Lanka': ('South Asia', 'Sri Lanka'),
    'Sudan': ('Africa', 'Northeast Africa'),
    'Suriname': ('South America and Caribbean', 'Amazonia'),
    'Sweden': ('Europe', 'Northern Europe'),
    'Switzerland': ('Europe', 'Central Europe'),
    'Syria': ('Southwest Asia', 'Levant'),
    'Taiwan': ('East Asia', 'South China'),
    'Tajikistan': ('Central and Northern Eurasia', 'Turkestan'),
    'Tanzania': ('Africa', 'East Africa'),
    'Thailand': ('Southeast Asia', 'Mainland Southeast Asia'),
    'Timor-Leste': ('Southeast Asia', 'Maritime Southeast Asia'),
    'Togo': ('Africa', 'West Africa'),
    'Trinidad and Tobago': ('South America and Caribbean', 'Caribbean'),
    'Tunisia': ('Africa', 'Maghreb'),
    'Turkey': ('Southwest Asia', 'Anatolia-Caucasus'),
    'Turkmenistan': ('Central and Northern Eurasia', 'Turkestan'),
    'Uganda': ('Africa', 'East Africa'),
    'Ukraine': ('Central and Northern Eurasia', 'Pontic-Caspian'),
    'United Arab Emirates': ('Southwest Asia', 'Arabia'),
    'United Kingdom': ('Europe', 'Western Europe'),
    'United States of America': ('North America', 'East Coast'),
    'Uruguay': ('South America and Caribbean', 'Southern South America'),
    'Uzbekistan': ('Central and Northern Eurasia', 'Turkestan'),
    'Vanuatu': ('Oceania-Australia', 'New Guinea'),
    'Venezuela': ('South America and Caribbean', 'Amazonia'),
    'Vietnam': ('Southeast Asia', 'Mainland Southeast Asia'),
    'W. Sahara': ('Africa', 'Maghreb'),
    'Yemen': ('Southwest Asia', 'Arabia'),
    'Zambia': ('Africa', 'Southern Africa'),
    'Zimbabwe': ('Africa', 'Southern Africa'),
    'eSwatini': ('Africa', 'Southern Africa'),
}

_countries = None  # lazily loaded [(name, shapely_geom), ...]


def _load_countries():
    global _countries
    if _countries is not None:
        return _countries
    with open(COUNTRIES_PATH, encoding='utf-8') as f:
        fc = json.load(f)
    _countries = []
    for feat in fc['features']:
        name = feat['properties'].get('NAME')
        if name in NO_REGION:
            continue
        _countries.append((name, shape(feat['geometry'])))
    return _countries


def classify_region(geom):
    """Returns (Region, Subregion) for a shapely geometry, or (None, None) if
    the geometry's centroid can't be resolved to a mapped country (e.g. open
    ocean far from any coastline, or a country missing from the mapping
    table -- see COUNTRY_TO_SESHAT_REGION)."""
    if geom is None or geom.is_empty:
        return (None, None)
    countries = _load_countries()
    centroid = geom.centroid

    for name, poly in countries:
        if poly.contains(centroid):
            return COUNTRY_TO_SESHAT_REGION.get(name, (None, None))

    # Centroid didn't land inside any country polygon (open water, a
    # fragmented/coastal territory, or Natural Earth's simplified coastline
    # missing a sliver) -- fall back to nearest country by distance.
    nearest_name, nearest_dist = None, None
    for name, poly in countries:
        d = poly.distance(centroid)
        if nearest_dist is None or d < nearest_dist:
            nearest_name, nearest_dist = name, d
    if nearest_name is None:
        return (None, None)
    return COUNTRY_TO_SESHAT_REGION.get(nearest_name, (None, None))
