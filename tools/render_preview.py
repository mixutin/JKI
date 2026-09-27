"""Render production Cairo orb states; these are not desktop screenshots."""
from pathlib import Path
import io
import sys

import cairo
from PIL import Image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from jki.orb import draw_orb
    directory = root / 'docs' / 'assets'
    directory.mkdir(parents=True, exist_ok=True)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1020, 620)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(.05, .065, .095)
    ctx.paint()
    states = [('listening', 'Listening'), ('hearing', 'Understanding'), ('working', 'Working'),
              ('attention', 'Approval needed'), ('speaking', 'Speaking'), ('muted', 'Microphone muted')]
    ctx.select_font_face('sans-serif', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(26)
    ctx.set_source_rgb(.91, .94, 1)
    ctx.move_to(30, 40)
    ctx.show_text('JKI / Jake Voice — production orb renderer')
    for i, (state, label) in enumerate(states):
        x, y = (i % 3) * 340, 60 + (i // 3) * 255
        ctx.save()
        ctx.translate(x, y)
        draw_orb(ctx, 340, 205, state, 1.2, .3)
        ctx.set_source_rgb(.91, .94, 1)
        ctx.set_font_size(18)
        width = ctx.text_extents(label).width
        ctx.move_to((340 - width) / 2, 232)
        ctx.show_text(label)
        ctx.restore()
    ctx.set_font_size(14)
    ctx.set_source_rgb(.64, .70, .79)
    ctx.move_to(30, 600)
    ctx.show_text('Deterministic renderer preview · not a native GTK screenshot or a live task')
    surface.write_to_png(str(directory / 'orb-states.png'))
    frames = []
    for i in range(36):
        frame = cairo.ImageSurface(cairo.FORMAT_ARGB32, 320, 210)
        context = cairo.Context(frame)
        context.set_source_rgb(.05, .065, .095)
        context.paint()
        draw_orb(context, 320, 210, 'working', i / 12, .25)
        stream = io.BytesIO()
        frame.write_to_png(stream)
        stream.seek(0)
        frames.append(Image.open(stream).convert('RGB'))
    frames[0].save(directory / 'working-orb.gif', save_all=True, append_images=frames[1:],
                   duration=83, loop=0, optimize=True)


if __name__ == '__main__':
    main()
