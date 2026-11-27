const { Cinnamon, Clutter, GLib, GObject, Meta, St } = imports.gi;
const Main = imports.ui.main;
const Mainloop = imports.mainloop;
const Settings = imports.ui.settings;
const PanelModule = imports.ui.panel;
const Lib = require('./lib.js');

const FORWARDED = [Clutter.EventType.BUTTON_PRESS, Clutter.EventType.SCROLL];
const POSITION_CLASS = ['panel-top', 'panel-bottom', 'panel-left', 'panel-right'];
const LIVE_KEYS = {
    'gap': 'gap', 'side-margin': 'sideMargin', 'inner-padding': 'innerPadding', 'radius': 'radius', 'shadow': 'shadow', 'blur': 'blur',
    'refraction': 'refraction', 'lens-width': 'lensWidth', 'fringe': 'fringe', 'highlight': 'highlight',
    'frost': 'frost', 'vibrancy': 'vibrancy',
    'highlight-radius': 'highlightRadius', 'highlight-color': 'highlightColor', 'round-menu': 'roundMenu',
    'adapt-glyphs': 'adaptGlyphs', 'glyph-shadow': 'glyphShadow',
};
const ATTENTION_ALPHA = 0.75;
const SAMPLES_PER_REGION = 6;
const IDLE_INTERVAL = 1000;
const DRAG_INTERVAL = 150;
const FADE = 70;
const FADE_FROM = 150;
const MEASURE_TIMEOUT = 500000;
const REBUILD_KEYS = { 'background': 'background', 'edge-buttons': 'edgeButtons', 'instant-hide': 'instantHide' };

let meta, settings, signals, pending, highlights, BlurEffect, GlassEffect;
let tickTimer = 0, soonTimer = 0, dragging = false;
const config = {};
const panels = new Map();

function init(metadata) {
    meta = metadata;
    BlurEffect = shaderEffect('blur');
    GlassEffect = shaderEffect('glass');
}

function shaderEffect(name) {
    const source = new TextDecoder().decode(GLib.file_get_contents(`${meta.path}/${name}.glsl`)[1]);
    return GObject.registerClass({
        GTypeName: `Vitrin_${name}_${GLib.uuid_string_random().replace(/-/g, '')}`,
    }, class extends Cinnamon.GLSLEffect {
        vfunc_build_pipeline() {
            this.add_glsl_snippet(Cinnamon.SnippetHook.FRAGMENT, source, 'effect_main();', true);
        }

        vfunc_paint_target(...args) {
            for (const key in this.uniforms)
                this.set_uniform_float(this.get_uniform_location(key), 1, [this.uniforms[key]]);
            super.vfunc_paint_target(...args);
        }
    });
}

function enable() {
    settings = new Settings.ExtensionSettings(config, meta.uuid);
    for (const [key, prop] of Object.entries(LIVE_KEYS))
        settings.bind(key, prop, refresh);
    for (const [key, prop] of Object.entries(REBUILD_KEYS))
        settings.bind(key, prop, rebuild);
    const repopulate = (group, actor) => {
        panels.forEach((s, panel) => s.scene && !panel._destroyed && populate(s.scene));
        soon();
        if (actor instanceof Meta.WindowActor) {
            const id = actor.connect('first-frame', () => {
                actor.disconnect(id);
                soon();
            });
        }
    };
    const drag = active => {
        dragging = active;
        restartTicks();
        soon();
    };
    signals = [
        [global.display, global.display.connect('grab-op-begin', () => drag(true))],
        [global.display, global.display.connect('grab-op-end', () => drag(false))],
        [global.workspace_manager, global.workspace_manager.connect('active-workspace-changed', soon)],
        [global.settings, global.settings.connect('changed::panels-enabled', refresh)],
        [global.stage, global.stage.connect('captured-event', (stage, event) => release(event))],
        [global.window_group, global.window_group.connect('actor-added', repopulate)],
        [global.window_group, global.window_group.connect('actor-removed', () => repopulate())],
        [global.bottom_window_group, global.bottom_window_group.connect('actor-added', repopulate)],
        [global.bottom_window_group, global.bottom_window_group.connect('actor-removed', () => repopulate())],
        [global.display, global.display.connect('restacked', () => repopulate())],
        [Main.themeManager, Main.themeManager.connect('theme-set', loadHighlights)],
    ];
    refresh();
    return { _uuid: meta.uuid, restoreDefaults };
}

function restoreDefaults() {
    for (const [key, data] of Object.entries(settings.settingsData))
        if (data?.default !== undefined)
            settings.setValue(key, data.default);
    rebuild();
}

