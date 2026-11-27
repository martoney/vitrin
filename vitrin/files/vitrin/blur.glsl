uniform sampler2D tex;
uniform float width;
uniform float height;
uniform float dx;
uniform float dy;

void effect_main() {
    vec2 size = vec2(width, height);
    vec2 uv = cogl_tex_coord_in[0].xy;
    vec2 stepUV = vec2(dx, dy) / size;
    vec2 lo = 0.5 / size;
    vec2 hi = 1.0 - lo;
    vec3 sum = vec3(0.0);
    float total = 0.0;
    for (int i = -12; i <= 12; i++) {
        float w = exp(-float(i * i) / 32.0);
        sum += texture2D(tex, clamp(uv + stepUV * float(i), lo, hi)).rgb * w;
        total += w;
    }
    cogl_color_out = vec4(sum / total, 1.0);
}
