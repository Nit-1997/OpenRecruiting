"use client";

import { useEffect, useRef, useState } from "react";

const VERTEX_SHADER = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const FRAGMENT_SHADER = `
  uniform float uTime;
  uniform float uProgress;
  uniform sampler2D uTexture1;
  uniform sampler2D uTexture2;
  uniform vec2 uResolution;
  varying vec2 vUv;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }

  void main() {
    vec2 uv = vUv;
    float t = uProgress;

    float distortion = noise(uv * 4.0 + uTime * 0.3) * 0.08;
    float wave = sin(uv.x * 8.0 + uTime * 0.5) * 0.02;

    vec2 distortedUv1 = uv + vec2(distortion * (1.0 - t), wave * (1.0 - t));
    vec2 distortedUv2 = uv + vec2(-distortion * t, -wave * t);

    vec4 tex1 = texture2D(uTexture1, distortedUv1);
    vec4 tex2 = texture2D(uTexture2, distortedUv2);

    float edge = smoothstep(0.0, 1.0, t + (noise(uv * 6.0 + uTime) - 0.5) * 0.3);

    vec4 color = mix(tex1, tex2, edge);

    float vignette = 1.0 - length((uv - 0.5) * 1.4);
    vignette = smoothstep(0.0, 0.7, vignette);
    color.rgb *= vignette * 0.85 + 0.15;

    color.rgb *= 0.7;

    gl_FragColor = color;
  }
`;

const IMAGE_URLS = [
  "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1920&q=80&auto=format",
  "https://images.unsplash.com/photo-1506318137071-a8e063b4bec0?w=1920&q=80&auto=format",
  "https://images.unsplash.com/photo-1462331940025-496dfbfc7564?w=1920&q=80&auto=format",
  "https://images.unsplash.com/photo-1534796636912-3b95b3ab5986?w=1920&q=80&auto=format",
];

const SLIDE_DURATION = 5000;
const TRANSITION_DURATION = 2000;

function WebGLHeroBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [webglSupported, setWebglSupported] = useState(true);

  useEffect(() => {
    const canvasEl = canvasRef.current;
    if (!canvasEl) return;

    let THREE: typeof import("three");
    let gsapLib: typeof import("gsap");
    let animationId: number;
    let disposed = false;

    async function init() {
      const el = canvasEl as HTMLCanvasElement;

      try {
        [THREE, gsapLib] = await Promise.all([
          import("three"),
          import("gsap"),
        ]);
      } catch {
        setWebglSupported(false);
        return;
      }

      if (disposed) return;

      const renderer = new THREE.WebGLRenderer({
        canvas: el,
        antialias: false,
        alpha: false,
      });
      renderer.setSize(el.clientWidth, el.clientHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

      const scene = new THREE.Scene();
      const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
      camera.position.z = 1;

      const loader = new THREE.TextureLoader();
      const textures: InstanceType<typeof THREE.Texture>[] = [];

      const loadTexture = (url: string): Promise<InstanceType<typeof THREE.Texture>> =>
        new Promise((resolve) => {
          loader.load(
            url,
            (tex) => {
              tex.minFilter = THREE.LinearFilter;
              tex.magFilter = THREE.LinearFilter;
              resolve(tex);
            },
            undefined,
            () => {
              const fallback = new THREE.Texture();
              resolve(fallback);
            }
          );
        });

      const loaded = await Promise.all(IMAGE_URLS.map(loadTexture));
      if (disposed) {
        loaded.forEach((t) => t.dispose());
        renderer.dispose();
        return;
      }
      textures.push(...loaded);

      const uniforms = {
        uTime: { value: 0 },
        uProgress: { value: 0 },
        uTexture1: { value: textures[0] },
        uTexture2: { value: textures[1] },
        uResolution: {
          value: new THREE.Vector2(el.clientWidth, el.clientHeight),
        },
      };

      const material = new THREE.ShaderMaterial({
        vertexShader: VERTEX_SHADER,
        fragmentShader: FRAGMENT_SHADER,
        uniforms,
      });

      const geometry = new THREE.PlaneGeometry(2, 2);
      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      let currentSlide = 0;
      let isTransitioning = false;

      function transitionToNext() {
        if (isTransitioning || disposed) return;
        isTransitioning = true;

        const nextSlide = (currentSlide + 1) % textures.length;
        uniforms.uTexture1.value = textures[currentSlide];
        uniforms.uTexture2.value = textures[nextSlide];
        uniforms.uProgress.value = 0;

        gsapLib.gsap.to(uniforms.uProgress, {
          value: 1,
          duration: TRANSITION_DURATION / 1000,
          ease: "power2.inOut",
          onComplete: () => {
            currentSlide = nextSlide;
            isTransitioning = false;
            // transition complete
          },
        });
      }

      const slideInterval = setInterval(transitionToNext, SLIDE_DURATION);

      const clock = new THREE.Clock();

      function animate() {
        if (disposed) return;
        animationId = requestAnimationFrame(animate);
        uniforms.uTime.value = clock.getElapsedTime();
        renderer.render(scene, camera);

      }
      animate();

      const handleResize = () => {
        if (disposed) return;
        renderer.setSize(el.clientWidth, el.clientHeight);
        uniforms.uResolution.value.set(el.clientWidth, el.clientHeight);
      };
      window.addEventListener("resize", handleResize);

      return () => {
        disposed = true;
        clearInterval(slideInterval);
        cancelAnimationFrame(animationId);
        window.removeEventListener("resize", handleResize);
        textures.forEach((t) => t.dispose());
        geometry.dispose();
        material.dispose();
        renderer.dispose();
      };
    }

    const cleanup = init();
    return () => {
      disposed = true;
      cleanup.then((fn) => fn?.());
    };
  }, []);

  if (!webglSupported) {
    return (
      <div
        id="hero-fallback-bg"
        className="absolute inset-0"
        style={{
          background: "linear-gradient(135deg, #0A0A0A 0%, #1a1a2e 50%, #0A0A0A 100%)",
        }}
      />
    );
  }

  return (
    <canvas
      ref={canvasRef}
      id="hero-webgl-canvas"
      className="absolute inset-0 w-full h-full"
      style={{ display: "block" }}
    />
  );
}

export { WebGLHeroBackground };
