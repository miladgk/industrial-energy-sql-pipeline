import React from 'react';
import { LatestFingrid, fmt } from '../dataLoader';

/** Clock time in Finland, e.g. "08:15". */
function fiClock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Helsinki',
  });
}

/**
 * The newest 15-minute wind and consumption values from Fingrid's API, fetched
 * by the hourly GitHub Pages deploy into data/fingrid_latest.json. That file is
 * git-ignored, so the row stays hidden wherever it does not exist.
 */
export const LiveTicker: React.FC<{ latest: LatestFingrid | null }> = ({ latest }) => {
  if (!latest) return null;
  const ageMin = Math.max(1, Math.round((Date.now() - new Date(latest.generated_at).getTime()) / 60000));
  const age = ageMin < 90 ? `${ageMin} min` : `${Math.round(ageMin / 60)} h`;
  const w = latest.wind_production;
  return (
    <div
      id="live-ticker"
      aria-live="polite"
      title={`Fetched from Fingrid ${age} ago by the hourly GitHub Action`}
      className="hidden lg:flex items-center gap-1.5 px-2 py-1 rounded-lg glass-well text-[11px] font-mono text-slate-600 dark:text-slate-300 whitespace-nowrap"
    >
      <span className="relative flex w-1.5 h-1.5" aria-hidden="true">
        <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 motion-safe:animate-ping" />
        <span className="relative inline-flex w-1.5 h-1.5 rounded-full bg-emerald-500" />
      </span>
      <span className="hidden xl:inline text-slate-400 dark:text-slate-500">Latest Fingrid</span>
      <b id="tick-wind" className="tabular-nums text-emerald-600 dark:text-emerald-400">
        {fmt(Math.round(latest.wind_production.value_mw))} MW
      </b>
      <span>wind</span>
      <span className="text-slate-300 dark:text-slate-700">·</span>
      <b id="tick-cons" className="tabular-nums text-indigo-600 dark:text-indigo-300">
        {fmt(Math.round(latest.consumption.value_mw))} MW
      </b>
      <span>demand</span>
      <span className="text-slate-300 dark:text-slate-700">·</span>
      <span id="tick-age" className="tabular-nums text-slate-500 dark:text-slate-400">
        {fiClock(w.start_time)}–{fiClock(w.end_time)}
        <span> Finnish time</span>
      </span>
    </div>
  );
};
