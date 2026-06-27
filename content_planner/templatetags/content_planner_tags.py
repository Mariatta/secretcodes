from django import template

register = template.Library()


@register.inclusion_tag("content_planner/_asset.html")
def render_asset(asset, show_caption=False):
    """Render an asset card.

    Two modes: thumbnail + (edit-linked) title, optionally followed by a
    copyable caption — captions double as ready-to-paste social copy.
    """
    return {"asset": asset, "show_caption": show_caption}
