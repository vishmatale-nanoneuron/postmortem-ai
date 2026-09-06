"use client";

import * as React from "react";

// A real canvas particle field behind the hero -- scattered points drifting
// and slowly swirling inward, which is the one motif worth borrowing from
// the kind of launch-page animation this was modeled on (a luminous
// particle spiral). Deliberately reinterpreted rather than copied:
//
// - Accent teal on the light paper background, not glowing white on black.
//   The rest of this site is a sober "case file / evidence exhibit" design,
//   and the product's whole credibility pitch is that it doesn't oversell.
//   A black hero with a glowing spiral would read as a different product
//   than the page directly below it.
// - No connecting lines between nearby particles. That "constellation
//   network" look is the single most templated canvas effect on the web;
//   depth here comes from size/opacity/speed parallax instead, which reads
//   as atmosphere rather than as a stock demo.
// - Thematically it's evidence converging, not decoration for its own sake:
//   scattered points drawn gradually toward a center.
//
// Everything below that looks defensive is load-bearing -- see each comment.
export function HeroParticles({ className }: { className?: string }) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // canvas unsupported: hero just renders without it

    // globals.css's prefers-reduced-motion block collapses CSS animation
    // and transition durations, but it has no way to stop a JS
    // requestAnimationFrame loop -- a canvas would keep moving for exactly
    // the users who asked their OS for it not to. So this is checked here
    // in JS, and honored by drawing a single static frame instead of
    // animating. Not "render nothing": the composition still shows up, it
    // just doesn't move.
    const reduceMotionQuery =
      typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

    type Particle = {
      angle: number; // position around the center, in radians
      radius: number; // distance from center, in px
      depth: number; // 0..1, drives size/opacity/speed parallax
      drift: number; // per-particle angular speed multiplier
    };

    let particles: Particle[] = [];
    let width = 0;
    let height = 0;
    let frame = 0;
    let running = false;
    let lastTime = 0;

    // Read the accent straight off the design system rather than
    // hardcoding #2a6e5c here -- if the brand color is ever changed in
    // globals.css, this follows it instead of silently drifting out of
    // sync. Falls back to the current accent if the property is missing.
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim() || "#2a6e5c";

    function resize() {
      if (!canvas || !ctx) return;
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      // Cap device pixel ratio at 2: a 3x phone display would otherwise
      // allocate (and repaint) 2.25x more pixels than a 2x one for a
      // difference nobody can see on a blurred background field, and this
      // runs on every frame.
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Particle count scales with area so a wide desktop hero doesn't look
      // sparse and a phone doesn't render hundreds of points it can't show,
      // but is hard-capped -- unbounded counts are how canvas backgrounds
      // quietly become the most expensive thing on a page.
      const target = Math.min(140, Math.max(40, Math.round((width * height) / 7000)));
      particles = Array.from({ length: target }, () => spawn());
    }

    function spawn(): Particle {
      const maxRadius = Math.hypot(width, height) * 0.5;
      return {
        angle: Math.random() * Math.PI * 2,
        // Biased outward (sqrt distribution) so particles are spread evenly
        // by area rather than clustering near the center, which a uniform
        // random radius would do.
        radius: Math.sqrt(Math.random()) * maxRadius,
        depth: Math.random(),
        drift: 0.6 + Math.random() * 0.8,
      };
    }

    function draw(deltaMs: number) {
      if (!ctx) return;
      ctx.clearRect(0, 0, width, height);

      // The convergence point sits above the hero's center, roughly behind
      // the logo, so the swirl reads as centered on the content rather than
      // on the viewport.
      const cx = width * 0.5;
      const cy = height * 0.38;
      const maxRadius = Math.hypot(width, height) * 0.5;

      for (const p of particles) {
        // Delta-time scaled: a naive per-frame increment runs at double
        // speed on a 120Hz display and half speed on a throttled tab. This
        // keeps the drift identical regardless of refresh rate.
        const t = deltaMs / 1000;
        // Nearer particles (higher depth) orbit faster -- the parallax that
        // creates a sense of depth without any 3D math.
        p.angle += t * 0.05 * p.drift * (0.4 + p.depth);
        p.radius -= t * 4 * (0.3 + p.depth); // slow inward pull

        // Recycle at the center back out to the rim, so the field never
        // depletes and there's no visible "all particles arrived" end state.
        if (p.radius < 8) {
          p.radius = maxRadius;
          p.angle = Math.random() * Math.PI * 2;
        }

        const x = cx + Math.cos(p.angle) * p.radius;
        // Squashed vertically (0.62) so the swirl reads as a shallow disc
        // seen at an angle rather than a flat circle -- the depth cue that
        // makes a 2D particle field feel dimensional.
        const y = cy + Math.sin(p.angle) * p.radius * 0.62;

        const size = 1 + p.depth * 2.2;
        // Fade out near the rim so particles enter and leave softly instead
        // of popping in at the edges.
        const edgeFade = Math.min(1, (maxRadius - p.radius) / (maxRadius * 0.35));
        const alpha = (0.16 + p.depth * 0.34) * Math.max(0, edgeFade);

        // The nearest third get a soft halo -- this is what reads as
        // "luminous" on a light background, where a hard dot just reads as
        // a speck of dust. Drawn as a radial gradient rather than canvas
        // shadowBlur: shadowBlur is dramatically slower per-particle and
        // this runs every frame.
        if (p.depth > 0.66) {
          const glow = ctx.createRadialGradient(x, y, 0, x, y, size * 4);
          glow.addColorStop(0, accent);
          glow.addColorStop(1, "transparent");
          ctx.globalAlpha = alpha * 0.3;
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(x, y, size * 4, 0, Math.PI * 2);
          ctx.fill();
        }

        ctx.globalAlpha = alpha;
        ctx.fillStyle = accent;
        ctx.beginPath();
        ctx.arc(x, y, size, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function loop(now: number) {
      if (!running) return;
      // Clamp the delta: returning to a backgrounded tab can produce a
      // multi-second gap, which would teleport every particle in one frame.
      const delta = Math.min(now - lastTime, 50);
      lastTime = now;
      draw(delta);
      frame = window.requestAnimationFrame(loop);
    }

    function start() {
      if (running || reduceMotionQuery?.matches) return;
      running = true;
      lastTime = performance.now();
      frame = window.requestAnimationFrame(loop);
    }

    function stop() {
      running = false;
      window.cancelAnimationFrame(frame);
    }

    resize();
    if (reduceMotionQuery?.matches) {
      draw(0); // one static frame, no loop
    } else {
      start();
    }

    // Pause when scrolled past. The hero is at the top of a long page --
    // without this, the loop keeps running (and draining battery) the
    // entire time someone reads the rest of the page with it off-screen.
    let observer: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) start();
          else stop();
        },
        { threshold: 0 },
      );
      observer.observe(canvas);
    }

    // Pause in a hidden tab too -- browsers throttle RAF there but don't
    // reliably stop it, and there is nothing to see either way.
    function onVisibility() {
      if (document.hidden) stop();
      else start();
    }
    document.addEventListener("visibilitychange", onVisibility);

    // If the user flips reduced-motion on while the page is open, honor it
    // immediately rather than only on next load.
    function onReduceMotionChange() {
      if (reduceMotionQuery?.matches) {
        stop();
        draw(0);
      } else {
        start();
      }
    }
    reduceMotionQuery?.addEventListener("change", onReduceMotionChange);

    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            resize();
            if (reduceMotionQuery?.matches) draw(0);
          })
        : null;
    resizeObserver?.observe(canvas);

    return () => {
      stop();
      observer?.disconnect();
      resizeObserver?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduceMotionQuery?.removeEventListener("change", onReduceMotionChange);
    };
  }, []);

  // aria-hidden + pointer-events-none: purely decorative, must never appear
  // in the accessibility tree or intercept a click on the CTA behind it.
  return <canvas ref={canvasRef} aria-hidden className={className} />;
}
