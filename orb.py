"""Cairo orb renderer shared by the desktop overlay and headless previews."""
import math
import cairo

PALETTES = {
    'starting': ((.46,.50,.92),(.3,.85,.94)),
    'listening': ((.32,.42,.98),(.26,.91,.92)),
    'hearing': ((.55,.38,1.0),(.30,.98,.87)),
    'working': ((.94,.42,.23),(1.0,.81,.37)),
    'speaking': ((.38,.42,1.0),(.91,.47,.90)),
    'muted': ((.34,.39,.48),(.57,.62,.68)),
    'offline': ((.66,.46,.37),(.95,.72,.43)),
    'attention': ((.83,.45,.25),(.98,.74,.35)),
    'error': ((.80,.26,.37),(.98,.59,.42)),
}


def draw_orb(ctx, width, height, state='listening', elapsed=0, level=0):
    first, second = PALETTES.get(state, PALETTES['listening'])
    cx,cy = width/2,height/2
    radius = min(width,height)*.285
    if state != 'muted':
        radius *= 1 + .022*math.sin(elapsed*2.2) + .07*level
    ctx.save()
    ctx.translate(cx,cy)
    glow = cairo.RadialGradient(0,0,radius*.7,0,0,radius*1.65)
    glow.add_color_stop_rgba(0,*first,.26)
    glow.add_color_stop_rgba(.5,*first,.09)
    glow.add_color_stop_rgba(1,*first,0)
    ctx.set_source(glow)
    ctx.arc(0,0,radius*1.7,0,math.tau)
    ctx.fill()
    # Two faint orbital rings communicate movement without spinning the window.
    for index in range(2):
        ctx.save()
        ctx.rotate(elapsed*(.12 if index == 0 else -.08)+index*.8)
        ctx.scale(1,.78+index*.15)
        ctx.set_source_rgba(*second,.16 if state != 'muted' else .07)
        ctx.set_line_width(.75)
        ctx.arc(0,0,radius*(1.24+index*.12),0,math.tau)
        ctx.stroke()
        if state != 'muted':
            ctx.set_source_rgba(*second,.7)
            ctx.arc(radius*(1.24+index*.12),0,1.6,0,math.tau)
            ctx.fill()
        ctx.restore()
    base=cairo.RadialGradient(-radius*.34,-radius*.40,radius*.05,0,0,radius)
    base.add_color_stop_rgb(0,*[min(1,x*.7+.3) for x in second])
    base.add_color_stop_rgb(.42,*first)
    base.add_color_stop_rgb(1,*[x*.16 for x in first])
    ctx.arc(0,0,radius,0,math.tau)
    ctx.set_source(base)
    ctx.fill_preserve()
    ctx.clip()
    # Flowing, translucent contour lines give the ball a liquid appearance.
    for band in range(12):
        y=-radius+band*radius/5.5
        ctx.new_path()
        for step in range(61):
            x=-radius+step*radius/30
            wave=math.sin(x/radius*2.8+elapsed*.65+band*.40)
            yy=y+wave*radius*.19*math.cos(y/(radius*1.5))
            if step == 0:ctx.move_to(x,yy)
            else:ctx.line_to(x,yy)
        ctx.set_source_rgba(*second,.14+band*.015)
        ctx.set_line_width(1.3 if band%3 else 2.2)
        ctx.stroke()
    shine=cairo.RadialGradient(-radius*.32,-radius*.48,0,-radius*.32,-radius*.48,radius*.66)
    shine.add_color_stop_rgba(0,1,1,1,.48)
    shine.add_color_stop_rgba(1,1,1,1,0)
    ctx.set_source(shine)
    ctx.paint()
    ctx.restore()
    # A restrained rim keeps the sphere crisp at all display scales.
    ctx.set_source_rgba(*second,.30)
    ctx.set_line_width(.8)
    ctx.arc(cx,cy,radius,0,math.tau)
    ctx.stroke()
