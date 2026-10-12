"""Language tags are labels, never translations or release equivalence."""
import re


# Query labels are recognized even before the corresponding catalog is loaded.
# This is a retrieval policy vocabulary, not a promise of source coverage.
QUERY_LANGUAGE_TAGS = frozenset({'en', 'ja', 'fr', 'de', 'es', 'it', 'pt', 'ko',
    'zh', 'zh-tw', 'zh-cn', 'th', 'id', 'nl', 'pl', 'ru', 'cs', 'da', 'fi', 'sv',
    'no', 'el', 'tr', 'ar', 'he', 'uk', 'vi', 'ms', 'hi', 'ro', 'hu'})


def is_query_language_tag(value):
    return value in QUERY_LANGUAGE_TAGS or (value.split('-')[0] in QUERY_LANGUAGE_TAGS and bool(re.fullmatch(r'[a-z]{2,3}(?:-[a-z0-9]{2,8})+', value)))


def normalize_language(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*', value):
        raise ValueError('invalid language tag')
    return value.lower()
