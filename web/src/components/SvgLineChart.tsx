import React, { useEffect, useRef, useState } from 'react';
import { fmt } from '../dataLoader';

export interface ChartSeries {
  name: string;
  short?: string;
  values: number[];
  color: string;
  width?: number;
  dash?: string;
  dots?: boolean;
}

export interface ChartBand {
  lo: number[];
  hi: number[];
  color: string;
  opacity?: number;
}

export interface ChartPoint {
  i: number;
  v: number;
  color: string;
  r?: number;
  label?: string;
  dy?: number;
}

export interface ChartReferenceLine {
  y: number;
  label?: string;
  color?: string;
  dash?: string;
  position?: 'left' | 'right';
}

export interface ChartVLine {
  i: number;
  label?: string;
  color?: string;
  dash?: string;
}

export interface SvgLineChartProps {
  series: ChartSeries[];
  labels: string[];
  height?: number;
  yFmt?: (v: number) => string;
  xTick?: (i: number, label: string, narrow: boolean) => string | null;
  tipTitle?: (label: string, index: number) => string;
  tipValue?: (val: number, s: ChartSeries) => string;
  tipExtra?: (index: number) => string[];
  points?: ChartPoint[];
  referenceLines?: ChartReferenceLine[];
  vLines?: ChartVLine[];
  forceZero?: boolean;
  yMin?: number;
  yMax?: number;
  directLabels?: boolean;
  bands?: ChartBand[];
  yUnit?: string;
  ariaLabel?: string;
  syncIndex?: number | null;
  onIndexChange?: (index: number | null) => void;
}

function niceStep(span: number, count: number): number {
  const raw = span / count;
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const f = raw / p;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
}

