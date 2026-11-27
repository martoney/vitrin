function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

function barPadding(vertical, gap, side, inset) {
    const across = gap + inset, along = side + inset;
    return vertical
        ? { top: along, right: across, bottom: along, left: across }
        : { top: across, right: along, bottom: across, left: along };
}

function extraThickness(gap, inset, scale) {
    return 2 * (gap + inset) * scale;
}

function barBox(vertical, width, height, gap, side, scale) {
    const across = gap * scale, along = side * scale;
    const [ix, iy] = vertical ? [across, along] : [along, across];
    return { x1: ix, y1: iy, x2: width - ix, y2: height - iy };
}

function clampToContent(x, y, box, pad) {
    return [
        clamp(x, box.x + pad.left + 1, box.x + box.width - pad.right - 2),
        clamp(y, box.y + pad.top + 1, box.y + box.height - pad.bottom - 2),
    ];
}

function dodge(state, { shouldShow, mouseEntered, now, hideDelay }) {
    const leftAt = state.mouse && !mouseEntered ? now : state.leftAt;
    return { mouse: mouseEntered, leftAt, hideNow: !shouldShow && now - leftAt >= hideDelay };
}

function luminance(c) {
    return (0.2126 * c.red + 0.7152 * c.green + 0.0722 * c.blue) / 255;
}

function isLight(wasLight, lum) {
    return wasLight ? lum > 0.5 : lum > 0.6;
}

function sampleBands(vertical, panel, gap, inset, scale) {
    const depth = Math.max(Math.round(inset * scale) - 1, 0);
    const start = vertical ? panel.x : panel.y;
    const size = vertical ? panel.width : panel.height;
    return [Math.floor(start + gap * scale + depth), Math.floor(start + size - gap * scale - 1 - depth)];
}

function samplePoints(vertical, region, bands, count) {
    const start = vertical ? region.y : region.x;
    const size = vertical ? region.height : region.width;
    const points = [];
    for (let i = 0; i < count; i++) {
        const along = Math.floor(start + (i + 0.5) * size / count);
        for (const band of bands)
            points.push(vertical ? [band, along] : [along, band]);
    }
    return points;
}

function outside(points, rect) {
    return points.filter(([x, y]) => x < rect.x || x >= rect.x + rect.width || y < rect.y || y >= rect.y + rect.height);
}

const HIGHLIGHT_STATES = [
    '.applet-box:hover', '.applet-box:checked', '.applet-cornerbar-box:hover',
    '.grouped-window-list-item-box:hover', '.grouped-window-list-item-box:focus',
    '.window-list-item-box:hover', '.window-list-item-box:groupFocus', '.window-list-item-box:focus',
    '.window-list-item-box:checked', '.window-list-item-box:active', '.window-list-item-box:running',
];

const ATTENTION_STATES = ['.grouped-window-list-item-demands-attention', '.window-list-item-demands-attention'];
const MENU_STATES = ['.applet-box.menu-cinnamon-org-applet:hover', '.applet-box.menu-cinnamon-org-applet:checked'];

const GLYPHS = ['StLabel', '.vitrin-glyph'];

function isGlyphIcon(styleClass, iconName) {
    return (styleClass ?? '').split(' ').includes('system-status-icon') || String(iconName ?? '').includes('-symbolic');
}
const DARK_GLYPH = 'rgba(20, 20, 22, 0.9)';

function glyphShadow(tone, alpha) {
    const shadow = alpha > 0 ? `0 1px 3px rgba(${tone}, ${tone}, ${tone}, ${alpha})` : 'none';
    return [`text-shadow: ${shadow}`, `icon-shadow: ${shadow}`];
}

function highlightCss(scope, { radius, color, roundMenu, attention, shadow = 0 }) {
    const panel = `#panel.${scope}`;
    const select = (prefix, states) => states.map(state => `${prefix} ${state}`).join(',\n');
    const rule = (selector, lines) => `${selector} {\n${lines.map(line => `    ${line};\n`).join('')}}\n\n`;
    let css = rule(select(panel, HIGHLIGHT_STATES.concat(ATTENTION_STATES)), [`border-radius: ${radius}px`]);
    if (roundMenu)
        css += rule(select(panel, MENU_STATES), ['border-radius: 999px']);
    css += rule(select(`${panel}.vitrin-glass`, HIGHLIGHT_STATES),
        [`background-color: ${color}`, 'background-image: none', 'border-image: none', 'box-shadow: none']);
    if (attention)
        css += rule(select(panel, ATTENTION_STATES), ['background-gradient-direction: none', `background-color: ${attention}`]);
    css += rule(select(panel, ['.applet-cornerbar', '.applet-cornerbar-box:hover > .applet-cornerbar']),
        ['background-color: transparent', 'border-color: transparent']);
    css += rule(select(panel, ['.applet-cornerbar-box:hover']), [`background-color: ${color}`]);
    css += rule(select(`${panel}.vitrin-glass`, GLYPHS), glyphShadow(0, shadow));
    css += rule(select(`${panel}.vitrin-glass .vitrin-light`, GLYPHS), [`color: ${DARK_GLYPH}`, ...glyphShadow(255, shadow)]);
    return css;
}

function glassUniforms(width, height, vertical, c, scale) {
    const box = barBox(vertical, width, height, c.gap, c.sideMargin, scale);
    return {
        width, height, scale,
        inset_x: box.x1,
        inset_y: box.y1,
        radius: c.radius * scale,
        bezel: c.lensWidth,
        lens: c.refraction,
        fringe: c.fringe,
        saturation: c.vibrancy,
        frost: c.frost,
        rim: c.highlight,
        shadow: c.shadow,
    };
}

module.exports = {
    barPadding, extraThickness, barBox, clampToContent, dodge, glassUniforms,
    highlightCss, luminance, isLight, sampleBands, samplePoints, isGlyphIcon, outside,
};
