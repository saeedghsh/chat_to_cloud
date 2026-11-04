import itertools

import pytest

from chat_to_cloud import dynamic_animation, fonts

pytestmark = pytest.mark.fonts


def test_wedged_word_moves_aside_instead_of_shrinking_the_cloud() -> None:
    # Two big words fill the canvas width and a small word sits between them,
    # where pushing alone cannot free it.
    font_path = fonts.font_path(fonts.LATIN)
    styles = {
        "alpha": dynamic_animation._WordStyle(40.0, 1.0),
        "omega": dynamic_animation._WordStyle(40.0, 1.0),
        "x": dynamic_animation._WordStyle(12.0, 1.0),
    }
    alpha_width, _ = dynamic_animation._text_dimensions("alpha", font_path, 40.0)
    omega_width, _ = dynamic_animation._text_dimensions("omega", font_path, 40.0)
    width, height, margin = int(alpha_width + omega_width + 30), 140, 2.0
    desired = {
        "alpha": (alpha_width / 2 + 6, 70.0),
        "omega": (alpha_width - 30 + omega_width / 2 + 6, 70.0),
        "x": (alpha_width + 6 - 15, 70.0),
    }

    layout = dynamic_animation._reflow_from_previous(
        {},
        styles,
        desired,
        font_path=font_path,
        width=width,
        height=height,
        margin=margin,
    )

    assert {word: item.font_size for word, item in layout.items()} == {
        word: style.font_size for word, style in styles.items()
    }
    rectangles = [
        dynamic_animation._rectangle(
            item.word, item.font_size, item.center_x, item.center_y, font_path, margin
        )
        for item in layout.values()
    ]
    for rectangle in rectangles:
        assert dynamic_animation._position_is_free(rectangle, [], width, height)
    for first, second in itertools.combinations(rectangles, 2):
        assert not dynamic_animation._rectangles_overlap(first, second)