function disable() {
    signals.forEach(([obj, id]) => obj.disconnect(id));
    stopTicks();
    unloadHighlights();
    pending = null;
    panels.forEach(detach);
    panels.clear();
    settings.finalize();
}

function rebuild() {
    panels.forEach(detach);
    panels.clear();
    refresh();
}

function attentionColor() {
    const probe = new St.Widget({ style_class: 'grouped-window-list-item-demands-attention', visible: false });
    Main.uiGroup.add_child(probe);
    const node = probe.get_theme_node();
    const [type, start] = node.get_background_gradient();
    const color = type === St.GradientType.NONE ? node.get_background_color() : start;
    probe.destroy();
    return color.alpha ? Lib.rgba(color, ATTENTION_ALPHA) : null;
}

function loadHighlights() {
    const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
    const options = {
        radius: config.highlightRadius,
        color: config.highlightColor,
        roundMenu: config.roundMenu,
        attention: attentionColor(),
        shadow: config.glyphShadow,
    };
    const key = JSON.stringify(options);
    if (highlights && highlights.theme === theme && highlights.key === key)
        return;
    unloadHighlights();
    const scope = `vitrin-${GLib.uuid_string_random().slice(0, 8)}`;
    const path = `${GLib.get_user_runtime_dir()}/${meta.uuid}-${scope}.css`;
    GLib.file_set_contents(path, Lib.highlightCss(scope, options));
    theme.load_stylesheet(path);
    highlights = { theme, path, key, scope };
    panels.forEach((s, panel) => panel._destroyed || panel.actor.add_style_class_name(scope));
}

function unloadHighlights() {
    if (!highlights)
        return;
    panels.forEach((s, panel) => panel._destroyed || panel.actor.remove_style_class_name(highlights.scope));
    highlights.theme.unload_stylesheet(highlights.path);
    GLib.unlink(highlights.path);
    highlights = null;
}

function refresh() {
    loadHighlights();
    for (const panel of panels.keys())
        if (panel._destroyed)
            panels.delete(panel);
    for (const panel of Main.panelManager.panels) {
        if (!panel || panel._destroyed)
            continue;
        const s = panels.get(panel) || attach(panel);
        const padding = Lib.barPadding(panel.is_vertical, config.gap, config.sideMargin, config.innerPadding);
        if (!s.effects) {
            s.bg.style_class = POSITION_CLASS[panel.panelPosition];
            s.bg.style = `border-radius: ${config.radius}px; box-shadow: 0 1px 6px rgba(0,0,0,${config.shadow});`;
        }
        panel.actor.set_style(`padding: ${Lib.paddingCss(padding)}; background-color: transparent; ` +
                              'background-image: none; box-shadow: none; border: none;');
        panel._moveResizePanel();
        s.bg.queue_relayout();
        if (!adapting(s))
            regions(panel).forEach(box => setLight(panel, box, false, false));
    }
    restartTicks();
    soon();
}

function adapting(s) {
    return config.adaptGlyphs && !!s.effects;
}

function regions(panel) {
    return [panel._leftBox, panel._centerBox, panel._rightBox];
}

function restartTicks() {
    stopTicks();
    tickTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, dragging ? DRAG_INTERVAL : IDLE_INTERVAL, () => {
        measureAll();
        return GLib.SOURCE_CONTINUE;
    });
}

function stopTicks() {
    for (const id of [tickTimer, soonTimer])
        if (id)
            GLib.source_remove(id);
    tickTimer = soonTimer = 0;
}

function soon() {
    if (soonTimer)
        return;
    soonTimer = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
        soonTimer = 0;
        measureAll();
        return GLib.SOURCE_REMOVE;
    });
}

function iconName(icon) {
    try {
        return icon.icon_name || (icon.gicon ? icon.gicon.to_string() : '');
    } catch (e) {
        return '';
    }
}

function glyphs(actor, out = []) {
    if (actor instanceof St.Label) {
        out.push(actor);
    } else if (actor instanceof St.Icon) {
        const glyph = Lib.isGlyphIcon(actor.get_style_class_name(), iconName(actor));
        if (glyph !== actor.has_style_class_name('vitrin-glyph'))
            glyph ? actor.add_style_class_name('vitrin-glyph') : actor.remove_style_class_name('vitrin-glyph');
        if (glyph)
            out.push(actor);
    }
    for (const child of actor.get_children())
        glyphs(child, out);
    return out;
}

function untag(actor) {
    if (actor instanceof St.Icon)
        actor.remove_style_class_name('vitrin-glyph');
    actor.get_children().forEach(untag);
}

function measureAll() {
    panels.forEach((s, panel) => {
        if (panel._destroyed || !s.effects)
            return;
        regions(panel).forEach(box => glyphs(box));
        if (busy(s) || !adapting(s) || panel._hidden || !panel.actor.visible)
            return;
        if (panel.actor.get_transition('x') || panel.actor.get_transition('y'))
            return soon();
        measure(panel, s);
    });
}

