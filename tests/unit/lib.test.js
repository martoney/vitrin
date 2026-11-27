const { test } = require('node:test');
const assert = require('node:assert/strict');
const Lib = require('../../vitrin/files/vitrin/lib.js');

test('barPadding puts the gap across the panel and the side margin along it', () => {
    assert.deepEqual(Lib.barPadding(false, 10, 20, 0), { top: 10, right: 20, bottom: 10, left: 20 });
    assert.deepEqual(Lib.barPadding(true, 10, 20, 0), { top: 20, right: 10, bottom: 20, left: 10 });
    assert.deepEqual(Lib.barPadding(false, 0, 0, 0), { top: 0, right: 0, bottom: 0, left: 0 });
});

test('barPadding adds the inner padding on every side', () => {
    assert.deepEqual(Lib.barPadding(false, 10, 20, 4), { top: 14, right: 24, bottom: 14, left: 24 });
});

test('paddingCss orders sides like CSS', () => {
    assert.equal(Lib.paddingCss({ top: 1, right: 2, bottom: 3, left: 4 }), '1px 2px 3px 4px');
});

test('extraThickness adds the gap and inner padding on both sides, scaled', () => {
    assert.equal(Lib.extraThickness(10, 0, 1), 20);
    assert.equal(Lib.extraThickness(10, 0, 2), 40);
    assert.equal(Lib.extraThickness(10, 4, 2), 56);
    assert.equal(Lib.extraThickness(0, 0, 2), 0);
});

test('barBox insets by the gap across and the side margin along the panel', () => {
    assert.deepEqual(Lib.barBox(false, 1920, 60, 10, 30, 1), { x1: 30, y1: 10, x2: 1890, y2: 50 });
    assert.deepEqual(Lib.barBox(true, 60, 1080, 10, 30, 2), { x1: 20, y1: 60, x2: 40, y2: 1020 });
});

test('clampToContent pulls points in the margins one pixel inside the content edge', () => {
    const box = { x: 0, y: 1020, width: 1920, height: 60 };
    const pad = { top: 10, right: 26, bottom: 10, left: 26 };
    assert.deepEqual(Lib.clampToContent(0, 1079, box, pad), [27, 1068]);
    assert.deepEqual(Lib.clampToContent(1919, 1079, box, pad), [1892, 1068]);
    assert.deepEqual(Lib.clampToContent(500, 1050, box, pad), [500, 1050]);
    assert.deepEqual(Lib.clampToContent(500, 1020, box, pad), [500, 1031]);
});

test('dodge hides immediately when a window causes the hide', () => {
    const d = Lib.dodge({ mouse: false, leftAt: 0 }, { shouldShow: false, mouseEntered: false, now: 10000, hideDelay: 500 });
    assert.equal(d.hideNow, true);
});

test('dodge keeps the hide delay right after the pointer leaves the panel', () => {
    const left = Lib.dodge({ mouse: true, leftAt: 0 }, { shouldShow: false, mouseEntered: false, now: 10000, hideDelay: 500 });
    assert.equal(left.hideNow, false);
    assert.equal(left.leftAt, 10000);
    const recheck = Lib.dodge(left, { shouldShow: false, mouseEntered: false, now: 10250, hideDelay: 500 });
    assert.equal(recheck.hideNow, false);
    const later = Lib.dodge(recheck, { shouldShow: false, mouseEntered: false, now: 10600, hideDelay: 500 });
    assert.equal(later.hideNow, true);
});

test('dodge never hides when the panel should show', () => {
    const d = Lib.dodge({ mouse: false, leftAt: 0 }, { shouldShow: true, mouseEntered: true, now: 10000, hideDelay: 0 });
    assert.equal(d.hideNow, false);
    assert.equal(d.mouse, true);
});

test('dodge with no hide delay hides as soon as the pointer is gone', () => {
    const d = Lib.dodge({ mouse: true, leftAt: 0 }, { shouldShow: false, mouseEntered: false, now: 10000, hideDelay: 0 });
    assert.equal(d.hideNow, true);
});

const OPTIONS = { radius: 10, color: 'rgba(255,255,255,0.16)', roundMenu: true, attention: 'rgba(240, 74, 80, 0.75)' };

test('rgba formats a colour with the given alpha', () => {
    assert.equal(Lib.rgba({ red: 240, green: 74, blue: 80 }, 0.75), 'rgba(240, 74, 80, 0.75)');
});

