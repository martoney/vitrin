#!/usr/bin/env python3
"""Integration tests: boot isolated Cinnamon sessions on a dummy Xorg and exercise Vitrin.

Every scenario gets its own HOME, D-Bus session and X server, so the desktop running the tests is
never touched. Requires Xorg's dummy video driver (xserver-xorg-video-dummy), python3-gi and
python3-pil.

    tests/integration/run.py              run every scenario
    tests/integration/run.py NAME...      run some scenarios
    tests/integration/run.py --list       list scenarios
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UUID = 'vitrin'
FILES = ROOT / 'vitrin' / 'files' / UUID
OUT = HERE / 'out'
HIDE_DELAY = 1000

DEFAULTS = dict(res=(1920, 1080), scale=1, height=40, panels={1: 'bottom'}, autohide='false',
                show_desktop=True, wallpaper='colour', settings={})

SCENARIOS = {
    '1080p-glass': dict(),
    '768p-theme-small': dict(res=(1366, 768), height=24, show_desktop=False, settings={'background': 'theme'}),
    '1440p-top-tall': dict(res=(2560, 1440), height=56, panels={1: 'top'}),
    '4k-hidpi-autohide': dict(res=(3840, 2160), scale=2, height=45, autohide='intel'),
    '1080p-left-vertical': dict(panels={1: 'left'}, height=48),
    '1080p-side-margins': dict(settings={'gap': 16, 'side-margin': 300, 'radius': 20}),
    '1080p-two-panels': dict(panels={1: 'bottom', 2: 'top'}),
    '1080p-features-off': dict(autohide='intel', settings={'edge-buttons': False, 'instant-hide': False, 'round-menu': False}),
    '1080p-dark-no-padding': dict(wallpaper='dark', settings={'inner-padding': 0}),
    'showcase': dict(res=(2560, 1440), scale=2, wallpaper='stripes', manual=True, crop=((0, 880, 2560, 1440), (1280, 280))),
    'showcase-neon': dict(res=(2560, 1440), scale=2, wallpaper='synthwave', manual=True, crop=((0, 880, 2560, 1440), (1280, 280))),
    '1080p-white': dict(wallpaper='white'),
    '1080p-dark-timing': dict(wallpaper='dark', autohide='intel', timing=True, settings={'instant-hide': False}),
    '1440p-split-hidpi': dict(res=(2560, 1440), scale=2, wallpaper='split'),
    '1440p-hidpi-colour': dict(res=(2560, 1440), scale=2),
}

EXPECTED_LIGHT = {'white': [True, True], 'dark': [False, False], 'split': [True, False]}

JS_HELPERS = r'''
global.__vt = {
    mod() {
        const ext = imports.ui.extension.getExtension('%(uuid)s');
        return ext ? imports.misc.fileUtils.getModuleByIndex(ext.moduleIndex) : null;
    },
    list() {
        return Main.panelManager.panels.filter(p => p && !p._destroyed);
    },
    applets(p) {
        const axis = p.is_vertical ? 1 : 0;
        return [p._leftBox, p._centerBox, p._rightBox]
            .flatMap(b => b.get_children())
            .filter(c => c._applet && c.visible && c.width > 0 && c.height > 0)
            .map(c => {
                const [x, y] = c.get_transformed_position();
                return { uuid: c._applet._uuid, x, y, width: c.width, height: c.height };
            })
            .sort((a, b) => (axis ? a.y - b.y : a.x - b.x));
    },
    panels() {
        const m = this.mod();
        return this.list().map(p => {
            const mon = global.display.get_monitor_geometry(p.monitorIndex);
            const s = m && m.panels.get(p);
            const out = {
                id: p.panelId, position: p.panelPosition, vertical: p.is_vertical,
                x: p.actor.x, y: p.actor.y, width: p.actor.width, height: p.actor.height,
                thickness: p.is_vertical ? p.actor.width : p.actor.height,
                content: p.height, style: p.actor.get_style(), children: p.actor.get_n_children(),
                classes: p.actor.get_style_class_name(),
                hidden: p._hidden, scale: global.ui_scale,
                monitor: { x: mon.x, y: mon.y, width: mon.width, height: mon.height },
                applets: this.applets(p),
            };
            if (s) {
                const box = s.bg.get_allocation_box();
                out.bg = { x1: box.x1, y1: box.y1, x2: box.x2, y2: box.y2,
                           effects: s.bg.get_effects().filter(e => e.enabled).length,
                           clones: s.scene ? s.scene.get_n_children() : 0 };
                const c = s.bg.get_theme_node().get_background_color();
                out.bg.color = [c.red, c.green, c.blue, c.alpha];
            }
            return out;
        });
    },
    errors() {
        return (Main._errorLogStack || [])
            .filter(e => e.category === 'error' && /vitrin/i.test(e.message))
            .map(e => e.message);
    },
    hoverStyle(x, y) {
        const actor = global.stage.get_actor_at_pos(imports.gi.Clutter.PickMode.REACTIVE, x, y);
        let box = actor;
        while (box && !box._applet)
            box = box.get_parent();
        if (!box)
            return null;
        const node = box.get_theme_node();
        const c = node.get_background_color();
        return { hover: box.has_style_pseudo_class('hover'), radius: node.get_border_radius(imports.gi.St.Corner.TOPLEFT),
                 height: box.height, background: [c.red, c.green, c.blue, c.alpha] };
    },
    glyphs(p) {
        const light = [p._leftBox, p._rightBox].map(b => b.has_style_class_name('vitrin-light'));
        const calendar = p._rightBox.get_children().find(c => c._applet && c._applet._uuid === 'calendar@cinnamon.org');
        const find = a => a instanceof imports.gi.St.Label ? a : a.get_children().map(find).find(Boolean);
        const label = calendar && find(calendar);
        const c = label && label.get_theme_node().get_foreground_color();
        const icons = [];
        const walk = a => {
            if (a instanceof imports.gi.St.Icon) {
                const fg = a.get_theme_node().get_foreground_color();
                let name = a.icon_name || '';
                try { name = name || (a.gicon ? a.gicon.to_string() : ''); } catch (e) {}
                icons.push({ name: String(name), glyph: a.has_style_class_name('vitrin-glyph'),
                             fg: [fg.red, fg.green, fg.blue], opacity: a.opacity });
            }
            a.get_children().forEach(walk);
        };
        [p._leftBox, p._rightBox].forEach(walk);
        return { light, clock: c ? [c.red, c.green, c.blue] : null, icons };
    },
    light(p) {
        return [p._leftBox, p._rightBox].some(b => b.has_style_class_name('vitrin-light'));
    },
    poll(done, record) {
        const t0 = Date.now();
        imports.mainloop.timeout_add(2, () => {
            if (done()) {
                record(Date.now());
                return false;
            }
            return Date.now() - t0 < 5000;
        });
    },
    armFirstFrame() {
        const p = this.list()[0];
        global.__timing = {};
        const id = global.display.connect('window-created', (d, win) => {
            global.display.disconnect(id);
            const actor = win.get_compositor_private();
            const ff = actor.connect('first-frame', () => {
                actor.disconnect(ff);
                global.__timing.frame = Date.now();
                this.poll(() => this.light(p), t => global.__timing.light = t);
            });
        });
    },
    showDark() {
        const p = this.list()[0];
        [p._leftBox, p._rightBox].forEach(b => b.remove_style_class_name('vitrin-light'));
        global.__timing = { show: Date.now() };
        this.poll(() => this.light(p), t => global.__timing.light = t);
        p._showPanel();
    },
    addTrayGlyph() {
        const p = this.list()[0];
        const icon = new imports.gi.St.Icon({ icon_name: 'dialog-information-symbolic', icon_size: 16 });
        p._rightBox.insert_child_at_index(icon, 0);
        global.__trayGlyph = icon;
    },
    attentionStyle() {
        const find = actor => actor.has_style_class_name?.('grouped-window-list-item-box')
            ? actor : actor.get_children().map(find).find(Boolean);
        const item = this.list().map(p => find(p._leftBox)).find(Boolean);
        if (!item)
            return null;
        item.add_style_class_name('grouped-window-list-item-demands-attention');
        const node = item.get_theme_node();
        const c = node.get_background_color();
        const out = { radius: node.get_border_radius(imports.gi.St.Corner.TOPLEFT), gradient: node.get_background_gradient()[0],
                      background: [c.red, c.green, c.blue, c.alpha] };
        item.remove_style_class_name('grouped-window-list-item-demands-attention');
        return out;
    },
    pointer() {
        if (!global.__vp) {
            const C = imports.gi.Clutter;
            global.__vp = C.get_default_backend().get_default_seat().create_virtual_device(C.InputDeviceType.POINTER_DEVICE);
        }
        return global.__vp;
    },
    move(x, y) {
        this.pointer().notify_absolute_motion(global.get_current_time() * 1000, x, y);
    },
    click() {
        const C = imports.gi.Clutter;
        const t = global.get_current_time() * 1000;
        this.pointer().notify_button(t, C.BUTTON_PRIMARY, C.ButtonState.PRESSED);
        this.pointer().notify_button(t + 50000, C.BUTTON_PRIMARY, C.ButtonState.RELEASED);
    },
    arm() {
        global.__hits = [];
        for (const p of this.list())
            for (const box of [p._leftBox, p._centerBox, p._rightBox])
                for (const c of box.get_children())
                    if (c._applet) {
                        const ap = c._applet;
                        ap.on_applet_clicked = () => global.__hits.push(ap._uuid);
                    }
    },
    disarm() {
        for (const p of this.list())
            for (const box of [p._leftBox, p._centerBox, p._rightBox])
                for (const c of box.get_children())
                    if (c._applet)
                        delete c._applet.on_applet_clicked;
        return global.__hits;
    },
    armDodge() {
        const p = this.list().find(x => x._autohideSettings === 'intel');
        global.__dodge = { t0: 0, t1: 0 };
        const id = global.display.connect('window-created', () => {
            global.display.disconnect(id);
            global.__dodge.t0 = Date.now();
            imports.mainloop.timeout_add(5, () => {
                if (p._hidden) {
                    global.__dodge.t1 = Date.now();
                    return false;
                }
                return Date.now() - global.__dodge.t0 < 5000;
            });
        });
    },
};
'ok';
''' % {'uuid': UUID}

WALLPAPER_PY = '''
import sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk
w = Gtk.Window(title="vitrin-wallpaper")
w.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
w.set_decorated(False)
w.add(Gtk.Image.new_from_file(sys.argv[1]))
w.move(0, 0)
w.show_all()
Gtk.main()
'''

WINDOW_PY = '''
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
w = Gtk.Window(title="vitrin-test")
w.maximize()
w.connect("destroy", Gtk.main_quit)
w.show_all()
Gtk.main()
'''


def scenario(name):
    sc = dict(DEFAULTS)
    sc.update(SCENARIOS[name])
    return sc


def applets(panel_id, show_desktop):
    base = panel_id * 10
    out = [f'panel{panel_id}:left:0:menu@cinnamon.org:{base}',
           f'panel{panel_id}:left:1:grouped-window-list@cinnamon.org:{base + 1}',
           f'panel{panel_id}:right:0:calendar@cinnamon.org:{base + 2}']
    if show_desktop:
        out.append(f'panel{panel_id}:right:1:cornerbar@cinnamon.org:{base + 3}')
    return out


def gset(schema, key, value):
    subprocess.run(['gsettings', 'set', schema, key, value], check=True)


def strv(items):
    return '[' + ', '.join(f"'{i}'" for i in items) + ']'


def free_display():
    for n in range(90, 200):
        if not Path(f'/tmp/.X11-unix/X{n}').exists() and not Path(f'/tmp/.X{n}-lock').exists():
            return n
    raise RuntimeError('no free X display')


def make_wallpaper(path, w, h, kind):
    from PIL import Image, ImageDraw, ImageFilter
    import showcase
    if kind in showcase.WALLPAPERS:
        showcase.WALLPAPERS[kind](path, w, h)
        return
    if kind in ('dark', 'white', 'split'):
        image = Image.new('RGB', (w, h), (8, 9, 11) if kind == 'dark' else (245, 245, 245))
        if kind == 'split':
            image.paste((8, 9, 11), (w // 2, 0, w, h))
        image.save(path)
        return
    small = Image.new('RGB', (160, 90))
    px = small.load()
    for y in range(90):
        for x in range(160):
            px[x, y] = (int(40 + 180 * x / 159), int(70 + 120 * y / 89), int(210 - 120 * x / 159))
    draw = ImageDraw.Draw(small)
    for cx, cy, r, c in [(30, 70, 22, (250, 190, 60)), (110, 20, 26, (240, 80, 120)), (140, 80, 18, (80, 220, 200))]:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    small.filter(ImageFilter.GaussianBlur(4)).resize((w, h), Image.BICUBIC).save(path)


def start_xorg(tmp, w, h):
    for refresh in (60, 50, 40, 30, 24, 20, 15):
        out = subprocess.run(['cvt', str(w), str(h), str(refresh)], capture_output=True, text=True, check=True).stdout
        modeline = next(l for l in out.splitlines() if l.startswith('Modeline'))
        if float(modeline.split()[2]) < 300:
            break
    timings = modeline.split('"', 2)[2].split()
    timings[1], timings[5] = str(w), str(h)
    modeline = 'Modeline "vitrin" ' + ' '.join(timings)
    (tmp / 'xorg.conf').write_text(f'''
Section "ServerFlags"
  Option "AutoAddDevices" "false"
  Option "AutoAddGPU" "false"
EndSection
Section "Device"
  Identifier "dummy"
  Driver "dummy"
  VideoRam {max(256000, w * h * 4 * 3 // 1024)}
EndSection
Section "Monitor"
  Identifier "monitor"
  HorizSync 5.0-1000.0
  VertRefresh 5.0-200.0
  {modeline}
EndSection
Section "Screen"
  Identifier "screen"
  Device "dummy"
  Monitor "monitor"
  DefaultDepth 24
  SubSection "Display"
    Depth 24
    Modes "vitrin"
  EndSubSection
EndSection
''')
    n = free_display()
    proc = subprocess.Popen(['/usr/lib/xorg/Xorg', f':{n}', '-config', 'xorg.conf', '-logfile', str(tmp / 'xorg.log'),
                             '-noreset', '-nolisten', 'tcp'], cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if Path(f'/tmp/.X11-unix/X{n}').exists():
            return proc, f':{n}'
        time.sleep(0.1)
    raise RuntimeError('Xorg did not start')


class Cinnamon:
    def __init__(self):
        from gi.repository import Gio
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def eval(self, code):
        from gi.repository import GLib
        ok, out = self.bus.call_sync('org.Cinnamon', '/org/Cinnamon', 'org.Cinnamon', 'Eval',
                                     GLib.Variant('(s)', (code,)), GLib.VariantType('(bs)'), 0, 10000, None).unpack()
        if not ok:
            raise RuntimeError(f'Eval failed: {out}\n{code}')
        return json.loads(out) if out else None

    def update_setting(self, key, value):
        from gi.repository import GLib
        self.bus.call_sync('org.Cinnamon', '/org/Cinnamon', 'org.Cinnamon', 'updateSetting',
                           GLib.Variant('(ssss)', (UUID, UUID, key, json.dumps(value))), None, 0, 10000, None)

    def activate_callback(self, name):
        from gi.repository import GLib
        self.bus.call_sync('org.Cinnamon', '/org/Cinnamon', 'org.Cinnamon', 'activateCallback',
                           GLib.Variant('(sss)', (name, UUID, UUID)), None, 0, 10000, None)

    def wait(self, code, timeout=20.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                value = self.eval(code)
                if value:
                    return value
            except Exception:
                pass
            time.sleep(0.2)
        raise TimeoutError(code)


class Checks:
    def __init__(self):
        self.results = []

    def check(self, name, ok, detail=''):
        self.results.append({'check': name, 'ok': bool(ok), 'detail': detail})
        return ok


def dist(a, b):
    return max(abs(int(x) - int(y)) for x, y in zip(a[:3], b[:3]))


def write_settings(cin, home, values):
    """Change settings the way the settings window does: rewrite the file, then notify Cinnamon."""
    path = home / '.config' / 'cinnamon' / 'spices' / UUID / f'{UUID}.json'
    data = json.loads(path.read_text())
    for key, value in values.items():
        data[key]['value'] = value
    path.write_text(json.dumps(data, indent=4))
    for key, value in values.items():
        cin.update_setting(key, value)


def settings_value(key, values):
    schema = json.loads((FILES / 'settings-schema.json').read_text())
    return values.get(key, schema[key]['default'])


def edge_corners(p):
    x0, y0 = p['x'], p['y']
    x1, y1 = p['x'] + p['width'] - 1, p['y'] + p['height'] - 1
    return {0: [(x0, y0), (x1, y0)], 1: [(x0, y1), (x1, y1)], 2: [(x0, y0), (x0, y1)], 3: [(x1, y0), (x1, y1)]}[p['position']]


def bar_samples(p):
    """Points along the middle of the bar that no applet covers."""
    apps = p['applets']
    if p['vertical']:
        lo = max([a['y'] + a['height'] for a in apps if a['y'] < p['y'] + p['height'] / 2], default=p['y'])
        hi = min([a['y'] for a in apps if a['y'] >= p['y'] + p['height'] / 2], default=p['y'] + p['height'])
        mid = p['x'] + p['width'] // 2
        return [(mid, int(lo + (hi - lo) * f)) for f in (0.3, 0.5, 0.7)]
    lo = max([a['x'] + a['width'] for a in apps if a['x'] < p['x'] + p['width'] / 2], default=p['x'])
    hi = min([a['x'] for a in apps if a['x'] >= p['x'] + p['width'] / 2], default=p['x'] + p['width'])
    mid = p['y'] + p['height'] // 2
    return [(int(lo + (hi - lo) * f), mid) for f in (0.3, 0.5, 0.7)]


def run_scenario(name, tmp):
    from PIL import Image
    sc = scenario(name)
    w, h = sc['res']
    home = Path(os.environ['HOME'])
    checks = Checks()
    procs = []
    try:
        make_wallpaper(tmp / 'wall.png', w, h, sc['wallpaper'])
        ext_dir = home / '.local' / 'share' / 'cinnamon' / 'extensions'
        ext_dir.mkdir(parents=True)
        (ext_dir / UUID).symlink_to(FILES)

        ids = sorted(sc['panels'])
        gset('org.cinnamon', 'panels-enabled', strv(f'{i}:0:{sc["panels"][i]}' for i in ids))
        gset('org.cinnamon', 'panels-height', strv(f'{i}:{sc["height"]}' for i in ids))
        gset('org.cinnamon', 'panels-autohide', strv(f'{i}:{sc["autohide"]}' for i in ids))
        gset('org.cinnamon', 'panels-hide-delay', strv(f'{i}:{HIDE_DELAY}' for i in ids))
        gset('org.cinnamon', 'panels-show-delay', strv(f'{i}:0' for i in ids))
        gset('org.cinnamon', 'enabled-applets', strv(a for i in ids for a in applets(i, sc['show_desktop'] and i == ids[0])))
        gset('org.cinnamon', 'enabled-extensions', '[]')
        gset('org.cinnamon', 'hotcorner-layout', strv(['expo:false:0', 'scale:false:0', 'scale:false:0', 'desktop:false:0']))
        gset('org.cinnamon', 'startup-animation', 'false')
        gset('org.cinnamon.desktop.interface', 'scaling-factor', f'uint32 {sc["scale"]}')

        xorg, display = start_xorg(tmp, w, h)
        procs.append(xorg)
        env = dict(os.environ, DISPLAY=display, GDK_SCALE='1')
        log = open(tmp / 'cinnamon.log', 'w')
        procs.append(subprocess.Popen(['cinnamon'], env=env, stdout=log, stderr=log))

        cin = Cinnamon()
        cin.wait('imports.ui.appletManager.appletsLoaded === true', 60)
        procs.append(subprocess.Popen([sys.executable, '-c', WALLPAPER_PY, str(tmp / 'wall.png')], env=env, stdout=log, stderr=log))
        cin.wait('global.bottom_window_group.get_n_children() > 0', 20)
        time.sleep(2)
        cin.eval(JS_HELPERS)
        before = cin.eval('global.__vt.panels()')

        gset('org.cinnamon', 'enabled-extensions', strv([UUID]))
        cin.wait('global.__vt.mod() !== null && global.__vt.mod().panels.size > 0')
        settings_file = home / '.config' / 'cinnamon' / 'spices' / UUID / f'{UUID}.json'
        for _ in range(50):
            if settings_file.exists():
                break
            time.sleep(0.1)
        if sc['settings']:
            write_settings(cin, home, sc['settings'])
            key, value = next(iter(sc['settings'].items()))
            prop = key.split('-')[0] + ''.join(part.title() for part in key.split('-')[1:])
            cin.wait(f'JSON.stringify(global.__vt.mod().config["{prop}"]) === {json.dumps(json.dumps(value))}')
        time.sleep(1.5)

        gap = settings_value('gap', sc['settings'])
        pad = settings_value('inner-padding', sc['settings'])
        glass = settings_value('background', sc['settings']) == 'glass'
        scale = sc['scale']
        after = cin.eval('global.__vt.panels()')
        mon = after[0]['monitor']
        checks.check('resolution', (mon['width'], mon['height']) == (w, h), f'{mon["width"]}x{mon["height"]}')
        checks.check('loaded', len(after) == len(sc['panels']), f'{len(after)} panels')
        checks.check('no-errors', not cin.eval('global.__vt.errors()'), str(cin.eval('global.__vt.errors()')))

        for b, p in zip(before, after):
            tag = f'panel{p["id"]}'
            checks.check(f'{tag}-thickness', p['thickness'] == b['thickness'] + 2 * (gap + pad) * scale,
                         f'{b["thickness"]} -> {p["thickness"]} (gap {gap}, inner padding {pad}, scale {scale})')
            checks.check(f'{tag}-style-class', 'vitrin' in p['classes'].split() and ('vitrin-glass' in p['classes'].split()) == glass,
                         p['classes'])
            checks.check(f'{tag}-icon-size-unchanged', p['content'] == b['content'], f'{b["content"]} -> {p["content"]}')
            m = p['monitor']
            at_edge = {0: p['y'] == m['y'], 1: p['y'] + p['height'] == m['y'] + m['height'],
                       2: p['x'] == m['x'], 3: p['x'] + p['width'] == m['x'] + m['width']}[p['position']]
            checks.check(f'{tag}-at-edge', at_edge or p['hidden'], f'x={p["x"]} y={p["y"]}')
            checks.check(f'{tag}-background', p['bg']['effects'] == (3 if glass and settings_value('blur', sc['settings']) > 0 else 1 if glass else 0)
                         and (p['bg']['clones'] > 0) == glass, json.dumps(p['bg']))

        shot = tmp / 'shot.png'
        subprocess.run(['import', '-display', display, '-window', 'root', str(shot)], check=True)
        OUT.mkdir(exist_ok=True)
        shutil.copy(shot, OUT / f'{name}.png')
        if sc.get('crop'):
            box, size = sc['crop']
            Image.open(shot).convert('RGB').crop(box).resize(size, Image.LANCZOS).save(OUT / f'{name}-crop.png')
        image = Image.open(shot).convert('RGB')
        wall = Image.open(tmp / 'wall.png').convert('RGB')
        for p in after:
            tag = f'panel{p["id"]}'
            if p['hidden']:
                continue
            corner = edge_corners(p)[0]
            checks.check(f'{tag}-corner-shows-wallpaper', dist(image.getpixel(corner), wall.getpixel(corner)) <= 30,
                         f'{image.getpixel(corner)} vs {wall.getpixel(corner)}')
            samples = bar_samples(p)
            if glass:
                diffs = [dist(image.getpixel(s), wall.getpixel(s)) for s in samples]
                if sc['wallpaper'] == 'colour':
                    checks.check(f'{tag}-glass-tints-backdrop', all(2 <= d <= 90 for d in diffs), f'diffs {diffs} at {samples}')
                    cross = int(gap * scale)
                    thickness = p['thickness']
                    offsets = [cross + i for i in range(4)] + [thickness - 1 - cross - i for i in range(4)]
                    rim = [(p['x'] + o, s[1]) if p['vertical'] else (s[0], p['y'] + o) for s in samples for o in offsets]
                    rim_diffs = [dist(image.getpixel(pt), wall.getpixel(pt)) for pt in rim]
                    checks.check(f'{tag}-no-colour-lines-on-rim', all(d <= 100 for d in rim_diffs),
                                 f'worst {max(rim_diffs)} at {rim[rim_diffs.index(max(rim_diffs))]}')
                else:
                    checks.check(f'{tag}-glass-follows-backdrop', all(d <= 60 for d in diffs), f'diffs {diffs} at {samples}')
                if sc['wallpaper'] == 'dark':
                    inner = int(gap * scale) + 1
                    rim = (p['x'] + inner, samples[1][1]) if p['vertical'] else (samples[1][0], p['y'] + inner)
                    checks.check(f'{tag}-no-bright-outline', dist(image.getpixel(rim), wall.getpixel(rim)) <= 40,
                                 f'rim {image.getpixel(rim)} vs wallpaper {wall.getpixel(rim)} at {rim}')
            else:
                color = p['bg']['color']
                diffs = [dist(image.getpixel(s), color) for s in samples]
                checks.check(f'{tag}-theme-colour', all(d <= 12 for d in diffs), f'diffs {diffs} to {color}')
                x1 = p['x'] + int(p['bg']['x1'])
                y1 = p['y'] + int(p['bg']['y1'])
                px = image.getpixel((x1, y1))
                checks.check(f'{tag}-rounded-corner', dist(px, wall.getpixel((x1, y1))) < dist(px, color),
                             f'{px} wall {wall.getpixel((x1, y1))} bar {color}')

        edge_buttons = settings_value('edge-buttons', sc['settings'])
        for p in after:
            tag = f'panel{p["id"]}'
            if p['hidden'] or not p['applets']:
                continue
            for corner, applet in zip(edge_corners(p), (p['applets'][0], p['applets'][-1])):
                cin.eval('global.__vt.arm(); global.__vt.move(%d, %d)' % corner)
                time.sleep(0.4)
                cin.eval('global.__vt.click()')
                time.sleep(0.4)
                hits = cin.eval('global.__vt.disarm()')
                expected = [applet['uuid']] if edge_buttons else []
                checks.check(f'{tag}-corner-click-{corner[0]}x{corner[1]}', hits == expected, f'hits {hits}, expected {expected}')
            for applet in (p['applets'][0], p['applets'][-1]):
                cin.eval('global.__vt.move(%d, %d)' % (applet['x'] + applet['width'] // 2, applet['y'] + applet['height'] // 2))
                time.sleep(0.4)
                style = cin.eval('global.__vt.hoverStyle(%d, %d)' % (applet['x'] + applet['width'] // 2, applet['y'] + applet['height'] // 2))
                round_menu = applet['uuid'] == 'menu@cinnamon.org' and settings_value('round-menu', sc['settings'])
                radius = 999 if round_menu else settings_value('highlight-radius', sc['settings'])
                ok = style and style['hover'] and style['radius'] == radius * scale
                if glass and applet['uuid'] != 'cornerbar@cinnamon.org':
                    ok = ok and style['background'][:3] == [255, 255, 255] and 30 <= style['background'][3] <= 50
                checks.check(f'{tag}-hover-capsule-{applet["uuid"]}', ok, json.dumps(style))
        cin.eval('global.__vt.move(%d, %d)' % (w // 2, h // 2))

        attention = cin.eval('global.__vt.attentionStyle()')
        checks.check('attention-highlight', attention and attention['radius'] == settings_value('highlight-radius', sc['settings']) * scale
                     and attention['gradient'] == 0 and 180 <= attention['background'][3] <= 200, json.dumps(attention))

        expected_light = EXPECTED_LIGHT.get(sc['wallpaper']) if glass else [False, False]
        if expected_light is not None and sc['panels'][min(sc['panels'])] in ('bottom', 'top'):
            code = f'JSON.stringify(global.__vt.glyphs(global.__vt.list()[0]).light) === {json.dumps(json.dumps(expected_light))}'
            try:
                cin.wait(code, 5)
            except TimeoutError:
                pass
            glyphs = cin.eval('global.__vt.glyphs(global.__vt.list()[0])')
            ok = glyphs['light'] == expected_light
            if glyphs['clock']:
                dark = max(glyphs['clock']) < 60
                ok = ok and dark == expected_light[1]
            checks.check('adaptive-glyphs', ok, f'{json.dumps(glyphs)}, expected light {expected_light}')
            if sc['wallpaper'] == 'white':
                cin.eval('global.__vt.addTrayGlyph()')
                time.sleep(1.5)
                icons = cin.eval('global.__vt.glyphs(global.__vt.list()[0])')['icons']
                tray = [i for i in icons if i['name'] == 'dialog-information-symbolic']
                colour = [i for i in icons if i['name'] and '-symbolic' not in i['name']]
                checks.check('untagged-symbolic-icon-adapts', tray and tray[0]['glyph'] and max(tray[0]['fg']) < 60, json.dumps(tray))
                checks.check('colour-icons-untouched', colour and not any(i['glyph'] for i in colour), json.dumps(colour))
                checks.check('no-glyph-left-faded', all(i['opacity'] == 255 for i in icons), json.dumps(icons))
                cin.eval('global.__trayGlyph.destroy()')

        if sc.get('timing'):
            first_frame = []
            for _ in range(3):
                cin.eval('global.__vt.armFirstFrame()')
                window = subprocess.Popen([sys.executable, '-c', WINDOW_PY], env=env, stdout=log, stderr=log)
                procs.append(window)
                timing = cin.wait('global.__timing.light ? global.__timing : null', 5)
                first_frame.append(timing['light'] - timing['frame'])
                if first_frame[-1] < 250:
                    break
                window.terminate()
                window.wait()
                cin.wait('global.__vt.list().every(p => !p._hidden && !global.__vt.light(p))', 10)
            else:
                window = subprocess.Popen([sys.executable, '-c', WINDOW_PY], env=env, stdout=log, stderr=log)
                procs.append(window)
            checks.check('switch-after-first-frame', min(first_frame) < 250,
                         f'{first_frame} ms after the window first drew; best of up to 3 attempts, since a CPU-rendered desktop under load can miss once')
            cin.wait('global.__vt.list()[0]._hidden', 5)
            attempts = []
            for _ in range(3):
                cin.eval('global.__vt.showDark()')
                timing = cin.wait('global.__timing.light ? global.__timing : null', 5)
                attempts.append(timing['light'] - timing['show'])
                if attempts[-1] < 100:
                    break
                cin.eval('global.__vt.list()[0]._hidePanel()')
                cin.wait('global.__vt.list()[0]._hidden', 5)
                time.sleep(0.4)
            checks.check('ready-when-sliding-in', min(attempts) < 100,
                         f'{attempts} ms after the panel started to show; best of up to 3 attempts, since a CPU-rendered desktop under load can miss once')
            window.terminate()
            window.wait()
            cin.wait('global.__vt.list().every(p => !p._hidden)', 5)

        if sc['autohide'] == 'intel':
            instant = settings_value('instant-hide', sc['settings'])
            time.sleep(HIDE_DELAY / 1000 + 0.5)
            cin.eval('global.__vt.armDodge()')
            window = subprocess.Popen([sys.executable, '-c', WINDOW_PY], env=env, stdout=log, stderr=log)
            procs.append(window)
            dodge = cin.wait('global.__dodge.t1 ? global.__dodge : null', 10)
            took = dodge['t1'] - dodge['t0']
            if instant:
                checks.check('dodge-instant', took < HIDE_DELAY - 100, f'hid {took} ms after the window appeared')
            else:
                checks.check('dodge-uses-delay', took >= HIDE_DELAY, f'hid {took} ms after the window appeared')
            window.terminate()
            window.wait()
            cin.wait('global.__vt.list().every(p => !p._hidden)', 5)
            checks.check('dodge-shows-again', True)

        cin.wait('global.__vt.list().every(p => !p.actor.get_transition("x") && !p.actor.get_transition("y"))', 5)
        positions = [(a['x'], a['y']) for p in cin.eval('global.__vt.panels()') for a in p['applets']]
        write_settings(cin, home, {'radius': settings_value('radius', sc['settings']) + 8})
        time.sleep(0.8)
        moved = [(a['x'], a['y']) for p in cin.eval('global.__vt.panels()') for a in p['applets']]
        checks.check('radius-keeps-buttons-in-place', moved == positions, f'{positions} -> {moved}')

        new_gap = gap + 6
        write_settings(cin, home, {'gap': new_gap})
        expected = [b['thickness'] + 2 * (new_gap + pad) * scale for b in before]
        try:
            cin.wait(f'JSON.stringify(global.__vt.panels().map(p => p.thickness)) === {json.dumps(json.dumps(expected))}', 10)
        except TimeoutError:
            pass
        actual = [p['thickness'] for p in cin.eval('global.__vt.panels()')]
        checks.check('live-gap-change', actual == expected, f'thickness {actual}, expected {expected}')

        p = cin.eval('global.__vt.panels()')[0]
        applet = p['applets'][-1]
        centre = (applet['x'] + applet['width'] // 2, applet['y'] + applet['height'] // 2)
        cin.eval('global.__vt.move(%d, %d)' % centre)
        time.sleep(0.4)
        write_settings(cin, home, {'highlight-radius': 13})
        time.sleep(0.6)
        style = cin.eval('global.__vt.hoverStyle(%d, %d)' % centre)
        checks.check('live-highlight-radius-change', style and style['radius'] == 13 * scale, json.dumps(style))
        cin.eval('global.__vt.move(%d, %d)' % (w // 2, h // 2))

        other = 'theme' if glass else 'glass'
        write_settings(cin, home, {'background': other})
        cin.wait(f'global.__vt.panels().every(p => p.bg && (p.bg.effects > 0) === {json.dumps(other == "glass")})', 10)
        checks.check('switch-background', True, other)

        cin.activate_callback('restoreDefaults')
        expected = [b['thickness'] + 2 * (settings_value('gap', {}) + settings_value('inner-padding', {})) * scale for b in before]
        try:
            cin.wait(f'JSON.stringify(global.__vt.panels().map(p => p.thickness)) === {json.dumps(json.dumps(expected))}', 10)
        except TimeoutError:
            pass
        restored_panels = cin.eval('global.__vt.panels()')
        saved = json.loads((home / '.config' / 'cinnamon' / 'spices' / UUID / f'{UUID}.json').read_text())
        wrong = {k: v['value'] for k, v in saved.items()
                 if isinstance(v, dict) and 'default' in v and v.get('value') != v['default']}
        checks.check('restore-defaults', [p['thickness'] for p in restored_panels] == expected and not wrong
                     and all(p['bg']['effects'] > 0 for p in restored_panels),
                     f'thickness {[p["thickness"] for p in restored_panels]}, expected {expected}, not default: {wrong}')

        gset('org.cinnamon', 'enabled-extensions', '[]')
        cin.wait('global.__vt.mod() === null || global.__vt.mod().panels.size === 0', 10)
        time.sleep(1)
        restored = cin.eval('global.__vt.panels()')
        for b, r in zip(before, restored):
            same = {k: (b[k], r[k]) for k in ('thickness', 'content', 'style', 'classes', 'children', 'x', 'y', 'width', 'height') if b[k] != r[k]}
            checks.check(f'panel{r["id"]}-disable-restores', not same, json.dumps(same))
        checks.check('no-errors-at-end', not cin.eval('global.__vt.errors()'), str(cin.eval('global.__vt.errors()')))
    except Exception as e:
        checks.check('harness', False, f'{type(e).__name__}: {e}')
    finally:
        for proc in reversed(procs):
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return checks.results


def inner(name, tmp):
    results = run_scenario(name, Path(tmp))
    (Path(tmp) / 'result.json').write_text(json.dumps(results))


def outer(names, keep):
    failed = 0
    for name in names:
        tmp = Path(tempfile.mkdtemp(prefix=f'vitrin-{name}-'))
        (tmp / 'home').mkdir()
        (tmp / 'run').mkdir(mode=0o700)
        env = {
            'PATH': os.environ['PATH'],
            'LANG': os.environ.get('LANG', 'C.UTF-8'),
            'HOME': str(tmp / 'home'),
            'XDG_CONFIG_HOME': str(tmp / 'home' / '.config'),
            'XDG_DATA_HOME': str(tmp / 'home' / '.local' / 'share'),
            'XDG_CACHE_HOME': str(tmp / 'home' / '.cache'),
            'XDG_RUNTIME_DIR': str(tmp / 'run'),
        }
        start = time.time()
        subprocess.run(['dbus-run-session', '--', sys.executable, __file__, '--inner', name, str(tmp)],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result_file = tmp / 'result.json'
        results = json.loads(result_file.read_text()) if result_file.exists() else [
            {'check': 'harness', 'ok': False, 'detail': 'scenario crashed'}]
        bad = [r for r in results if not r['ok']]
        failed += bool(bad)
        print(f'{"FAIL" if bad else "PASS"}  {name}  ({len(results) - len(bad)}/{len(results)} checks, {time.time() - start:.0f}s)')
        for r in bad:
            print(f'      {r["check"]}: {r["detail"]}')
        if bad and (tmp / 'cinnamon.log').exists():
            OUT.mkdir(exist_ok=True)
            shutil.copy(tmp / 'cinnamon.log', OUT / f'{name}.log')
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{len(names) - failed}/{len(names)} scenarios passed. Screenshots in {OUT}')
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('names', nargs='*', help='scenarios to run (default: all)')
    parser.add_argument('--list', action='store_true', help='list scenarios')
    parser.add_argument('--keep', action='store_true', help='keep temporary session directories')
    parser.add_argument('--inner', nargs=2, metavar=('NAME', 'DIR'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.list:
        print('\n'.join(SCENARIOS))
        return 0
    if args.inner:
        inner(*args.inner)
        return 0
    unknown = [n for n in args.names if n not in SCENARIOS]
    if unknown:
        parser.error(f'unknown scenarios: {", ".join(unknown)}')
    return outer(args.names or [n for n in SCENARIOS if not SCENARIOS[n].get('manual')], args.keep)


if __name__ == '__main__':
    sys.exit(main())
