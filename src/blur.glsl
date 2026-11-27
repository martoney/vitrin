uniform sampler2D tex;
uniform float tex_width;
uniform float tex_height;
uniform float dx;
uniform float dy;

void effect_main() {
    vec2 texSize = vec2(tex_width, tex_height);
    vec2 uv = cogl_tex_coord_in[0].xy;
    vec2 stepUV = vec2(dx, dy) / texSize;
    vec2 lo = 0.5 / texSize;
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
