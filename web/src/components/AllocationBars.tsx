import React, { useState } from 'react';
import { pct } from '../dataLoader';

export const AL_PARTS = [
  ['imports', 'Lower imports', 'var(--al-imports)'],
  ['hydro', 'Less hydro', 'var(--al-hydro)'],
  ['other', 'Less other production', 'var(--al-other)'],
  ['consumption', 'More consumption', 'var(--al-cons)'],
] as const;

const SEASON_NAMES: Record<string, string> = {
  winter: 'Winter',
  spring: 'Spring',
  summer: 'Summer',
  autumn: 'Autumn',
};

interface AllocationBarsProps {
  windAlloc: any;
  compact?: boolean;
}

export const AllocationBars: React.FC<AllocationBarsProps> = ({
  windAlloc,
  compact = false,
}) => {
  const [hovered, setHovered] = useState<{
    rowIndex: number;
    partKey: string | null;
  } | null>(null);

  if (!windAlloc || !windAlloc.wind) return null;

  const rows: Array<{
    name: string;
    shares: Record<string, { share: number; ci_low: number; ci_high: number }>;
    sep?: boolean;
  }> = [
    { name: 'Wind · year', shares: windAlloc.wind },
    ...(windAlloc.seasons || []).map((s: any) => ({
      name: SEASON_NAMES[s.season] || s.season,
      shares: s.wind,
    })),
    ...(windAlloc.nuclear
      ? [{ name: 'Nuclear · year', shares: windAlloc.nuclear, sep: true }]
      : []),
  ];

  const activeRow = hovered ? rows[hovered.rowIndex] : null;
  const activePart =
    hovered && hovered.partKey
      ? AL_PARTS.find(([k]) => k === hovered.partKey)
      : null;

  return (
    <div className={compact ? 'space-y-1' : 'space-y-2.5'}>
      <div className={compact ? 'space-y-1' : 'space-y-1.5'}>
        {rows.map((r, rIdx) => {
          const pos = AL_PARTS.map(([k, label, color]) => ({
            k,
            label,
            color,
            s: r.shares[k]?.share ?? 0,
            posVal: Math.max(r.shares[k]?.share ?? 0, 0),
          }));
          const tot = pos.reduce((a, p) => a + p.posVal, 0) || 1;

          return (
            <div
              key={r.name}
              className={`grid ${
                compact
                  ? 'grid-cols-[88px_1fr] gap-2'
                  : 'grid-cols-[105px_1fr] sm:grid-cols-[120px_1fr] gap-2.5'
              } items-center ${
                r.sep
                  ? compact
                    ? 'pt-1 border-t border-slate-200 dark:border-slate-800'
                    : 'pt-2 border-t border-slate-200 dark:border-slate-800'
                  : ''
              }`}
              tabIndex={0}
              onFocus={() => setHovered({ rowIndex: rIdx, partKey: null })}
              onBlur={() => setHovered(null)}
            >
              <span
                className={`${
                  compact ? 'text-[11px]' : 'text-xs'
                } font-mono text-slate-600 dark:text-slate-300 truncate`}
              >
                {r.name}
              </span>
              <div
                className={`flex ${
                  compact ? 'h-3.5' : 'h-6'
                } w-full rounded overflow-hidden bg-slate-100 dark:bg-slate-800/80 p-0.5 gap-0.5`}
              >
                {pos.map((p) => {
                  const widthPct = ((p.posVal / tot) * 100).toFixed(2);
                  return (
                    <span
                      key={p.k}
                      style={{
                        width: `${widthPct}%`,
                        backgroundColor: p.color,
                      }}
                      title={`${r.name} — ${p.label}: ${pct(p.s)}`}
                      className="h-full rounded-xs transition-opacity hover:opacity-85 cursor-pointer"
                      onPointerEnter={() =>
                        setHovered({ rowIndex: rIdx, partKey: p.k })
                      }
                      onPointerLeave={() => setHovered(null)}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend & Live Readout */}
      <div
        className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-1 ${
          compact ? 'pt-0.5 text-[10px]' : 'pt-1 text-xs'
        } text-slate-600 dark:text-slate-400`}
      >
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
          {AL_PARTS.map(([k, label, color]) => (
            <span key={k} className="inline-flex items-center gap-1">
              <i
                className="w-2 h-2 rounded-xs inline-block shrink-0"
                style={{ backgroundColor: color }}
              />
              <span>{label}</span>
            </span>
          ))}
        </div>

        {!compact && (
          <div
            className="font-mono text-[11px] text-slate-700 dark:text-slate-300 min-h-[18px]"
            aria-live="polite"
          >
            {activeRow ? (
              activePart ? (
                <span>
                  <strong className="text-slate-900 dark:text-white">
                    {activeRow.name}
                  </strong>{' '}
                  · {activePart[1].toLowerCase()}:{' '}
                  <strong className="text-sky-600 dark:text-sky-400">
                    {pct(activeRow.shares[activePart[0]]?.share ?? 0)}
                  </strong>{' '}
                  (95% CI {pct(activeRow.shares[activePart[0]]?.ci_low ?? 0)} to{' '}
                  {pct(activeRow.shares[activePart[0]]?.ci_high ?? 0)})
                </span>
              ) : (
                <span>
                  <strong className="text-slate-900 dark:text-white">
                    {activeRow.name}
                  </strong>
                  :{' '}
                  {AL_PARTS.map(
                    ([k, l]) =>
                      `${l.toLowerCase()} ${pct(activeRow.shares[k]?.share ?? 0)}`
                  ).join(' · ')}
                </span>
              )
            ) : (
              <span className="text-slate-400 dark:text-slate-500">
                Hover or focus a bar segment to inspect 95% Newey-West confidence intervals
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
