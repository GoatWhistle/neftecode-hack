import { useEffect, useRef, useState } from "react";

const DURATION = 520;

interface Parsed {
  prefix: string;
  target: number;
  suffix: string;
  decimals: number;
}

function parse(value: string): Parsed | null {
  const match = /^(\D*?)(-?\d[\d  ]*(?:[.,]\d+)?)(.*)$/s.exec(value);
  const digits = match?.[2];
  if (!match || digits === undefined) return null;
  const raw = digits.replace(/[  ]/g, "").replace(",", ".");
  const target = Number(raw);
  if (!Number.isFinite(target)) return null;
  const dot = raw.indexOf(".");
  return {
    prefix: match[1] ?? "",
    target,
    suffix: match[3] ?? "",
    decimals: dot === -1 ? 0 : raw.length - dot - 1
  };
}

function still(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function frameOf(parsed: Parsed, eased: number): string {
  return `${parsed.prefix}${(parsed.target * eased).toFixed(parsed.decimals)}${parsed.suffix}`;
}

function animates(parsed: Parsed | null): parsed is Parsed {
  return parsed !== null && parsed.target !== 0 && !still();
}

export function useCountUp(value: string): string {
  const [shown, setShown] = useState(() => {
    const parsed = parse(value);
    return animates(parsed) ? frameOf(parsed, 0) : value;
  });
  const played = useRef<string | null>(null);

  useEffect(() => {
    const parsed = parse(value);
    if (played.current === value || !animates(parsed)) {
      setShown(value);
      return;
    }
    played.current = value;

    const start = performance.now();
    let frame = requestAnimationFrame(function step(now: number) {
      const progress = Math.min(1, Math.max(0, (now - start) / DURATION));
      setShown(progress < 1 ? frameOf(parsed, 1 - Math.pow(1 - progress, 3)) : value);
      if (progress < 1) frame = requestAnimationFrame(step);
    });

    return () => {
      cancelAnimationFrame(frame);
      played.current = null;
    };
  }, [value]);

  return shown;
}
