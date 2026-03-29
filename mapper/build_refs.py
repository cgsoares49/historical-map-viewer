"""
build_refs.py
Generates GEODATA_REFS Wikipedia entries for hand-curated geodata keys.
Writes the refs block into js/geodata.js, replacing any existing GEODATA_REFS.
"""

import os, re

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
GEODATA_JS = os.path.join(MAPPER_DIR, 'js', 'geodata.js')

BASE = 'https://en.wikipedia.org/wiki/'

def wiki(article):
    return BASE + article.replace(' ', '_')

# ── Hand-curated keys → Wikipedia article title ───────────────────────────────
# None = skip (no useful article or duplicate alias)
REFS = {
    # Whole world / oceans
    'world':              None,
    'earth':              None,

    # Continents
    'africa':             wiki('Africa'),
    'europe':             wiki('Europe'),
    'asia':               wiki('Asia'),
    'eurasia':            wiki('Eurasia'),
    'north america':      wiki('North America'),
    'south america':      wiki('South America'),
    'americas':           wiki('Americas'),
    'australia':          wiki('Australia (continent)'),
    'oceania':            wiki('Oceania'),
    'antarctica':         wiki('Antarctica'),

    # Ancient / Historical regions
    'mesopotamia':        wiki('Mesopotamia'),
    'fertile crescent':   wiki('Fertile Crescent'),
    'sumer':              wiki('Sumer'),
    'akkad':              wiki('Akkad (region)'),
    'babylonia':          wiki('Babylonia'),
    'babylon':            wiki('Babylon'),
    'assyria':            wiki('Assyria'),
    'nineveh':            wiki('Nineveh'),
    'ancient egypt':      wiki('Ancient Egypt'),
    'nile valley':        wiki('Nile'),
    'nubia':              wiki('Nubia'),
    'carthage':           wiki('Carthage'),
    'north africa':       wiki('North Africa'),
    'levant':             wiki('Levant'),
    'canaan':             wiki('Canaan'),
    'phoenicia':          wiki('Phoenicia'),
    'judea':              wiki('Judea'),
    'israel (ancient)':   wiki('Kingdom of Israel (united monarchy)'),
    'persia (ancient)':   wiki('Persia'),
    'achaemenid empire':  wiki('Achaemenid Empire'),
    'anatolia':           wiki('Anatolia'),
    'asia minor':         wiki('Anatolia'),
    'ancient greece':     wiki('Ancient Greece'),
    'ancient rome':       wiki('Ancient Rome'),
    'roman empire':       wiki('Roman Empire'),
    'gaul':               wiki('Gaul'),
    'britannia':          wiki('Roman Britain'),
    'iberia (ancient)':   wiki('Iberian Peninsula'),
    'germania':           wiki('Germania'),
    'scythia':            wiki('Scythia'),
    'pontic steppe':      wiki('Pontic–Caspian steppe'),
    'steppe':             wiki('Eurasian Steppe'),
    'indus valley':       wiki('Indus Valley Civilisation'),
    'ancient india':      wiki('History of India'),
    'maurya empire':      wiki('Maurya Empire'),
    'ancient china':      wiki('History of China'),
    'arabia (ancient)':   wiki('Arabian Peninsula'),
    'arabian peninsula':  wiki('Arabian Peninsula'),
    'near east':          wiki('Near East'),
    'middle east':        wiki('Middle East'),
    'caucasus':           wiki('Caucasus'),
    'central asia':       wiki('Central Asia'),
    'horn of africa':     wiki('Horn of Africa'),
    'sub-saharan africa': wiki('Sub-Saharan Africa'),
    'mali empire':        wiki('Mali Empire'),
    'byzantine empire':   wiki('Byzantine Empire'),
    'ottoman empire':     wiki('Ottoman Empire'),
    'mongol empire':      wiki('Mongol Empire'),
    'silk road':          wiki('Silk Road'),

    # Modern Countries — Europe
    'france':             wiki('France'),
    'germany':            wiki('Germany'),
    'united kingdom':     wiki('United Kingdom'),
    'great britain':      wiki('Great Britain'),
    'uk':                 None,
    'britain':            None,
    'england':            wiki('England'),
    'scotland':           wiki('Scotland'),
    'wales':              wiki('Wales'),
    'ireland':            wiki('Ireland'),
    'spain':              wiki('Spain'),
    'portugal':           wiki('Portugal'),
    'italy':              wiki('Italy'),
    'greece':             wiki('Greece'),
    'turkey':             wiki('Turkey'),
    'ukraine':            wiki('Ukraine'),
    'russia':             wiki('Russia'),
    'poland':             wiki('Poland'),
    'sweden':             wiki('Sweden'),
    'norway':             wiki('Norway'),
    'finland':            wiki('Finland'),
    'denmark':            wiki('Denmark'),
    'netherlands':        wiki('Netherlands'),
    'belgium':            wiki('Belgium'),
    'switzerland':        wiki('Switzerland'),
    'austria':            wiki('Austria'),
    'hungary':            wiki('Hungary'),
    'romania':            wiki('Romania'),
    'bulgaria':           wiki('Bulgaria'),
    'serbia':             wiki('Serbia'),
    'croatia':            wiki('Croatia'),
    'czech republic':     wiki('Czech Republic'),
    'slovakia':           wiki('Slovakia'),
    'albania':            wiki('Albania'),
    'north macedonia':    wiki('North Macedonia'),
    'bosnia':             wiki('Bosnia and Herzegovina'),
    'slovenia':           wiki('Slovenia'),
    'latvia':             wiki('Latvia'),
    'lithuania':          wiki('Lithuania'),
    'estonia':            wiki('Estonia'),
    'belarus':            wiki('Belarus'),
    'moldova':            wiki('Moldova'),
    'iceland':            wiki('Iceland'),
    'luxembourg':         wiki('Luxembourg'),

    # Modern Countries — Middle East & North Africa
    'egypt':              wiki('Egypt'),
    'israel':             wiki('Israel'),
    'palestine':          wiki('State of Palestine'),
    'jordan':             wiki('Jordan'),
    'syria':              wiki('Syria'),
    'lebanon':            wiki('Lebanon'),
    'iraq':               wiki('Iraq'),
    'iran':               wiki('Iran'),
    'saudi arabia':       wiki('Saudi Arabia'),
    'yemen':              wiki('Yemen'),
    'oman':               wiki('Oman'),
    'uae':                wiki('United Arab Emirates'),
    'kuwait':             wiki('Kuwait'),
    'qatar':              wiki('Qatar'),
    'bahrain':            wiki('Bahrain'),
    'afghanistan':        wiki('Afghanistan'),
    'pakistan':           wiki('Pakistan'),
    'morocco':            wiki('Morocco'),
    'algeria':            wiki('Algeria'),
    'libya':              wiki('Libya'),
    'tunisia':            wiki('Tunisia'),
    'sudan':              wiki('Sudan'),

    # Modern Countries — Sub-Saharan Africa
    'ethiopia':           wiki('Ethiopia'),
    'somalia':            wiki('Somalia'),
    'kenya':              wiki('Kenya'),
    'tanzania':           wiki('Tanzania'),
    'nigeria':            wiki('Nigeria'),
    'ghana':              wiki('Ghana'),
    'mali':               wiki('Mali'),
    'south africa':       wiki('South Africa'),
    'madagascar':         wiki('Madagascar'),
    'congo':              wiki('Democratic Republic of the Congo'),
    'angola':             wiki('Angola'),
    'mozambique':         wiki('Mozambique'),
    'zambia':             wiki('Zambia'),
    'zimbabwe':           wiki('Zimbabwe'),

    # Modern Countries — Asia
    'india':              wiki('India'),
    'china':              wiki('China'),
    'japan':              wiki('Japan'),
    'korea':              wiki('Korea'),
    'north korea':        wiki('North Korea'),
    'south korea':        wiki('South Korea'),
    'mongolia':           wiki('Mongolia'),
    'vietnam':            wiki('Vietnam'),
    'thailand':           wiki('Thailand'),
    'myanmar':            wiki('Myanmar'),
    'burma':              None,
    'cambodia':           wiki('Cambodia'),
    'laos':               wiki('Laos'),
    'indonesia':          wiki('Indonesia'),
    'malaysia':           wiki('Malaysia'),
    'philippines':        wiki('Philippines'),
    'uzbekistan':         wiki('Uzbekistan'),
    'kazakhstan':         wiki('Kazakhstan'),
    'georgia':            wiki('Georgia (country)'),
    'armenia':            wiki('Armenia'),
    'azerbaijan':         wiki('Azerbaijan'),
    'nepal':              wiki('Nepal'),
    'bangladesh':         wiki('Bangladesh'),
    'sri lanka':          wiki('Sri Lanka'),
    'ceylon':             None,

    # Modern Countries — Americas
    'usa':                None,
    'united states':      wiki('United States'),
    'us':                 None,
    'america':            None,
    'canada':             wiki('Canada'),
    'mexico':             wiki('Mexico'),
    'brazil':             wiki('Brazil'),
    'argentina':          wiki('Argentina'),
    'chile':              wiki('Chile'),
    'peru':               wiki('Peru'),
    'colombia':           wiki('Colombia'),
    'venezuela':          wiki('Venezuela'),
    'cuba':               wiki('Cuba'),

    # Cities & Landmarks
    'rome':               wiki('Rome'),
    'athens':             wiki('Athens'),
    'jerusalem':          wiki('Jerusalem'),
    'nineveh':            wiki('Nineveh'),
    'ur':                 wiki('Ur'),
    'babylon (city)':     wiki('Babylon'),
    'persepolis':         wiki('Persepolis'),
    'carthage (city)':    wiki('Carthage'),
    'alexandria':         wiki('Alexandria'),
    'istanbul':           wiki('Istanbul'),
    'constantinople':     wiki('Constantinople'),
    'byzantium':          wiki('Byzantium'),
    'london':             wiki('London'),
    'paris':              wiki('Paris'),
    'berlin':             wiki('Berlin'),
    'moscow':             wiki('Moscow'),
    'cairo':              wiki('Cairo'),
    'baghdad':            wiki('Baghdad'),
    'tehran':             wiki('Tehran'),
    'delhi':              wiki('Delhi'),
    'beijing':            wiki('Beijing'),
    'new york':           wiki('New York City'),
}

# ── Build JS block ─────────────────────────────────────────────────────────────
lines = []
lines.append('// ── References database ────────────────────────────────────────────────────')
lines.append('// Add URLs or citations for any GEODATA key (lowercase, apostrophes escaped).')
lines.append('// Values are arrays of strings; URLs become clickable links in the info popup.')
lines.append('const GEODATA_REFS = {')

for key, url in REFS.items():
    if url is None:
        continue
    escaped_key = key.replace("'", "\\'")
    lines.append(f"    '{escaped_key}': ['{url}'],")

lines.append('};')
lines.append('')

new_refs_block = '\n'.join(lines)

# ── Splice into geodata.js, replacing existing GEODATA_REFS ───────────────────
with open(GEODATA_JS, encoding='utf-8') as f:
    text = f.read()

# Remove existing refs block
marker = '\n// ── References database'
idx = text.find(marker)
if idx != -1:
    text = text[:idx].rstrip() + '\n'

text = text.rstrip() + '\n\n' + new_refs_block

with open(GEODATA_JS, 'w', encoding='utf-8') as f:
    f.write(text)

count = sum(1 for v in REFS.values() if v is not None)
print(f'Done. Wrote {count} Wikipedia references to geodata.js.')
