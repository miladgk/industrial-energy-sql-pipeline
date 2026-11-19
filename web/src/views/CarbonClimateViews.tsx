import React, { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import {
  ObservatoryData,
  fmt,
  dayFmt,
  dayWord,
  signed,
  hrs,
  hourSpan,
} from '../dataLoader';
import { SvgLineChart } from '../components/SvgLineChart';
import { SqlEnginePanel } from '../components/CodeInspector';
import { ChapterId } from './OverviewView';

interface ViewProps {
  data: ObservatoryData;
  onSelectChapter: (ch: ChapterId) => void;
}

type LensMode = 'pulse' | 'matrix' | 'sql';

const LensBar: React.FC<{
  lens: LensMode;
  setLens: (l: LensMode) => void;
  matrixLabel?: string;
}> = ({ lens, setLens, matrixLabel = 'Evidence Matrix' }) => (
  <div
    className="inline-flex items-center gap-0.5 p-0.5 glass-well rounded-lg"
    role="tablist"
    aria-label="Chapter view lens"
  >
    <button
      type="button"
      role="tab"
      aria-selected={lens === 'pulse'}
      onClick={() => setLens('pulse')}
      className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
        lens === 'pulse'
          ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
      }`}
    >
      Visual Pulse
    </button>
    <button
      type="button"
      role="tab"
      aria-selected={lens === 'matrix'}
      onClick={() => setLens('matrix')}
      className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
        lens === 'matrix'
          ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
      }`}
    >
      {matrixLabel}
    </button>
    <button
      type="button"
      role="tab"
      aria-selected={lens === 'sql'}
      onClick={() => setLens('sql')}
      className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
        lens === 'sql'
          ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
      }`}
    >
      SQL &amp; Engine
    </button>
  </div>
);

/* ─────────────────────────────────────────────────────────
   CHAPTER: CO2 INTENSITY FORECAST & SQL REGRESSION
   ───────────────────────────────────────────────────────── */
export const Co2View: React.FC<ViewProps> = ({ data }) => {
  const { co2: c, sql, errors } = data;
  const [lens, setLens] = useState<'pulse' | 'sql'>('pulse');
  const [co2SyncIdx, setCo2SyncIdx] = useState<number | null>(null);

  if (!c || !c.hours) {
    return (
      <div className="p-6 glass-card rounded-xl">
        <p className="text-sm text-rose-600 dark:text-rose-400">
          {errors.co2 || 'Loading CO₂ intensity forecast...'}
        </p>
      </div>
    );
  }

  const g = (v: number) => `${fmt(v, 1)} g`;
  const when = dayWord(c.target_day);
  const H = c.hours;
  const idx = (h: any) => H.findIndex((x: any) => x.hour_start === h.hour_start);
  const P = c.yesterday?.hours || [];
  const canSyncCo2 = H.length > 0 && P.length === H.length;
  const b = c.backtest;

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      <div className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-emerald-600 dark:text-emerald-400">
            ROLLING SQL REGRESSION (REGR_SLOPE)
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            When is electricity cleanest {when}?
          </h1>
        </div>

        <div className="inline-flex items-center gap-0.5 p-0.5 glass-well rounded-lg">
          <button
            type="button"
            onClick={() => setLens('pulse')}
            className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              lens === 'pulse'
                ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Visual Pulse &amp; Verification
          </button>
          <button
            type="button"
            onClick={() => setLens('sql')}
            className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              lens === 'sql'
                ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            SQL &amp; Engine
          </button>
        </div>
      </div>

      {/* 4 KPIs */}
      <div className="flex-none grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-emerald-600 dark:text-emerald-400 leading-tight">
            {hourSpan(c.cleanest_hour.hour_fi)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            cleanest hour ({g(c.cleanest_hour.co2)}/kWh)
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-critical">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-rose-600 dark:text-rose-400 leading-tight">
            {hourSpan(c.dirtiest_hour.hour_fi)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            dirtiest hour ({g(c.dirtiest_hour.co2)}/kWh)
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-slate-900 dark:text-white leading-tight">
            {b ? `${fmt(b.pick_in_top3_pct, 0)}%` : '–'}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            days picked hour was in top 3 cleanest
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-sky-600 dark:text-sky-400 leading-tight">
            {b ? `${fmt(b.saving_pct, 1)}%` : '–'}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            CO₂ saved vs average hour ({b ? fmt(b.days) : '–'} days)
          </span>
        </div>
      </div>

      {/* Main Split Stage */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        <div className="lg:col-span-4 glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-3">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              THE 3-SECOND VERDICT
            </div>
            <p className="text-xs sm:text-[13px] text-slate-700 dark:text-slate-200 leading-relaxed">
              Charging a 50 kWh EV during the cleanest 3-hour window (
              <strong className="font-mono text-emerald-600 dark:text-emerald-400">
                {hourSpan(c.best_3h.hour_fi, 3)}
              </strong>
              ) instead of the dirtiest hour avoids{' '}
              <strong className="font-mono text-slate-900 dark:text-white">
                ~{fmt((50 * (c.dirtiest_hour.co2 - c.best_3h.co2)) / 1000, 2)}{' '}
                kg of CO₂
              </strong>
              .
            </p>

            {b && (
              <div className="p-3 rounded-lg glass-well text-[11.5px] text-slate-600 dark:text-slate-300 leading-relaxed">
                <strong className="text-slate-900 dark:text-white block mb-0.5">
                  Pure SQL Model Accuracy:
                </strong>
                Refitted daily in PostgreSQL using 60-day rolling linear
                regression (<code>regr_slope</code>) of CO₂ intensity against
                residual load. Model MAE is{' '}
                <strong className="font-mono">{g(b.mae_model_g)}</strong> vs.{' '}
                <span className="font-mono">{g(b.mae_naive_g)}</span> naive
                persistence.
              </div>
            )}
          </div>

          <div className="text-xs font-mono text-slate-500 dark:text-slate-400 pt-2.5 border-t border-slate-200/70 dark:border-white/10 shrink-0">
            Daily mean forecast: {g(c.day_mean_forecast)}/kWh
          </div>
        </div>

        <div className="lg:col-span-8 min-h-0 flex flex-col overflow-hidden">
          {lens === 'pulse' ? (
            <div key="pulse" className="lens-enter h-full glass-card rounded-xl p-3.5 flex flex-col justify-between gap-2 min-h-0 overflow-hidden">
              <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                <div className="flex-none text-xs font-bold text-slate-900 dark:text-white mb-0.5">
                  Hourly CO₂ forecast {when} (Finnish time)
                </div>
                <div className="flex-1 min-h-0">
                  <SvgLineChart
                    height={110}
                    yUnit="g CO₂/kWh"
                    ariaLabel="Forecast CO2 intensity by hour"
                    syncIndex={canSyncCo2 ? co2SyncIdx : undefined}
                    onIndexChange={canSyncCo2 ? setCo2SyncIdx : undefined}
                    referenceLines={[
                      {
                        y: c.day_mean_forecast,
                        label: `day mean ${fmt(c.day_mean_forecast, 0)} g`,
                        color: 'var(--syn)',
                        position: 'right',
                      },
                    ]}
                    series={[
                      {
                        name: 'CO₂ Forecast',
                        values: H.map((x: any) => x.co2_forecast),
                        color: 'var(--fc-da)',
                        width: 2,
                      },
                    ]}
                    labels={H.map((x: any) => hrs(x.hour_fi))}
                    points={[
                      {
                        i: idx(c.cleanest_hour),
                        v: c.cleanest_hour.co2,
                        color: 'var(--real)',
                        label: `clean ${hrs(c.cleanest_hour.hour_fi)}`,
                        dy: 13,
                      },
                      {
                        i: idx(c.dirtiest_hour),
                        v: c.dirtiest_hour.co2,
                        color: 'var(--fault)',
                        label: `peak ${hrs(c.dirtiest_hour.hour_fi)}`,
                        dy: -6,
                      },
                    ]}
                    xTick={(i, l) => (i % 6 === 0 ? l : null)}
                    tipTitle={(l) => `${l} Finnish time`}
                    tipValue={(v) => `${fmt(v, 1)} gCO₂/kWh`}
                  />
                </div>
              </div>

              <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                <div className="flex-none flex flex-wrap items-center justify-between gap-2 mb-0.5">
                  <span className="text-xs font-bold text-slate-900 dark:text-white">
                    Yesterday: forecast against measured reality
                  </span>
                  <span className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
                    Solid = Measured · Dashed = Forecast
                  </span>
                </div>
                <div className="flex-1 min-h-0">
                  <SvgLineChart
                    height={110}
                    directLabels={true}
                    yUnit="g CO₂/kWh"
                    ariaLabel="Yesterday CO2 forecast vs actual"
                    syncIndex={canSyncCo2 ? co2SyncIdx : undefined}
                    onIndexChange={canSyncCo2 ? setCo2SyncIdx : undefined}
                    series={[
                      {
                        name: 'Measured',
                        short: 'Actual',
                        values: P.map((x: any) => x.co2_actual ?? NaN),
                        color: 'var(--ink)',
                        width: 2,
                      },
                      {
                        name: 'Forecast',
                        short: 'Forecast',
                        values: P.map((x: any) => x.co2_forecast),
                        color: 'var(--fc-da)',
                        width: 2,
                        dash: '4 4',
                      },
                    ]}
                    labels={P.map((x: any) => hrs(x.hour_fi))}
                    xTick={(i, l) => (i % 4 === 0 ? l : null)}
                    tipTitle={(l) => `${l} Finnish time`}
                    tipValue={(v) => `${fmt(v, 1)} gCO₂/kWh`}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div key="sql" className="lens-enter h-full min-h-0">
              <SqlEnginePanel
                sqlData={sql}
                files={[
                  {
                    label: 'CO₂ Forecast Schema & Rolling Regression',
                    filePath: 'sql/schema/14_co2_forecast.sql',
                  },
                ]}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/* ─────────────────────────────────────────────────────────
   CHAPTER: GRID EVENTS & 50 HZ FREQUENCY EXCURSIONS
   ───────────────────────────────────────────────────────── */
export const EventsView: React.FC<ViewProps> = ({ data }) => {
  const { events: d, sql, errors } = data;
  const [lens, setLens] = useState<LensMode>('pulse');

  if (!d || !d.counts) {
    return (
      <div className="p-6 glass-card rounded-xl">
        <p className="text-sm text-rose-600 dark:text-rose-400">
          {errors.events || 'Loading grid events log...'}
        </p>
      </div>
    );
  }

  const c = d.counts;
  const freqYear = (c.frequency_low?.year || 0) + (c.frequency_high?.year || 0);
  const M = d.frequency_by_minute || [];
  const freqAvg =
    M.length > 0
      ? M.reduce((acc: number, m: any) => acc + Number(m.pct_outside || 0), 0) /
        M.length
      : null;
  const worst =
    M.length > 0
      ? M.reduce(
          (a: any, m: any) => (m.pct_outside > a.pct_outside ? m : a),
          M[0]
        )
      : null;

  const fiTime = (iso: string) =>
    new Date(iso).toLocaleString('en-GB', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Helsinki',
    });

  const peak = (e: any) =>
    e.unit === 'Hz'
      ? `${fmt(e.peak, 3)} Hz`
      : e.unit === 'MW'
      ? `${signed(e.peak)} MW`
      : e.unit === 'GWs'
      ? `${fmt(e.peak, 0)} GWs`
      : `${fmt(e.peak, 0)} €/MWh`;

  const lasted = (e: any) => {
    const m = Math.round(
      (new Date(e.end_time).getTime() - new Date(e.start_time).getTime()) /
        60000
    );
    return m >= 120 ? `${fmt(m / 60, 1)} h` : `${m} min`;
  };

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      <div className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-amber-600 dark:text-amber-400">
            ISLANDS-AND-GAPS SQL ANOMALY DETECTION
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Grid frequency excursions &amp; unusual events (last 12 months)
          </h1>
        </div>

        <LensBar
          lens={lens}
          setLens={setLens}
          matrixLabel="Recent & Largest Events"
        />
      </div>

      {/* 4 KPIs */}
      <div className="flex-none grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-amber-600 dark:text-amber-400 leading-tight">
            {fmt(freqYear)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            frequency excursions outside 49.9–50.1 Hz
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-critical">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-rose-600 dark:text-rose-400 leading-tight">
            {fmt(c.nuclear_drop?.year)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            fast nuclear drops (≥400 MW)
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-slate-900 dark:text-white leading-tight">
            {fmt(c.low_inertia?.year)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            low Nordic inertia periods
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-critical">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-slate-900 dark:text-white leading-tight">
            {fmt(c.price_spike?.year)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            imbalance price spikes (≥€1,000)
          </span>
        </div>
      </div>

      {/* Main Split Stage */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        <div className="lg:col-span-4 glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-3">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              THE 3-SECOND VERDICT
            </div>
            {worst && (
              <p className="text-xs sm:text-[13px] text-slate-700 dark:text-slate-200 leading-relaxed">
                At minute{' '}
                <strong className="font-mono text-rose-600 dark:text-rose-400">
                  :{String(worst.minute_of_hour).padStart(2, '0')}
                </strong>{' '}
                of the hour, Nordic grid frequency exits its 49.9–50.1 Hz band
                most frequently (
                <strong className="font-mono">
                  {fmt(worst.pct_outside, 1)}%
                </strong>
                ) as hourly generation schedules step abruptly while physical
                demand changes smoothly.
              </p>
            )}

            <div className="p-3 rounded-lg glass-well text-[11.5px] text-slate-600 dark:text-slate-300 leading-relaxed">
              <strong className="text-slate-900 dark:text-white block mb-0.5">
                Islands-and-Gaps SQL Detection:
              </strong>
              Consecutive anomalous observations are stitched into discrete
              physical episodes directly in PostgreSQL window functions,
              capturing duration and peak severity.
            </div>
          </div>

          <button
            type="button"
            onClick={() => setLens('matrix')}
            className="text-xs font-mono text-sky-600 dark:text-sky-400 hover:underline text-left pt-2.5 border-t border-slate-200/70 dark:border-white/10 shrink-0 cursor-pointer"
          >
            Inspect latest &amp; largest anomaly episodes →
          </button>
        </div>

        <div className="lg:col-span-8 min-h-0 flex flex-col overflow-hidden">
          {lens === 'pulse' && (
            <div key="pulse" className="lens-enter h-full glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-hidden">
              <h3 className="flex-none text-xs sm:text-sm font-bold text-slate-900 dark:text-white mb-1">
                Off-target frequency by minute of the hour (% outside 49.9–50.1
                Hz)
              </h3>
              <div className="flex-1 min-h-0 overflow-hidden">
                <SvgLineChart
                  height={210}
                  yUnit="% outside 49.9–50.1 Hz"
                  ariaLabel="Frequency excursions by minute of the hour"
                  referenceLines={
                    freqAvg != null
                      ? [
                          {
                            y: freqAvg,
                            label: `hourly baseline ${fmt(freqAvg, 2)}%`,
                            color: 'var(--syn)',
                            position: 'right',
                          },
                        ]
                      : []
                  }
                  series={[
                    {
                      name: 'Outside 49.9–50.1 Hz',
                      values: M.map((m: any) => m.pct_outside),
                      color: 'var(--fc-da)',
                      width: 2,
                    },
                  ]}
                  labels={M.map(
                    (m: any) => `:${String(m.minute_of_hour).padStart(2, '0')}`
                  )}
                  points={
                    worst
                      ? [
                          {
                            i: M.indexOf(worst),
                            v: worst.pct_outside,
                            color: 'var(--fault)',
                            label: `:${worst.minute_of_hour}`,
                            dy: -6,
                          },
                        ]
                      : []
                  }
                  xTick={(i, l) => (i % 15 === 0 ? l : null)}
                  tipTitle={(l) => `Minute ${l} of the hour`}
                  tipValue={(v) => `${fmt(v, 2)}% outside band`}
                />
              </div>
              <span className="flex-none pt-1 text-[11px] text-slate-500 dark:text-slate-400">
                Notice the sharp spikes at :00 and :59 when hourly market blocks
                transition.
              </span>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full glass-card rounded-xl p-4 overflow-auto thin-scroll grid grid-cols-1 xl:grid-cols-12 gap-4">
              <div className="xl:col-span-7 space-y-2">
                <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400">
                  Latest events
                </h3>
                <div className="glass-well rounded-lg overflow-hidden">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                        <th className="py-2 px-2.5 text-left">
                          When (FI time)
                        </th>
                        <th className="py-2 px-2.5 text-left">Event</th>
                        <th className="py-2 px-2.5 text-right">Peak</th>
                        <th className="py-2 px-2.5 text-right">Lasted</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                      {(d.recent || []).map((e: any, idx: number) => (
                        <tr key={idx}>
                          <td className="py-2 px-2.5 font-mono">
                            {fiTime(e.start_time)}
                          </td>
                          <td className="py-2 px-2.5 font-medium">
                            {c[e.kind]?.label || e.kind}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono font-semibold">
                            {peak(e)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono text-slate-500">
                            {lasted(e)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="xl:col-span-5 space-y-2">
                <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400">
                  Largest anomalies of the year
                </h3>
                <div className="glass-well rounded-lg overflow-hidden">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                        <th className="py-2 px-2.5 text-left">Event</th>
                        <th className="py-2 px-2.5 text-left">When</th>
                        <th className="py-2 px-2.5 text-right">Peak</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                      {Object.keys(d.top || {})
                        .filter((k) => d.top[k].length > 0)
                        .map((k) => {
                          const e = d.top[k][0];
                          return (
                            <tr key={k}>
                              <td className="py-2 px-2.5 font-medium">
                                {c[k]?.label || k}
                              </td>
                              <td className="py-2 px-2.5 font-mono">
                                {fiTime(e.start_time)}
                              </td>
                              <td className="py-2 px-2.5 text-right font-mono font-semibold text-rose-600 dark:text-rose-400">
                                {peak(e)}
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {lens === 'sql' && (
            <div key="sql" className="lens-enter h-full min-h-0">
              <SqlEnginePanel
                sqlData={sql}
                files={[
                  {
                    label: 'Grid Events Islands-and-Gaps SQL',
                    filePath: 'sql/schema/15_grid_events.sql',
                  },
                ]}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/* ─────────────────────────────────────────────────────────
   CHAPTER: THERMODYNAMICS OF COLD
   ───────────────────────────────────────────────────────── */
export const ColdView: React.FC<ViewProps> = ({ data, onSelectChapter }) => {
  const { temperature: t, sql, errors } = data;
  const [lens, setLens] = useState<'pulse' | 'sql'>('pulse');

  if (!t || !t.fits) {
    return (
      <div className="p-6 glass-card rounded-xl">
        <p className="text-sm text-rose-600 dark:text-rose-400">
          {errors.temperature || 'Loading temperature sensitivity data...'}
        </p>
      </div>
    );
  }

  const wd = t.fits.find((f: any) => f.day_type === 'weekday');
  const we = t.fits.find((f: any) => f.day_type === 'weekend');
  const deg = (v: number) => `${v < 0 ? '−' : ''}${fmt(Math.abs(v), 1)} °C`;
  const B = t.bins || [];
  const freezeIdx = B.findIndex((b: any) => b.from_c <= 0 && b.to_c > 0);
  const balanceIdx = B.findIndex(
    (b: any) =>
      b.from_c <= wd.balance_point_c && b.to_c > wd.balance_point_c
  );
  const labels = B.map((b: any) => `${b.from_c}`);
  const model = B.map(
    (b: any) =>
      wd.base_mw +
      wd.mw_per_degree *
        Math.max(wd.balance_point_c - (b.from_c + b.to_c) / 2, 0)
  );
  const c = t.coldest_day;

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      <div className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-600 dark:text-sky-400">
            HEATING THRESHOLD &amp; PIECEWISE REGRESSION
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Consumption vs. Outdoor Temperature
          </h1>
        </div>

        <div className="inline-flex items-center gap-0.5 p-0.5 glass-well rounded-lg">
          <button
            type="button"
            onClick={() => setLens('pulse')}
            className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              lens === 'pulse'
                ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Visual Pulse
          </button>
          <button
            type="button"
            onClick={() => setLens('sql')}
            className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              lens === 'sql'
                ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            SQL &amp; Engine
          </button>
        </div>
      </div>

      {/* 3 KPIs */}
      <div className="flex-none grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-sky-600 dark:text-sky-400 leading-tight">
            +{fmt(Math.round(wd.mw_per_degree))} MW
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            per °C below {wd.balance_point_c} °C (weekday, r² {fmt(wd.r2, 2)})
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-indigo">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-pink-600 dark:text-pink-400 leading-tight">
            +{fmt(Math.round(we.mw_per_degree))} MW
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            per °C below {we.balance_point_c} °C (weekend)
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-critical">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-slate-900 dark:text-white leading-tight">
            {fmt(Math.round(c.consumption_mw))} MW
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            coldest day demand ({deg(c.temp_c)})
          </span>
        </div>
      </div>

      {/* Main Split Stage */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        <div className="lg:col-span-4 glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-3">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              THE 3-SECOND VERDICT
            </div>
            <p className="text-xs sm:text-[13px] text-slate-700 dark:text-slate-200 leading-relaxed">
              Below{' '}
              <strong className="font-mono text-slate-900 dark:text-white">
                {wd.balance_point_c} °C
              </strong>
              , every 1 °C drop adds{' '}
              <strong className="font-mono text-sky-600 dark:text-sky-400">
                ~{fmt(Math.round(wd.mw_per_degree))} MW
              </strong>{' '}
              of electric heating load across Finland (population-weighted mean
              of Helsinki, Jyväskylä, Oulu, and Rovaniemi).
            </p>
            <div className="p-3 rounded-lg glass-well text-[11.5px] text-slate-600 dark:text-slate-300 leading-relaxed">
              Temperature alone explains{' '}
              <strong className="font-mono text-slate-900 dark:text-white">
                {fmt(wd.r2 * 100, 0)}%
              </strong>{' '}
              of daily weekday consumption variance. What remains unexplained by
              weather reveals human industrial shocks.
            </div>
          </div>

          <div className="pt-2.5 border-t border-slate-200/70 dark:border-white/10 shrink-0">
            <button
              type="button"
              onClick={() => onSelectChapter('strikes')}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
            >
              <span>What weather cannot explain: the 2024 strikes</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="lg:col-span-8 min-h-0 flex flex-col overflow-hidden">
          {lens === 'pulse' ? (
            <div key="pulse" className="lens-enter h-full glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-hidden">
              <div className="flex-none flex flex-wrap items-center justify-between gap-2 mb-1">
                <h3 className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                  Daily average consumption vs. outdoor temperature
                </h3>
                <div className="flex items-center gap-4 text-xs text-slate-600 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--fc-da)' }}
                    />
                    <span>Weekdays</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--fc-id)' }}
                    />
                    <span>Weekends</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--ink-2)' }}
                    />
                    <span>Piecewise model</span>
                  </span>
                </div>
              </div>

              <div className="flex-1 min-h-0 overflow-hidden">
                <SvgLineChart
                  height={210}
                  forceZero={false}
                  yUnit="MW, daily average"
                  ariaLabel="Consumption against temperature"
                  vLines={[
                    ...(freezeIdx >= 0
                      ? [
                          {
                            i: freezeIdx,
                            label: '0 °C freeze',
                            color: 'var(--rec)',
                            dash: '3 3',
                          },
                        ]
                      : []),
                    ...(balanceIdx >= 0
                      ? [
                          {
                            i: balanceIdx,
                            label: `${wd.balance_point_c} °C heat onset`,
                            color: 'var(--syn)',
                            dash: '4 3',
                          },
                        ]
                      : []),
                  ]}
                  series={[
                    {
                      name: 'Weekdays',
                      short: 'Weekday',
                      values: B.map((b: any) => b.weekday_mw ?? NaN),
                      color: 'var(--fc-da)',
                      width: 2,
                      dots: true,
                    },
                    {
                      name: 'Weekends',
                      short: 'Weekend',
                      values: B.map((b: any) => b.weekend_mw ?? NaN),
                      color: 'var(--fc-id)',
                      width: 1.5,
                    },
                    {
                      name: 'Model',
                      short: 'Fit',
                      values: model,
                      color: 'var(--ink-2)',
                      width: 1.2,
                      dash: '4 3',
                    },
                  ]}
                  labels={labels}
                  xTick={(i, l) =>
                    i % 3 === 0
                      ? `${(+l < 0 ? '−' : '') + Math.abs(+l)} °C`
                      : null
                  }
                  tipTitle={(l) => `${l}°C band`}
                  tipValue={(v) => `${fmt(Math.round(v))} MW`}
                />
              </div>

              <span className="flex-none pt-1 text-[11px] text-slate-500 dark:text-slate-400">
                Above {wd.balance_point_c} °C, heating demand flattens to the
                industrial &amp; baseload floor.
              </span>
            </div>
          ) : (
            <div key="sql" className="lens-enter h-full min-h-0">
              <SqlEnginePanel
                sqlData={sql}
                files={[
                  {
                    label: 'Temperature Sensitivity SQL',
                    filePath: 'sql/analysis/23_temperature_sensitivity.sql',
                  },
                ]}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/* ─────────────────────────────────────────────────────────
   CHAPTER: THE 2024 INDUSTRIAL STRIKES
   ───────────────────────────────────────────────────────── */
export const StrikesView: React.FC<ViewProps> = ({ data }) => {
  const { strikes: d, sql, errors } = data;
  const [lens, setLens] = useState<LensMode>('pulse');

  if (!d || !d.events) {
    return (
      <div className="p-6 glass-card rounded-xl">
        <p className="text-sm text-rose-600 dark:text-rose-400">
          {errors.strikes || 'Loading 2024 strike counterfactual analysis...'}
        </p>
      </div>
    );
  }

  const mw = (n: number) =>
    `${n < 0 ? '−' : n > 0 ? '+' : ''}${fmt(Math.abs(Math.round(n)))} MW`;
  const big = d.events.reduce(
    (a: any, e: any) => (Math.abs(e.gwh) > Math.abs(a.gwh) ? e : a),
    d.events[0]
  );
  const dd = big.daily || [];
  const pv = (p: number) => (p < 1 / 40 ? '< 0.025' : fmt(p, 2));

  const clear = d.events.filter((e: any) => e.placebo_p < 0.05);
  const L = d.monthly_link?.manufacturing?.all_months;

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      <div className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-indigo-600 dark:text-indigo-400">
            COUNTERFACTUAL DEMAND &amp; PLACEBO INFERENCE
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            How much electricity did the 2024 strikes take away?
          </h1>
        </div>

        <LensBar
          lens={lens}
          setLens={setLens}
          matrixLabel="All 3 Strikes & Industrial Link"
        />
      </div>

      {/* 3 KPIs */}
      <div className="flex-none grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-indigo">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-indigo-600 dark:text-indigo-400 leading-tight">
            {fmt(Math.abs(big.gwh), 0)} GWh
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            not used in {big.name.toLowerCase()} (
            {dayFmt(`${big.start}T12:00:00Z`).replace(/ \d{4}$/, '')} –{' '}
            {dayFmt(`${big.end}T12:00:00Z`)})
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-slate-900 dark:text-white leading-tight">
            {mw(big.mean_mw)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            average drop every hour of the strike
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-critical">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-rose-600 dark:text-rose-400 leading-tight">
            {fmt(big.share_pct, 1)}%
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            of what Finland would have used
          </span>
        </div>
      </div>

      {/* Main Split Stage */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        <div className="lg:col-span-4 glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-3">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              THE 3-SECOND VERDICT
            </div>
            <p className="text-xs sm:text-[13px] text-slate-700 dark:text-slate-200 leading-relaxed">
              {clear
                .map(
                  (e: any) =>
                    `The ${e.name.toLowerCase()} cut national consumption by ${mw(
                      Math.abs(e.mean_mw)
                    ).replace(/^[−+]/, '')} (${fmt(
                      Math.abs(e.share_pct),
                      1
                    )}%), far beyond ordinary model noise across ${
                      d.events[0].placebo_n
                    } strike-free placebo windows.`
                )
                .join(' ')}
            </p>
            <div className="p-3 rounded-lg glass-well text-[11.5px] text-slate-600 dark:text-slate-300 leading-relaxed">
              <strong className="text-slate-900 dark:text-white block mb-0.5">
                Counterfactual Model:
              </strong>
              Trained on every strike-free hour (
              {dayFmt(`${d.window_start}T12:00:00Z`)} –{' '}
              {dayFmt(`${d.window_end}T12:00:00Z`)}) using temperature splines,
              daylight, calendar, and slow trend.
            </div>
          </div>

          <button
            type="button"
            onClick={() => setLens('matrix')}
            className="text-xs font-mono text-sky-600 dark:text-sky-400 hover:underline text-left pt-2.5 border-t border-slate-200/70 dark:border-white/10 shrink-0 cursor-pointer"
          >
            Inspect placebo p-values &amp; Statistics Finland output →
          </button>
        </div>

        <div className="lg:col-span-8 min-h-0 flex flex-col overflow-hidden">
          {lens === 'pulse' && (
            <div key="pulse" className="lens-enter h-full glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-hidden">
              <div className="flex-none flex flex-wrap items-center justify-between gap-2 mb-1">
                <h3 className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                  {big.name} · Daily mean consumption vs. expected without
                  strike
                </h3>
                <div className="flex items-center gap-4 text-xs text-slate-600 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--cons)' }}
                    />
                    <span>Measured</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--ink-2)' }}
                    />
                    <span>Expected without strike (dashed)</span>
                  </span>
                </div>
              </div>

              <div className="flex-1 min-h-0 overflow-hidden">
                <SvgLineChart
                  height={210}
                  forceZero={false}
                  directLabels={false}
                  yUnit="MW"
                  ariaLabel="Measured consumption against what the model expected without the strike"
                  series={[
                    {
                      name: 'Measured',
                      short: 'Measured',
                      values: dd.map((x: any) => x.actual_mw),
                      color: 'var(--cons)',
                      width: 2,
                    },
                    {
                      name: 'Expected without the strike',
                      short: 'Expected',
                      values: dd.map((x: any) => x.counterfactual_mw),
                      color: 'var(--ink-2)',
                      width: 1.6,
                      dash: '4 3',
                    },
                  ]}
                  labels={dd.map((x: any) => x.day)}
                  xTick={(i, l) =>
                    i % 7 === 0
                      ? dayFmt(`${l}T12:00:00Z`).replace(/ \d{4}$/, '')
                      : null
                  }
                  tipTitle={(l) => dayFmt(`${l}T12:00:00Z`)}
                  tipValue={(v) => `${fmt(Math.round(v))} MW`}
                  tipExtra={(i) => [
                    `Gap: ${mw(dd[i].actual_mw - dd[i].counterfactual_mw)}`,
                  ]}
                />
              </div>
              <span className="flex-none pt-1 text-[11px] text-slate-500 dark:text-slate-400">
                Pulp, paper, and metal refineries halted during the four-week
                port and rail blockade.
              </span>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full glass-card rounded-xl p-4 overflow-auto thin-scroll space-y-4">
              <div>
                <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400 mb-2">
                  All three 2024 strikes &amp; placebo permutation significance
                </h3>
                <div className="glass-well rounded-lg overflow-hidden">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                        <th className="py-2.5 px-3 text-left">Strike</th>
                        <th className="py-2.5 px-3 text-right">Effect</th>
                        <th className="py-2.5 px-3 text-right">Placebo MW</th>
                        <th className="py-2.5 px-3 text-right">p-value</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                      {d.events.map((e: any) => (
                        <tr key={e.name} className={e.placebo_p < 0.05 ? 'telemetry-row-crit' : ''}>
                          <td className="py-2.5 px-3">
                            <strong className="block text-slate-900 dark:text-white">
                              {e.name}
                            </strong>
                            <span className="text-[11px] text-slate-500 dark:text-slate-400">
                              {dayFmt(`${e.start}T12:00:00Z`).replace(
                                / \d{4}$/,
                                ''
                              )}{' '}
                              – {dayFmt(`${e.end}T12:00:00Z`)}: {e.what}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono">
                            <strong className="block text-slate-900 dark:text-white">
                              {mw(e.mean_mw)}
                            </strong>
                            <span className="text-[11px] text-slate-500">
                              {fmt(e.gwh, 0)} GWh
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono">
                            {mw(e.placebo_band_mw[0]).replace(' MW', '')} to{' '}
                            {mw(e.placebo_band_mw[1]).replace(' MW', '')}
                          </td>
                          <td className={`py-2.5 px-3 text-right font-mono font-semibold ${e.placebo_p < 0.05 ? 'text-rose-600 dark:text-rose-400' : ''}`}>
                            {pv(e.placebo_p)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {L && (
                <div className="p-3.5 rounded-lg glass-well text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                  <strong className="text-slate-900 dark:text-white block mb-1">
                    Does consumption follow monthly industrial output? (
                    {L.n} months, Statistics Finland):
                  </strong>
                  Levels correlate (r = {fmt(L.r_levels, 2)}) due to shared
                  trend, but month-to-month changes do not (r ={' '}
                  {fmt(L.r_changes, 2)}, slope = {fmt(L.slope_with_trend, 1)} ±{' '}
                  {fmt(L.slope_se, 1)} MW per index point, t ={' '}
                  {fmt(L.slope_t, 2)}). Ordinary monthly industrial fluctuations
                  are too small to stand out from weather noise, whereas major
                  stoppages like the March–April 2024 strike stand out clearly.
                </div>
              )}
            </div>
          )}

          {lens === 'sql' && (
            <div key="sql" className="lens-enter h-full min-h-0">
              <SqlEnginePanel
                sqlData={sql}
                files={[
                  {
                    label: 'Hourly Consumption Panel SQL',
                    filePath: 'sql/analysis/28_consumption_hourly.sql',
                  },
                  {
                    label: 'Strike Counterfactual Python',
                    filePath: 'src/strike_effect.py',
                  },
                ]}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