function shownOffset(panel) {
    const m = panel.monitor, a = panel.actor;
    const target = [
        [a.x, m.y],
        [a.x, m.y + m.height - a.height],
        [m.x, a.y],
        [m.x + m.width - a.width, a.y],
    ][panel.panelPosition];
    return [target[0] - a.x, target[1] - a.y];
}

function busy(s) {
    return s.measuring && GLib.get_monotonic_time() - s.measuring < MEASURE_TIMEOUT;
}

function measure(panel, s, [dx, dy] = [0, 0], fade = true) {
    const [ax, ay] = panel.actor.get_transformed_position();
    const x = ax + dx, y = ay + dy;
    const scale = global.ui_scale;
    const bands = Lib.sampleBands(panel.is_vertical, { x, y, width: panel.actor.width, height: panel.actor.height },
        config.gap, config.innerPadding, scale);
    const here = { x: ax, y: ay, width: panel.actor.width, height: panel.actor.height };
    const jobs = regions(panel).filter(box => box.width > 0 && box.height > 0).map(box => {
        const [bx, by] = box.get_transformed_position();
        const region = { x: bx + dx, y: by + dy, width: box.width, height: box.height };
        const points = Lib.samplePoints(panel.is_vertical, region, bands, SAMPLES_PER_REGION);
        return { box, points: dx || dy ? Lib.outside(points, here) : points, lum: [] };
    });
    let left = jobs.reduce((n, job) => n + job.points.length, 0);
    if (!left)
        return;
    s.measuring = GLib.get_monotonic_time();
    const generation = s.generation = (s.generation ?? 0) + 1;
    const screenshot = new Cinnamon.Screenshot();
    for (const job of jobs) {
        for (const [px, py] of job.points) {
            screenshot.pick_color(px, py, (shot, ok, color) => {
                if (ok)
                    job.lum.push(Lib.luminance(color));
                if (--left || generation !== s.generation)
                    return;
                s.measuring = 0;
                if (s.detached || !adapting(s))
                    return;
                for (const { box, lum } of jobs)
                    if (lum.length)
                        setLight(panel, box, Lib.isLight(box.has_style_class_name('vitrin-light'), lum.reduce((a, b) => a + b) / lum.length), fade);
            });
        }
    }
}