test('highlightCss scopes every rule to the given panel class', () => {
    const css = Lib.highlightCss('vitrin-abc', OPTIONS);
    assert.match(css, /#panel\.vitrin-abc \.applet-box:hover,/);
    assert.match(css, /#panel\.vitrin-abc \.applet-cornerbar-box:hover,/);
    assert.match(css, /#panel\.vitrin-abc\.vitrin-glass \.grouped-window-list-item-box:focus,/);
    assert.match(css, /border-radius: 10px;/);
    assert.match(css, /background-color: rgba\(255,255,255,0\.16\);/);
    for (const selector of css.split('{').slice(0, -1).flatMap(block => block.split('}').pop().split(',')))
        assert.match(selector.trim(), /^#panel\.vitrin-abc[ .]/);
    assert.equal(css.split('{').length, css.split('}').length);
});

test('highlightCss makes the menu button round only when asked', () => {
    const capsule = /\.applet-box\.menu-cinnamon-org-applet:hover,\n[^{]*\{\n    border-radius: 999px;/;
    assert.match(Lib.highlightCss('s', OPTIONS), capsule);
    assert.doesNotMatch(Lib.highlightCss('s', { ...OPTIONS, roundMenu: false }), capsule);
});

test('highlightCss shapes attention highlights like the rest and makes them translucent', () => {
    const css = Lib.highlightCss('s', OPTIONS);
    assert.match(css, /\.grouped-window-list-item-demands-attention,\n#panel\.s \.window-list-item-demands-attention \{\n    border-radius: 10px;/);
    assert.match(css, /background-gradient-direction: none;\n    background-color: rgba\(240, 74, 80, 0\.75\);/);
    assert.doesNotMatch(Lib.highlightCss('s', { ...OPTIONS, attention: null }), /background-gradient-direction/);
});

test('highlightCss hides the Show Desktop bar until hovered', () => {
    assert.match(Lib.highlightCss('s', OPTIONS), /#panel\.s \.applet-cornerbar,\n[^{]*\{\n    background-color: transparent;/);
});

test('luminance weighs green highest and spans 0..1', () => {
    assert.equal(Lib.luminance({ red: 0, green: 0, blue: 0 }), 0);
    assert.ok(Math.abs(Lib.luminance({ red: 255, green: 255, blue: 255 }) - 1) < 1e-9);
    assert.ok(Lib.luminance({ red: 0, green: 255, blue: 0 }) > Lib.luminance({ red: 255, green: 0, blue: 255 }));
});

test('isLight switches with hysteresis', () => {
    assert.equal(Lib.isLight(false, 0.55), false);
    assert.equal(Lib.isLight(false, 0.65), true);
    assert.equal(Lib.isLight(true, 0.55), true);
    assert.equal(Lib.isLight(true, 0.45), false);
});

test('sampleBands lies inside the bar, in the inner padding, on both sides', () => {
    assert.deepEqual(Lib.sampleBands(false, { x: 0, y: 2738, width: 5120, height: 142 }, 10, 3, 2), [2763, 2854]);
    assert.deepEqual(Lib.sampleBands(true, { x: 0, y: 0, width: 60, height: 1080 }, 10, 0, 1), [10, 49]);
});

test('samplePoints spreads samples along the region on every band', () => {
    const points = Lib.samplePoints(false, { x: 100, y: 0, width: 600, height: 40 }, [5, 35], 3);
    assert.deepEqual(points, [[200, 5], [200, 35], [400, 5], [400, 35], [600, 5], [600, 35]]);
    assert.deepEqual(Lib.samplePoints(true, { x: 0, y: 0, width: 40, height: 100 }, [3], 2), [[3, 25], [3, 75]]);
});

test('highlightCss turns glyphs dark in light regions of glass panels, with shadows', () => {
    const css = Lib.highlightCss('s', { ...OPTIONS, shadow: 0.4 });
    assert.match(css, /#panel\.s\.vitrin-glass \.vitrin-light StLabel,\n#panel\.s\.vitrin-glass \.vitrin-light \.vitrin-glyph \{\n    color: rgba\(20, 20, 22, 0\.9\);\n    text-shadow: 0 1px 3px rgba\(255, 255, 255, 0\.4\);/);
    assert.match(css, /#panel\.s\.vitrin-glass StLabel,\n#panel\.s\.vitrin-glass \.vitrin-glyph \{\n    text-shadow: 0 1px 3px rgba\(0, 0, 0, 0\.4\);\n    icon-shadow: 0 1px 3px rgba\(0, 0, 0, 0\.4\);/);
    assert.match(Lib.highlightCss('s', { ...OPTIONS, shadow: 0 }), /text-shadow: none;/);
});

test('isGlyphIcon takes symbolic icons and leaves colour icons alone', () => {
    assert.equal(Lib.isGlyphIcon('system-status-icon', 'xsi-printer'), true);
    assert.equal(Lib.isGlyphIcon(null, 'blueman-tray-symbolic'), true);
    assert.equal(Lib.isGlyphIcon(null, '. GThemedIcon xsi-battery-level-70-charging-symbolic xsi-battery'), true);
    assert.equal(Lib.isGlyphIcon(null, 'firefox'), false);
    assert.equal(Lib.isGlyphIcon('applet-icon', '/usr/share/pixmaps/app.png'), false);
    assert.equal(Lib.isGlyphIcon(null, null), false);
});

test('outside drops the points a rectangle covers', () => {
    const rect = { x: 0, y: 1057, width: 1920, height: 66 };
    const points = [[100, 1025], [100, 1068], [2000, 1068], [100, 1056], [100, 1057]];
    assert.deepEqual(Lib.outside(points, rect), [[100, 1025], [2000, 1068], [100, 1056]]);
    assert.deepEqual(Lib.outside(points, { x: 0, y: 5000, width: 1, height: 1 }), points);
});

test('blurStep spreads 4 taps per sigma', () => {
    assert.equal(Lib.blurStep(3, 2), 1.5);
    assert.equal(Lib.blurStep(0, 2), 0);
});

test('glassUniforms maps settings to shader uniforms', () => {
    const c = {
        gap: 10, sideMargin: 20, radius: 12, lensWidth: 11, refraction: 0.9, fringe: 1.2,
        vibrancy: 1.15, frost: 0.04, highlight: 0.5, shadow: 0.28,
    };
    const u = Lib.glassUniforms(3840, 130, false, c, 2);
    assert.equal(u.inset_x, 40);
    assert.equal(u.inset_y, 20);
    assert.equal(u.radius, 24);
    assert.equal(u.scale, 2);
    assert.equal(u.lens, 0.9);
    assert.equal(u.rim, 0.5);
    for (const value of Object.values(u))
        assert.equal(typeof value, 'number');
});
