"""Give the finished QR image an outline other than a square.

A QR code has to stay square and complete to scan: every module carries
data, and the finder patterns in three corners are what a scanner locks
onto. So the shape here is not cut out of the code, it is drawn around
it. The code is inset, untouched and pixel-exact, into the largest
centered square that fits inside the shape, and everything outside the
shape is transparent. That transparency is what makes the saved PNG read
as a star or a hexagon instead of as a square with a drawing on it.

The room between the code and the outline is filled with random
decorative modules on the same grid as the code, so the whole shape looks
like one pattern. A scanner finds the code by its finder patterns and
reads only what lies between them, so the decoration is ignored, as long
as a thin ring of background (`QUIET_MODULES`) keeps it from touching the
code.

Adding a shape means adding one entry to `FRAME_SHAPES`: how much room it
leaves for the code is measured off the rendered shape, not worked out by
hand.
"""

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw

DEFAULT_FRAME_SHAPE = "none"

# Resolution the inscribed-square measurement runs at. High enough that a
# rounding error is a fraction of a percent, cheap enough to do at import.
MEASURE_SIZE = 600

# Modules of plain background kept between the code and the decoration.
# The standard asks for four, but a framed code is never printed next to
# other clutter, and two is what keeps the circle from looking padded.
QUIET_MODULES = 2

# Modules of plain background kept between the decoration and the
# outline, so the shape reads as a clean border around the pattern and
# no decoration is sliced in half by the edge.
EDGE_MARGIN = 1.25

# Share of decorative cells that are filled, close to what real QR data
# looks like so the decoration blends into the code.
DECORATION_DENSITY = 0.5


def _circle(draw, size):
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)


def _rounded_square(draw, size):
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size * 0.18, fill=255)


def _polygon(corners):
    """A painter for a fixed polygon, given corners in the unit square."""

    def paint(draw, size):
        draw.polygon([(x * (size - 1), y * (size - 1)) for x, y in corners], fill=255)

    return paint


def regular_polygon(sides, rotation=-math.pi / 2):
    """Corners of a regular polygon inscribed in the unit square.

    `rotation` defaults to putting the first corner straight up, which is
    what makes four sides read as a diamond rather than as a square.
    """
    step = 2 * math.pi / sides
    return tuple(
        (
            0.5 + 0.5 * math.cos(rotation + step * corner),
            0.5 + 0.5 * math.sin(rotation + step * corner),
        )
        for corner in range(sides)
    )


def star_polygon(points=5, inner_ratio=0.62):
    """Corners of a star, alternating between an outer and inner radius.

    `inner_ratio` is deliberately high: the code has to fit in the star's
    middle, and a spikier star leaves a smaller middle, which shrinks the
    code relative to the image around it.
    """
    step = math.pi / points
    corners = []
    for corner in range(points * 2):
        radius = 0.5 if corner % 2 == 0 else 0.5 * inner_ratio
        angle = -math.pi / 2 + step * corner
        corners.append((0.5 + radius * math.cos(angle), 0.5 + radius * math.sin(angle)))
    return tuple(corners)


# key -> (human label, painter taking an ImageDraw and a pixel size, or
# None to leave the plain square image alone). `none` is the default so
# that codes saved before outlines existed render unchanged.
FRAME_SHAPES = {
    "none": ("Square", None),
    "circle": ("Circle", _circle),
    "rounded": ("Rounded square", _rounded_square),
    "hexagon": ("Hexagon", _polygon(regular_polygon(6))),
    "diamond": ("Diamond", _polygon(regular_polygon(4))),
    "star": ("Star", _polygon(star_polygon())),
}


def frame_shape_choices():
    """`(key, label)` pairs for a form ChoiceField."""
    return [(key, label) for key, (label, _) in FRAME_SHAPES.items()]


def _shape_mask(frame_shape, size):
    """An `L` mask of the shape, 255 inside and 0 outside."""
    _, painter = FRAME_SHAPES[frame_shape]
    mask = Image.new("L", (size, size), 0)
    painter(ImageDraw.Draw(mask), size)
    return mask


@lru_cache(maxsize=None)
def inscribed_ratio(frame_shape):
    """Side of the largest centered square that fits inside the shape, as
    a fraction of the shape's width.

    Binary searched against the rendered mask rather than derived per
    shape, so a new outline needs an entry in `FRAME_SHAPES` and no
    geometry. A star gives back much less than a circle does, which is
    exactly why the measurement has to happen per shape.
    """
    mask = _shape_mask(frame_shape, MEASURE_SIZE)
    middle = MEASURE_SIZE // 2
    low, high = 0, middle
    while low < high:
        half = (low + high + 1) // 2
        box = (middle - half, middle - half, middle + half, middle + half)
        if mask.crop(box).getextrema()[0] == 255:
            low = half
        else:
            high = half - 1
    return 2 * low / MEASURE_SIZE


def is_framed(frame_shape):
    """Whether `frame_shape` draws an outline. Unknown keys don't."""
    _, painter = FRAME_SHAPES.get(frame_shape, FRAME_SHAPES[DEFAULT_FRAME_SHAPE])
    return painter is not None


def frame_width(frame_shape, code_width):
    """Width of the shape that fits a `code_width` code inside it.

    Works in any unit, modules or pixels. The result keeps the same parity
    as `code_width`, so the code sits exactly centered on the shape's grid.
    """
    width = math.ceil(code_width / inscribed_ratio(frame_shape))
    if (width - code_width) % 2:
        width += 1
    return width


def decoration_matrix(frame_shape, grid_width, code_width, box_size, seed):
    """A `grid_width` square matrix of random decorative modules.

    Only cells that lie wholly inside the shape, at least `EDGE_MARGIN`
    modules from its outline, can be filled, and the centered
    `code_width` square is left empty for the code itself. `seed` makes
    the pattern repeatable, so the live preview doesn't flicker while
    someone types and the saved image matches the preview.
    """
    mask = _shape_mask(frame_shape, grid_width * box_size)
    margin = round(box_size * EDGE_MARGIN)
    code_start = (grid_width - code_width) // 2
    code_cells = range(code_start, code_start + code_width)
    rng = random.Random(seed)

    def fits(row, col):
        x, y = col * box_size, row * box_size
        box = (x - margin, y - margin, x + box_size + margin, y + box_size + margin)
        return mask.crop(box).getextrema()[0] == 255

    return [
        [
            rng.random() < DECORATION_DENSITY
            and not (row in code_cells and col in code_cells)
            and fits(row, col)
            for col in range(grid_width)
        ]
        for row in range(grid_width)
    ]


def apply_frame(code, frame_shape, back_color, decoration=None):
    """Return `code` inset into `frame_shape`, transparent outside it.

    `decoration` is an image as wide as the whole shape, painted from
    `decoration_matrix`; without one the shape is filled with plain
    `back_color`. Unknown keys and `none` return the code untouched, so a
    blank form field or an older saved row still renders a plain square.
    """
    if not is_framed(frame_shape):
        return code

    code = code.convert("RGBA")
    if decoration is None:
        size = frame_width(frame_shape, code.width)
        fill = Image.new("RGBA", (size, size), tuple(back_color) + (255,))
    else:
        size = decoration.width
        fill = decoration.convert("RGBA")

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(fill, mask=_shape_mask(frame_shape, size))

    offset = (size - code.width) // 2
    canvas.paste(code, (offset, offset), code)
    return canvas