function setLight(panel, box, light, fade) {
    if (box.has_style_class_name('vitrin-light') === light)
        return;
    light ? box.add_style_class_name('vitrin-light') : box.remove_style_class_name('vitrin-light');
    if (!fade || panel._hidden)
        return;
    for (const item of glyphs(box)) {
        item.opacity = FADE_FROM;
        item.ease({ opacity: 255, duration: FADE, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
    }
}

function attach(panel) {
    const glass = config.background === 'glass';
    const bg = new St.Widget({ clip_to_allocation: glass });
    const s = { bg, ids: [], orig: panel.actor.get_style(), mouse: false, leftAt: 0 };

    if (glass) {
        s.scene = new Clutter.Actor();
        bg.add_child(s.scene);
        populate(s.scene);
        s.effects = [new GlassEffect(), new BlurEffect(), new BlurEffect()];
        s.effects.forEach(effect => bg.add_effect(effect));
        const follow = () => {
            s.scene.set_position(-panel.actor.x, -panel.actor.y);
            soon();
        };
        s.ids.push(panel.actor.connect('notify::x', follow), panel.actor.connect('notify::y', follow));
        follow();
    }
    panel.actor.insert_child_at_index(bg, 0);
    panel.actor.add_style_class_name('vitrin');
    panel.actor.add_style_class_name(highlights.scope);
    if (glass)
        panel.actor.add_style_class_name('vitrin-glass');
    s.ids.push(panel.actor.connect('allocate', (actor, box, flags) => allocate(panel, s, flags)));
    if (config.edgeButtons)
        s.ids.push(panel.actor.connect('captured-event', (actor, event) => forward(actor, event)));

    const extra = () => Lib.extraThickness(config.gap, config.innerPadding, global.ui_scale);
    panel._getScaledPanelHeight = () => PanelModule.Panel.prototype._getScaledPanelHeight.call(panel) + extra();
    panel._setPanelHeight = () => {
        const height = PanelModule.setHeightForPanel(panel) - extra();
        if (height === panel.height)
            return;
        panel.height = height;
        panel._onPanelZoneSizesChanged();
        panel.emit('size-changed', height);
    };
    if (config.instantHide) {
        panel._queueShowHidePanel = () => {
            const d = Lib.dodge(s, {
                shouldShow: panel._shouldShow,
                mouseEntered: panel._mouseEntered,
                now: Date.now(),
                hideDelay: panel._getProperty('panels-hide-delay', 'i'),
            });
            s.mouse = d.mouse;
            s.leftAt = d.leftAt;
            if (!d.hideNow)
                return PanelModule.Panel.prototype._queueShowHidePanel.call(panel);
            if (panel._showHideTimer) {
                Mainloop.source_remove(panel._showHideTimer);
                panel._showHideTimer = 0;
            }
            panel._hidePanel();
        };
    }

    panel._showPanel = () => {
        if (panel._hidden && adapting(s))
            measure(panel, s, shownOffset(panel), false);
        return PanelModule.Panel.prototype._showPanel.call(panel);
    };

    panels.set(panel, s);
    return s;
}

function detach(s, panel) {
    s.detached = true;
    if (panel._destroyed)
        return;
    s.ids.forEach(id => panel.actor.disconnect(id));
    for (const box of regions(panel)) {
        glyphs(box).forEach(item => {
            item.remove_transition('opacity');
            item.opacity = 255;
        });
        setLight(panel, box, false, false);
        untag(box);
    }
    s.bg.destroy();
    panel.actor.remove_style_class_name('vitrin');
    panel.actor.remove_style_class_name('vitrin-glass');
    if (highlights)
        panel.actor.remove_style_class_name(highlights.scope);
    delete panel._getScaledPanelHeight;
    delete panel._setPanelHeight;
    delete panel._queueShowHidePanel;
    delete panel._showPanel;
    panel.actor.set_style(s.orig);
    panel._moveResizePanel();
}

function allocate(panel, s, flags) {
    const b = panel.actor.get_allocation_box();
    const width = b.get_width(), height = b.get_height(), scale = global.ui_scale;
    let box = { x1: 0, y1: 0, x2: width, y2: height };
    if (s.effects) {
        const [glass, blurY, blurX] = s.effects;
        const step = Lib.blurStep(config.blur, scale);
        blurX.uniforms = { width, height, dx: step, dy: 0 };
        blurY.uniforms = { width, height, dx: 0, dy: step };
        blurX.enabled = blurY.enabled = step > 0;
        glass.uniforms = Lib.glassUniforms(width, height, panel.is_vertical, config, scale);
    } else {
        box = Lib.barBox(panel.is_vertical, width, height, config.gap, config.sideMargin, scale);
    }
    s.bg.allocate(new Clutter.ActorBox(box), flags);
}

function backdropActors() {
    return (global.window_group?.get_children() ?? []).flatMap(actor =>
        actor === global.bottom_window_group ? actor.get_children() : [actor])
        .filter(actor => actor === global.background_actor || actor instanceof Meta.WindowActor);
}

function populate(scene) {
    scene.destroy_all_children();
    for (const actor of backdropActors()) {
        const clone = new Clutter.Clone({ source: actor });
        clone.add_constraint(new Clutter.BindConstraint({ source: actor, coordinate: Clutter.BindCoordinate.POSITION }));
        actor.bind_property('visible', clone, 'visible', GObject.BindingFlags.SYNC_CREATE);
        scene.add_child(clone);
    }
}

function forward(actor, event) {
    const type = event.type();
    if (event.get_source() !== actor || !FORWARDED.includes(type))
        return Clutter.EVENT_PROPAGATE;
    const node = actor.get_theme_node();
    const [x, y] = actor.get_transformed_position();
    const padding = {
        top: node.get_padding(St.Side.TOP),
        right: node.get_padding(St.Side.RIGHT),
        bottom: node.get_padding(St.Side.BOTTOM),
        left: node.get_padding(St.Side.LEFT),
    };
    const [cx, cy] = Lib.clampToContent(...event.get_coords(), { x, y, width: actor.width, height: actor.height }, padding);
    const target = global.stage.get_actor_at_pos(Clutter.PickMode.REACTIVE, cx, cy);
    if (!target || target === actor || !actor.contains(target))
        return Clutter.EVENT_PROPAGATE;
    if (type === Clutter.EventType.BUTTON_PRESS)
        pending = { actor, target, button: event.get_button() };
    dispatch(actor, target, event);
    return Clutter.EVENT_STOP;
}

function release(event) {
    if (!pending || event.type() !== Clutter.EventType.BUTTON_RELEASE || event.get_button() !== pending.button)
        return Clutter.EVENT_PROPAGATE;
    const { actor, target } = pending;
    pending = null;
    dispatch(actor, target, event);
    return Clutter.EVENT_STOP;
}

function dispatch(actor, target, event) {
    for (; target && target !== actor; target = target.get_parent())
        if (target.event(event, false))
            return;
}
