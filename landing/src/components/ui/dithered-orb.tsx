"use client";

import { useRef, useEffect } from "react";

export type OrbState = "idle" | "listening" | "processing" | "speaking";

interface DitheredOrbProps {
  state: OrbState;
  audioLevel?: number;
}

const BAYER4 = [
  [0 / 16, 8 / 16, 2 / 16, 10 / 16],
  [12 / 16, 4 / 16, 14 / 16, 6 / 16],
  [3 / 16, 11 / 16, 1 / 16, 9 / 16],
  [15 / 16, 7 / 16, 13 / 16, 5 / 16],
];

const LO_RES = 180;

export function DitheredOrb({ state, audioLevel = 0 }: DitheredOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameRef = useRef<number>(0);
  const smoothedAudioRef = useRef(0);
  const sizeRef = useRef({ w: 0, h: 0 });
  const loCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const audioLevelRef = useRef(audioLevel);

  audioLevelRef.current = audioLevel;

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const loCanvas = document.createElement("canvas");
    loCanvas.width = LO_RES;
    loCanvas.height = LO_RES;
    loCanvasRef.current = loCanvas;
    const loCtx = loCanvas.getContext("2d")!;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      sizeRef.current = { w: rect.width, h: rect.height };
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    resize();
    window.addEventListener("resize", resize);

    const brightness = new Float32Array(LO_RES * LO_RES);
    const zBuffer = new Float32Array(LO_RES * LO_RES);

    let frameCount = 0;

    const lnx = -0.33, lny = -0.6, lnz = 0.73;

    const draw = (timestamp: number) => {
      const { w, h } = sizeRef.current;
      if (w === 0 || h === 0) {
        animFrameRef.current = requestAnimationFrame(draw);
        return;
      }

      frameCount++;
      const t = timestamp / 1000;

      const rawAudio = state === "idle" ? 0 : audioLevelRef.current;
      const boostedAudio = Math.min(1, rawAudio);
      smoothedAudioRef.current +=
        (boostedAudio - smoothedAudioRef.current) * 0.01;
      const audio = smoothedAudioRef.current;

      const N = LO_RES;
      const cx = N / 2;
      const cy = N / 2;
      const sphereR = N * 0.18;

      brightness.fill(-1);
      zBuffer.fill(-Infinity);

      const shimmerRate = Math.max(8, 18 - Math.floor(audio * 8));
      const shimmerOff = Math.floor(frameCount / shimmerRate);

      const sr = Math.ceil(sphereR);
      for (let py = Math.floor(cy - sr); py <= Math.ceil(cy + sr); py++) {
        if (py < 0 || py >= N) continue;
        for (let px = Math.floor(cx - sr); px <= Math.ceil(cx + sr); px++) {
          if (px < 0 || px >= N) continue;
          const dx = px - cx, dy = py - cy;
          if (dx * dx + dy * dy > sphereR * sphereR) continue;
          const nx = dx / sphereR, ny = dy / sphereR;
          const nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
          const b = Math.max(0, nx * lnx + ny * lny + nz * lnz) * 0.85 + 0.15;
          const idx = py * N + px;
          const z = nz * sphereR;
          if (z > zBuffer[idx]) { zBuffer[idx] = z; brightness[idx] = b; }
        }
      }

      const baseAmp = N * 0.015 + audio * N * 0.2;
      const waveXStart = Math.floor(N * 0.15);
      const waveXEnd = Math.ceil(N * 0.85);
      const thickness = 1.8 + audio * 1.5;
      const speed = 4 + audio * 8;
      const zAmp = sphereR * 1.2;

      const sA = t * speed;
      for (let x = waveXStart; x < waveXEnd; x++) {
        const waveY = cy + Math.sin((x + sA) * 0.055) * baseAmp;
        const waveZ = Math.sin((x + sA) * 0.04) * zAmp;
        const th = Math.ceil(thickness);
        for (let dy = -th; dy <= th; dy++) {
          const pyW = Math.round(waveY + dy);
          if (pyW < 0 || pyW >= N) continue;
          const dist = Math.abs(dy) / thickness;
          if (dist > 1) continue;
          const crossZ = waveZ + Math.sqrt(Math.max(0, 1 - dist * dist)) * thickness * 0.5;
          const idx = pyW * N + x;
          if (crossZ > zBuffer[idx]) {
            const nyN = -dy / (thickness + 0.01);
            const nzN = Math.sqrt(Math.max(0, 1 - nyN * nyN));
            const dot = nyN * lny + nzN * lnz;
            const b = Math.max(0, dot) * 0.75 + 0.15;
            if (b > 0) { zBuffer[idx] = crossZ; brightness[idx] = b; }
          }
        }
      }

      const sB = -(t * speed);
      for (let x = waveXStart; x < waveXEnd; x++) {
        const waveY = cy + Math.sin((x + sB) * 0.06) * baseAmp;
        const waveZ = Math.sin((x + sB) * 0.045 + Math.PI) * zAmp;
        const th = Math.ceil(thickness);
        for (let dy = -th; dy <= th; dy++) {
          const pyW = Math.round(waveY + dy);
          if (pyW < 0 || pyW >= N) continue;
          const dist = Math.abs(dy) / thickness;
          if (dist > 1) continue;
          const crossZ = waveZ + Math.sqrt(Math.max(0, 1 - dist * dist)) * thickness * 0.5;
          const idx = pyW * N + x;
          if (crossZ > zBuffer[idx]) {
            const nyN = -dy / (thickness + 0.01);
            const nzN = Math.sqrt(Math.max(0, 1 - nyN * nyN));
            const dot = nyN * lny + nzN * lnz;
            const b = Math.max(0, dot) * 0.75 + 0.15;
            if (b > 0) { zBuffer[idx] = crossZ; brightness[idx] = b; }
          }
        }
      }

      const imageData = loCtx.createImageData(N, N);
      const data = imageData.data;

      for (let y = 0; y < N; y++) {
        for (let x = 0; x < N; x++) {
          const idx = y * N + x;
          const i4 = idx * 4;

          if (brightness[idx] < 0) {
            data[i4] = 9; data[i4 + 1] = 9; data[i4 + 2] = 9; data[i4 + 3] = 255;
            continue;
          }

          const bx = ((x + shimmerOff) % 4 + 4) % 4;
          const by = ((y + shimmerOff * 3) % 4 + 4) % 4;
          const threshold = BAYER4[by][bx];
          const v = brightness[idx] > threshold * 0.9 + 0.05 ? 252 : 9;
          data[i4] = v; data[i4 + 1] = v; data[i4 + 2] = v; data[i4 + 3] = 255;
        }
      }

      loCtx.putImageData(imageData, 0, 0);

      ctx.fillStyle = "#090909";
      ctx.fillRect(0, 0, w, h);
      ctx.imageSmoothingEnabled = false;

      const scale = Math.min(w, h) / N;
      const dw = N * scale;
      const dh = N * scale;
      const ddx = (w - dw) / 2;
      const ddy = (h - dh) * 0.35;
      ctx.drawImage(loCanvas, 0, 0, N, N, ddx, ddy, dw, dh);

      animFrameRef.current = requestAnimationFrame(draw);
    };

    animFrameRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(animFrameRef.current);
      window.removeEventListener("resize", resize);
    };
  }, [state]);

  return (
    <div
      id="dithered-orb-container"
      ref={containerRef}
      className="relative w-full h-full"
    >
      <canvas
        id="dithered-orb-canvas"
        ref={canvasRef}
        className="h-full w-full rounded-2xl"
      />
    </div>
  );
}
