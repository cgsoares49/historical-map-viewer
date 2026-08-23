"""Small shared helper for the *_quicklook.py / *_compare.py scripts."""
import io


def set_html_lang(path, lang='en'):
    """folium's saved HTML has a bare <html> tag with no lang attribute --
    browsers then auto-detect the page language from its visible text, and a
    page that's mostly proper nouns (polity/place names) with few common
    English words is exactly what that heuristic tends to misclassify,
    triggering an unwanted "translate this page?" prompt."""
    with io.open(path, encoding='utf-8') as f:
        content = f.read()
    content = content.replace('<html>', f'<html lang="{lang}">', 1)
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(content)
