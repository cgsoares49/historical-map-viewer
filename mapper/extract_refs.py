import re, json

with open('js/geodata.js', encoding='utf-8') as f:
    text = f.read()

m = re.search(r'const GEODATA_REFS\s*=\s*\{(.*?)\};', text, re.DOTALL)
if not m:
    print('GEODATA_REFS not found'); exit()

refs = {}
for line in m.group(1).splitlines():
    lm = re.match(r"\s*'([^']+)'\s*:\s*\[(.*)\]", line)
    if lm:
        key  = lm.group(1).replace("\\'", "'")
        urls = re.findall(r"'([^']+)'", lm.group(2))
        if urls:
            refs[key] = urls

with open('refs.json', 'w', encoding='utf-8') as f:
    json.dump(refs, f, indent=2, ensure_ascii=False)
print(f'Extracted {len(refs)} entries to refs.json')
