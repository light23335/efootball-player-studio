"""Editor card categories, retaining the client's original classification."""
CARD_TYPES = ('Standard', 'Featured', 'Highlight', 'Trending', 'Legendary', 'Epic', 'BigTime', 'UNKNOWN')


def editor_card_type(native_class, native_label=''):
    # Both series share a client class. The native variation label distinguishes
    # them; do not infer a series from the player name, rating or artwork.
    if native_class in ('Epic', 'BigTime') and native_label.startswith('Big Time'):
        return 'BigTime'
    if native_class=='UNKNOWN':
        label=native_label.replace(' ','').lower()
        for prefix,kind in (('bigtime','BigTime'),('epic','Epic'),('legendary','Legendary')):
            if label.startswith(prefix):return kind
    return native_class
