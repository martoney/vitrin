uniform sampler2D tex;
uniform float width;
uniform float height;
uniform float tex_width;
uniform float tex_height;
uniform float inset_x;
uniform float inset_y;
uniform float radius;
uniform float scale;
uniform float bezel;
uniform float lens;
uniform float fringe;
uniform float saturation;
uniform float frost;
uniform float rim;
uniform float shadow;

const float EDGE_GLOW = 0.25;
const vec2 LIGHT = vec2(-0.4, -1.0);

float box(vec2 p, vec2 halfSize, float r) {
    vec2 q = abs(p) - halfSize + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

float bezelSlope(float x) {
    float s = 1.0 - pow(1.0 - x, 4.0);
    return pow(max(s, 1e-4), -0.75) * pow(1.0 - x, 3.0);
}

vec2 texSize() {
    return vec2(tex_width, tex_height);
}

vec2 texPad() {
    return texSize() - vec2(width, height) - 1.0;
}

vec3 backdrop(vec2 px) {
    vec2 size = vec2(width, height);
    vec2 lo = vec2(inset_x, inset_y) + 0.5;
    return texture2D(tex, (clamp(px, lo, size - lo) + texPad()) / texSize()).rgb;
}

void effect_main() {
    vec2 size = vec2(width, height);
    vec2 px = cogl_tex_coord_in[0].xy * texSize() - texPad();
    vec2 halfSize = size * 0.5 - vec2(inset_x, inset_y);
    float r = min(radius, min(halfSize.x, halfSize.y));
    vec2 p = px - size * 0.5;
    float d = box(p, halfSize, r);

    float sd = max(box(p - vec2(0.0, 1.5 * scale), halfSize, r), 0.0);
    float sigma = 4.0 * scale;
    float shade = shadow * exp(-sd * sd / (2.0 * sigma * sigma));
    float cover = clamp(0.5 - d, 0.0, 1.0);
    if (cover <= 0.0) {
        cogl_color_out = vec4(0.0, 0.0, 0.0, shade * cogl_color_in.a);
        return;
    }

    vec2 n = normalize(vec2(box(p + vec2(1.0, 0.0), halfSize, r) - box(p - vec2(1.0, 0.0), halfSize, r),
                            box(p + vec2(0.0, 1.0), halfSize, r) - box(p - vec2(0.0, 1.0), halfSize, r)) + 1e-6);
    float depth = -d;
    float band = max(bezel * scale, 1.0);
    float x = clamp(depth / band, 0.0, 1.0);
    float bend = min(1.0, 0.4 * bezelSlope(x)) * (1.0 - x);
    vec2 offset = -n * bend * band * lens;
    vec2 split = offset * fringe;
    vec3 col = vec3(backdrop(px + offset - split).r,
                    backdrop(px + offset).g,
                    backdrop(px + offset + split).b);

    float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
    col = mix(vec3(lum), col, saturation);
    col = mix(col, vec3(1.0), frost);

    vec2 light = normalize(LIGHT);
    float specular = pow(max(dot(n, light), 0.0), 3.0) + 0.6 * pow(max(dot(n, -light), 0.0), 3.0);
    float edge = 1.0 - smoothstep(0.0, 2.0 * scale, depth);
    float glow = pow(1.0 - x, 3.0);
    float glare = rim * (edge * specular * (0.25 + 0.75 * lum) + EDGE_GLOW * glow * lum);
    col = clamp(1.0 - (1.0 - col) * (1.0 - clamp(glare, 0.0, 1.0)), 0.0, 1.0);

    float alpha = cover + (1.0 - cover) * shade;
    cogl_color_out = vec4(col * cover / max(alpha, 1e-4), alpha * cogl_color_in.a);
}