export const SvgLineChart: React.FC<SvgLineChartProps> = ({
  series,
  labels,
  height = 200,
  yFmt,
  xTick = () => null,
  tipTitle = (l) => l,
  tipValue = (v) => fmt(v, 1),
  tipExtra,
  points = [],
  referenceLines = [],
  vLines = [],
  forceZero = true,
  yMin,
  yMax,
  directLabels = false,
  bands = [],
  yUnit,
  ariaLabel = 'Chart',
  syncIndex,
  onIndexChange,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState<number>(560);
  const [measuredH, setMeasuredH] = useState<number | null>(null);
  const [internalIndex, setInternalIndex] = useState<number | null>(null);
  const [lastIndex, setLastIndex] = useState<number>(Math.max(0, labels.length - 1));

  useEffect(() => {
    setLastIndex(Math.max(0, labels.length - 1));
  }, [labels.length]);

  const rawActiveIndex = syncIndex !== undefined ? syncIndex : internalIndex;
  const activeIndex =
    rawActiveIndex !== null && labels.length > 0
      ? Math.max(0, Math.min(labels.length - 1, rawActiveIndex))
      : null;

  const updateActiveIndex = (next: number | null) => {
    setInternalIndex(next);
    onIndexChange?.(next);
    if (next !== null) {
      setLastIndex(next);
    }
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const updateSize = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0) {
        setWidth(Math.max(220, Math.round(rect.width)));
      }
      if (rect.height > 44) {
        setMeasuredH(Math.round(rect.height));
      }
    };
    updateSize();
    if ('ResizeObserver' in window) {
      const ro = new ResizeObserver(() => updateSize());
      ro.observe(el);
      return () => ro.disconnect();
    }
  }, []);

  const W = width;
  const fallbackH = Math.max(64, height);
  const H = measuredH ? Math.max(60, measuredH) : fallbackH;
  const compactY = H < 105;

  const m = {
    l: 46,
    r: directLabels ? 76 : 14,
    t: yUnit ? (compactY ? 15 : 19) : 10,
    b: compactY ? 18 : 22,
  };

  const vals = [
    ...series.flatMap((s) => s.values),
    ...bands.flatMap((b) => [...b.lo, ...b.hi]),
  ].filter((v) => Number.isFinite(v));

  if (!vals.length || !labels.length) {
    return (
      <div
        ref={containerRef}
        className="w-full h-full min-h-0 flex items-center justify-center text-xs text-slate-400 font-mono"
        style={{ minHeight: Math.min(fallbackH, 72) }}
      >
        No data points available
      </div>
    );
  }

  let lo = yMin ?? Math.min(...vals);
  let hi = yMax ?? Math.max(...vals);
  if (yMin == null && forceZero) lo = Math.min(lo, 0);
  const step = niceStep(hi - lo || 1, H >= 240 ? 4 : compactY ? 2 : 3);
  if (yMin == null) lo = Math.floor(lo / step + 1e-9) * step;
  if (yMax == null) hi = Math.ceil(hi / step - 1e-9) * step;
  if (hi <= lo) hi = lo + step;

  const dec = Math.max(0, Math.ceil(-Math.log10(step) - 1e-9));
  const tickFmt = yFmt || ((v: number) => fmt(Math.abs(v) < step / 1e6 ? 0 : v, dec));

  const n = labels.length;
  const x = (i: number) => m.l + (n <= 1 ? 0 : (i * (W - m.l - m.r)) / (n - 1));
  const y = (v: number) => H - m.b - ((v - lo) * (H - m.t - m.b)) / (hi - lo || 1);

  const yTicks: number[] = [];
  for (let v = lo; v <= hi + step * 1e-6; v += step) {
    yTicks.push(v);
  }

  // Bidirectional collision-free end labels that never bleed into the bottom x-axis labels
  const endLabels = directLabels
    ? (() => {
        const minY = m.t + 4;
        const maxY = H - m.b - 6;
        const gap = 12;
        const ends = series
          .map((s) => {
            let i = s.values.length - 1;
            while (i > 0 && !Number.isFinite(s.values[i])) i--;
            const val = s.values[i];
            const rawY = Number.isFinite(val) ? y(val) : H / 2;
            return { s, yy: Math.max(minY, Math.min(maxY, rawY)) };
          })
          .sort((a, b) => a.yy - b.yy);

        // Pass 1: push downward
        for (let k = 1; k < ends.length; k++) {
          if (ends[k].yy - ends[k - 1].yy < gap) {
            ends[k].yy = ends[k - 1].yy + gap;
          }
        }
        // Pass 2: if bottom label exceeded maxY, push upward from bottom
        if (ends.length > 0 && ends[ends.length - 1].yy > maxY) {
          ends[ends.length - 1].yy = maxY;
          for (let k = ends.length - 2; k >= 0; k--) {
            if (ends[k + 1].yy - ends[k].yy < gap) {
              ends[k].yy = Math.max(minY, ends[k + 1].yy - gap);
            }
          }
        }
        return ends;
      })()
    : [];

  const handlePointer = (e: React.PointerEvent<SVGRectElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const relX = e.clientX - rect.left;
    const idx = Math.round(((relX - m.l) / (W - m.l - m.r || 1)) * (n - 1));
    const clamped = Math.max(0, Math.min(n - 1, idx));
    updateActiveIndex(clamped);
  };

  const handleKeyDown = (e: React.KeyboardEvent<SVGRectElement>) => {
    const cur = activeIndex ?? lastIndex;
    const stepMap: Record<string, number> = {
      ArrowRight: 1,
      ArrowUp: 1,
      ArrowLeft: -1,
      ArrowDown: -1,
      PageUp: 5,
      PageDown: -5,
    };
    let next: number | null = null;
    if (stepMap[e.key] != null) {
      next = Math.max(0, Math.min(n - 1, cur + stepMap[e.key]));
    } else if (e.key === 'Home') {
      next = 0;
    } else if (e.key === 'End') {
      next = n - 1;
    }
    if (next !== null) {
      e.preventDefault();
      updateActiveIndex(next);
    }
  };

  const curIdx = activeIndex ?? lastIndex;
  const tipLines =
    activeIndex !== null
      ? [
          tipTitle(labels[activeIndex], activeIndex),
          ...series.map(
            (s) =>
              `${s.short || s.name}: ${
                Number.isFinite(s.values[activeIndex])
                  ? tipValue(s.values[activeIndex], s)
                  : '–'
              }`
          ),
          ...(tipExtra ? tipExtra(activeIndex).filter(Boolean) : []),
        ]
      : [];

  const maxLineLen = tipLines.reduce((acc, l) => Math.max(acc, l.length), 0);
  const tipBoxW = Math.max(126, maxLineLen * 6.8 + 18);
  const tipBoxH = tipLines.length * 15 + 10;
  const gx = activeIndex !== null ? x(activeIndex) : 0;
  const bx =
    gx + 12 + tipBoxW > W - 4 ? Math.max(4, gx - 12 - tipBoxW) : gx + 12;

  return (
    <div
      ref={containerRef}
      className="w-full h-full min-h-0 relative overflow-hidden"
      style={{ minHeight: Math.min(fallbackH, 72) }}
    >
      <svg
        ref={svgRef}
        className="chart"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={ariaLabel}
      >
        <g>
          {yUnit && (
            <text x={2} y={11} className="unit">
              {yUnit}
            </text>
          )}

          {yTicks.map((v, idx) => {
            const ty = y(v);
            return (
              <g key={`ytick-${idx}`}>
                <line
                  x1={m.l}
                  x2={W - m.r}
                  y1={ty}
                  y2={ty}
                  style={{ stroke: idx === 0 ? 'var(--axis)' : 'var(--grid)' }}
                  strokeWidth={1}
                />
                <text x={m.l - 6} y={ty + 3.5} textAnchor="end">
                  {tickFmt(v)}
                </text>
              </g>
            );
          })}

          {labels.map((l, i) => {
            const tickText = xTick(i, l, W < 420);
            if (tickText == null) return null;
            // Prevent the rightmost x-axis label from bleeding into direct endLabels
            const anchor =
              i === n - 1 && directLabels
                ? 'end'
                : i === 0
                ? 'start'
                : 'middle';
            return (
              <text key={`xtick-${i}`} x={x(i)} y={H - 4} textAnchor={anchor}>
                {tickText}
              </text>
            );
          })}

          {vLines.map((vl, vIdx) => {
            if (vl.i < 0 || vl.i >= n) return null;
            const vx = x(vl.i);
            const isRightSide = vx > W * 0.72;
            const vColor = vl.color || 'var(--syn)';
            return (
              <g key={`vline-${vIdx}`} pointerEvents="none">
                <line
                  x1={vx}
                  x2={vx}
                  y1={m.t}
                  y2={H - m.b}
                  style={{ stroke: vColor }}
                  strokeWidth={1.1}
                  strokeOpacity={0.65}
                  strokeDasharray={vl.dash || '4 3'}
                />
                {vl.label && (
                  <text
                    x={vx + (isRightSide ? -4 : 4)}
                    y={m.t + 10}
                    textAnchor={isRightSide ? 'end' : 'start'}
                    style={{
                      fill: vColor,
                      fontSize: '9.5px',
                      fontWeight: 600,
                      paintOrder: 'stroke',
                      stroke: 'var(--surface)',
                      strokeWidth: 3,
                      strokeLinejoin: 'round',
                    }}
                  >
                    {vl.label}
                  </text>
                )}
              </g>
            );
          })}

          {referenceLines.map((rl, rIdx) => {
            if (!Number.isFinite(rl.y) || rl.y < lo - step * 0.25 || rl.y > hi + step * 0.25) {
              return null;
            }
            const ry = Math.max(m.t + 2, Math.min(H - m.b - 2, y(rl.y)));
            const isLeft = rl.position === 'left';
            const rColor = rl.color || 'var(--syn)';
            const labelAbove = ry > m.t + 14;
            return (
              <g key={`refline-${rIdx}`} pointerEvents="none">
                <line
                  x1={m.l}
                  x2={W - m.r}
                  y1={ry}
                  y2={ry}
                  style={{ stroke: rColor }}
                  strokeWidth={1.15}
                  strokeOpacity={0.72}
                  strokeDasharray={rl.dash || '5 4'}
                />
                {rl.label && (
                  <text
                    x={isLeft ? m.l + 5 : W - m.r - 4}
                    y={labelAbove ? ry - 4 : ry + 11}
                    textAnchor={isLeft ? 'start' : 'end'}
                    style={{
                      fill: rColor,
                      fontSize: '9.5px',
                      fontWeight: 600,
                      paintOrder: 'stroke',
                      stroke: 'var(--surface)',
                      strokeWidth: 4,
                      strokeLinejoin: 'round',
                    }}
                  >
                    {rl.label}
                  </text>
                )}
              </g>
            );
          })}

          {bands.map((b, bIdx) => {
            const ok = labels.map(
              (_, i) => Number.isFinite(b.lo[i]) && Number.isFinite(b.hi[i])
            );
            const top = labels
              .map((_, i) =>
                ok[i] ? `${x(i).toFixed(1)},${y(b.hi[i]).toFixed(1)}` : null
              )
              .filter(Boolean);
            const bottom = labels
              .map((_, i) =>
                ok[i] ? `${x(i).toFixed(1)},${y(b.lo[i]).toFixed(1)}` : null
              )
              .filter(Boolean)
              .reverse();
            if (!top.length) return null;
            return (
              <path
                key={`band-${bIdx}`}
                d={`M${top.join('L')}L${bottom.join('L')}Z`}
                style={{ fill: b.color }}
                fillOpacity={b.opacity ?? 0.2}
              />
            );
          })}

          {series.map((s, sIdx) => {
            let d = '';
            let pen = false;
            s.values.forEach((v, i) => {
              if (!Number.isFinite(v)) {
                pen = false;
                return;
              }
              d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
              pen = true;
            });
            return (
              <g key={`series-${sIdx}`}>
                <path
                  d={d}
                  fill="none"
                  style={{ stroke: s.color }}
                  strokeWidth={s.width || 2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  strokeDasharray={s.dash}
                />
                {s.dots &&
                  s.values.map((v, i) =>
                    Number.isFinite(v) ? (
                      <circle
                        key={`dot-${i}`}
                        cx={x(i)}
                        cy={y(v)}
                        r={2.2}
                        style={{ fill: s.color }}
                      />
                    ) : null
                  )}
              </g>
            );
          })}

          {points.map((p, pIdx) => {
            if (!Number.isFinite(p.v) || p.i < 0 || p.i >= n) return null;
            const right = x(p.i) > W * 0.68;
            return (
              <g key={`pt-${pIdx}`}>
                <circle
                  cx={x(p.i)}
                  cy={y(p.v)}
                  r={p.r || 4.5}
                  style={{ fill: p.color, stroke: 'var(--surface)' }}
                  strokeWidth={1.8}
                />
                {p.label && (
                  <text
                    x={x(p.i) + (right ? -7 : 7)}
                    y={Math.max(12, Math.min(H - m.b - 2, y(p.v) + (p.dy || 4)))}
                    textAnchor={right ? 'end' : 'start'}
                    className="lbl"
                  >
                    {p.label}
                  </text>
                )}
              </g>
            );
          })}

          {endLabels.map(({ s, yy }, eIdx) => (
            <text
              key={`end-${eIdx}`}
              x={W - m.r + 8}
              y={yy + 3}
              className="lbl"
              style={{ fill: s.color }}
            >
              {s.short || s.name}
            </text>
          ))}

          {activeIndex !== null && (
            <g pointerEvents="none">
              <line
                x1={gx}
                x2={gx}
                y1={m.t}
                y2={H - m.b}
                style={{ stroke: 'var(--focus)' }}
                strokeOpacity={0.55}
                strokeWidth={1.2}
                strokeDasharray="3 2"
              />
              {series.map((s, k) => {
                const v = s.values[activeIndex];
                if (!Number.isFinite(v)) return null;
                return (
                  <g key={`adot-${k}`}>
                    <circle
                      cx={gx}
                      cy={y(v)}
                      r={6.5}
                      style={{ fill: s.color }}
                      fillOpacity={0.22}
                    />
                    <circle
                      cx={gx}
                      cy={y(v)}
                      r={3.5}
                      style={{ fill: s.color, stroke: 'var(--surface)' }}
                      strokeWidth={2}
                    />
                  </g>
                );
              })}
              <rect
                x={bx}
                y={Math.max(2, m.t)}
                width={tipBoxW}
                height={tipBoxH}
                rx={6}
                style={{ fill: 'var(--surface)', stroke: 'var(--line-strong)' }}
              />
              <text className="tip-text" y={Math.max(2, m.t) + 14}>
                {tipLines.map((line, k) => (
                  <tspan
                    key={`tline-${k}`}
                    x={bx + 9}
                    dy={k === 0 ? 0 : 14}
                    className={k === 0 ? 't0' : ''}
                  >
                    {line}
                  </tspan>
                ))}
              </text>
            </g>
          )}

          <rect
            className="tip-hit"
            x={m.l}
            y={m.t}
            width={Math.max(10, W - m.l - m.r)}
            height={Math.max(10, H - m.t - m.b)}
            tabIndex={0}
            role="slider"
            aria-label={`${ariaLabel}: use the arrow keys to read the values`}
            aria-valuemin={0}
            aria-valuemax={n - 1}
            aria-valuenow={curIdx}
            onPointerMove={handlePointer}
            onPointerDown={handlePointer}
            onPointerLeave={(e) => {
              if (e.pointerType === 'mouse') updateActiveIndex(null);
            }}
            onFocus={() => updateActiveIndex(lastIndex)}
            onBlur={() => updateActiveIndex(null)}
            onKeyDown={handleKeyDown}
          />
        </g>
      </svg>
    </div>
  );
};
