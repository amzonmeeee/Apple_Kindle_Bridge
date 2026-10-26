"""Only transfer highlight colors shared by Apple Books and Kindle.

Apple values: py-apple-books, models/annotation.py (AnnotationColor).
Kindle values: native json_metadata.mchl_color and clippyconvert's payloads.
"""
APPLE_TO_KINDLE = {2: 'blue', 3: 'yellow', 4: 'pink'}
KINDLE_TO_APPLE = {color: style for style, color in APPLE_TO_KINDLE.items()}


def kindle_color(style, underline=False):
    if underline:
        return 'yellow'  # Kindle's underline payload still carries a color field.
    if style not in APPLE_TO_KINDLE:
        raise ValueError('Apple highlight color has no verified Kindle equivalent')
    return APPLE_TO_KINDLE[style]


def apple_style(color, underline=False):
    if underline:
        return 0
    if color not in KINDLE_TO_APPLE:
        raise ValueError('Kindle highlight color has no verified Apple Books equivalent')
    return KINDLE_TO_APPLE[color]
