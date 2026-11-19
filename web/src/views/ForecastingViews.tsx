import React, { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import {
  ObservatoryData,
  fmt,
  dayFmt,
  dayWord,
  signed,
  hrs,
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
   CHAPTER: FINGRID FORECASTS VS. REALITY
   ───────────────────────────────────────────────────────── */
export const ForecastsView: React.FC<ViewProps> = ({
  data,
  onSelectChapter,
}) => {
  const { scorecard, sql, errors } = data;
  const [variable, setVariable] = useState<'wind' | 'consumption'>('wind');
  const [lens, setLens] = useState<LensMode>('pulse');

  if (!scorecard || !scorecard.summary) {
    return (
      <div className="p-6 glass-card rounded-xl">
        <p className="text-sm text-rose-600 dark:text-rose-400">
          {errors.scorecard || 'Loading forecast scorecard data...'}
        </p>
      </div>
    );
  }

  const wind = variable === 'wind';
  const da = scorecard.summary.find(
    (r: any) => r.variable === variable && r.product === 'day_ahead'
  );
  const id = scorecard.summary.find(
    (r: any) => r.variable === variable && r.product === 'intraday'
  );
  const change =
    da && id ? Math.round((1 - id.mae_mw / da.mae_mw) * 100) : 0;

  const hours = [...Array(24).keys()];
  const byH = (p: string) =>
    hours.map(
      (h) =>
        (
          scorecard.by_hour.find(
            (x: any) =>
              x.variable === variable && x.product === p && x.hour_fi === h
          ) || {}
        ).mae_mw ?? NaN
    );
  const daH = byH('day_ahead');
  const idH = byH('intraday');

  const worstH = hours.reduce((a, b) => (daH[b] > daH[a] ? b : a), 0);
  const bestH = hours.reduce((a, b) => (daH[b] < daH[a] ? b : a), 0);

  const biggestMisses = (scorecard.biggest_misses || []).filter(
    (r: any) => r.variable === variable
  );

  const b = scorecard.balancing;
  const binLabel = (r: any) =>
    r.bin_from_mw == null
      ? 'below −1,500 MW'
      : r.bin_to_mw == null
      ? '+1,500 MW or more'
      : `${signed(r.bin_from_mw)} to ${signed(r.bin_to_mw)} MW`;

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      {/* 3-Second Top Header & Lens Bar */}
      <div className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-600 dark:text-sky-400">
            FORECAST SCORECARD &amp; MFRR BALANCING
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Fingrid Forecasts vs. Reality
          </h1>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div
            className="inline-flex items-center gap-0.5 p-0.5 glass-well rounded-lg"
            role="group"
            aria-label="Forecast variable"
          >
            <button
              type="button"
              onClick={() => setVariable('wind')}
              className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
                variable === 'wind'
                  ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              Wind
            </button>
            <button
              type="button"
              onClick={() => setVariable('consumption')}
              className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
                variable === 'consumption'
                  ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              Consumption
            </button>
          </div>

          <LensBar
            lens={lens}
            setLens={setLens}
            matrixLabel="Worst Days & Balancing"
          />
        </div>
      </div>

      {/* 4-KPI Telemetry Strip */}
      {da && id && (
        <div className="flex-none grid grid-cols-2 lg:grid-cols-4 gap-2.5">
          <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
            <strong className="block text-lg sm:text-xl font-mono font-bold text-sky-600 dark:text-sky-400 leading-tight">
              {fmt(Math.round(da.mae_mw))} MW
            </strong>
            <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
              {wind
                ? `day-ahead miss (${fmt(da.mae_pct_of_capacity, 1)}% fleet)`
                : `day-ahead miss (${fmt(da.wape_pct, 1)}%)`}
            </span>
          </div>
          <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
            <strong className="block text-lg sm:text-xl font-mono font-bold text-pink-600 dark:text-pink-400 leading-tight">
              {fmt(Math.round(id.mae_mw))} MW
            </strong>
            <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
              intraday miss (
              {change >= 0 ? `${change}% smaller` : `${-change}% larger`})
            </span>
          </div>
          <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
            <strong className="block text-lg sm:text-xl font-mono font-bold text-amber-600 dark:text-amber-400 leading-tight">
              {signed(da.bias_mw)} MW
            </strong>
            <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
              day-ahead systematic bias
            </span>
          </div>
          <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-critical">
            <strong className="block text-lg sm:text-xl font-mono font-bold text-rose-600 dark:text-rose-400 leading-tight">
              {fmt(Math.round(da.p95_abs_error_mw))} MW
            </strong>
            <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
              95th percentile tail error
            </span>
          </div>
        </div>
      )}

      {/* Main Split Stage (Fits Remaining Height) */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        {/* Left 4 Cols: 3-Second Existential & Analytical Insight */}
        <div className="lg:col-span-4 glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-3">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              THE 3-SECOND VERDICT
            </div>
            <p className="text-xs sm:text-[13px] text-slate-700 dark:text-slate-200 leading-relaxed">
              Every 15-minute forecast of the last 12 months is aligned against
              measured reality in SQL. Day-ahead {variable} forecast misses most
              around{' '}
              <strong className="font-mono text-slate-900 dark:text-white">
                {hrs(worstH)} ({fmt(Math.round(daH[worstH]))} MW)
              </strong>{' '}
              and least around{' '}
              <strong className="font-mono text-slate-900 dark:text-white">
                {hrs(bestH)} ({fmt(Math.round(daH[bestH]))} MW)
              </strong>
              .
            </p>

            {b && (
              <div className="p-3 rounded-lg glass-well text-[11.5px] text-slate-600 dark:text-slate-300 leading-relaxed">
                <strong className="text-slate-900 dark:text-white block mb-0.5">
                  How the grid absorbs error (mFRR):
                </strong>
                Surprise = wind error minus consumption error. Fingrid&apos;s
                mFRR need tracks surprise (r ={' '}
                <span className="font-mono">
                  {fmt(b.r_surprise_vs_mfrr_need, 2)}
                </span>
                ), while intraday market trading absorbs most actual activation
                (r ={' '}
                <span className="font-mono">
                  {fmt(b.r_surprise_vs_net_mfrr, 2)}
                </span>
                ).
              </div>
            )}
          </div>

          <div className="pt-2.5 border-t border-slate-200/70 dark:border-white/10 flex items-center justify-between shrink-0">
            <button
              type="button"
              onClick={() => onSelectChapter('ranges')}
              className="inline-flex items-center gap-1 text-xs font-medium text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
            >
              <span>Tomorrow&apos;s 80%/95% ranges</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => onSelectChapter('model')}
              className="text-xs font-mono text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white cursor-pointer"
            >
              Public Weather →
            </button>
          </div>
        </div>

        {/* Right 8 Cols: Active Lens Stage */}
        <div className="lg:col-span-8 min-h-0 flex flex-col overflow-hidden">
          {lens === 'pulse' && (
            <div key="pulse" className="lens-enter h-full glass-card rounded-xl p-4 flex flex-col justify-between min-h-0 overflow-hidden">
              <div className="flex-none flex flex-wrap items-center justify-between gap-2 mb-1">
                <h3 className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                  Mean absolute forecast error by hour of day ({variable})
                </h3>
                <div className="flex items-center gap-4 text-xs text-slate-600 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--fc-da)' }}
                    />
                    <span>Day-ahead forecast</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--fc-id)' }}
                    />
                    <span>Intraday forecast</span>
                  </span>
                </div>
              </div>

              <div className="flex-1 min-h-0 overflow-hidden">
                <SvgLineChart
                  height={210}
                  directLabels={true}
                  yUnit="MAE (MW)"
                  ariaLabel="Mean absolute forecast error by hour"
                  referenceLines={
                    da?.mae_mw != null
                      ? [
                          {
                            y: da.mae_mw,
                            label: `DA mean ${fmt(Math.round(da.mae_mw))} MW`,
                            color: 'var(--fc-da)',
                            position: 'left',
                          },
                        ]
                      : []
                  }
                  series={[
                    { name: 'Day-ahead', values: daH, color: 'var(--fc-da)' },
                    { name: 'Intraday', values: idH, color: 'var(--fc-id)' },
                  ]}
                  labels={hours.map((h) => String(h).padStart(2, '0'))}
                  xTick={(i, l) => (i % 3 === 0 ? `${l}:00` : null)}
                  tipTitle={(l) => `${l}:00 Finnish time`}
                  tipValue={(x) => `${fmt(Math.round(x))} MW`}
                />
              </div>

              <div className="flex-none pt-1 text-[11px] text-slate-500 dark:text-slate-400 flex items-center justify-between">
                <span>
                  Hover or use Left/Right Arrow keys to scrub hourly error
                  profile.
                </span>
                <button
                  type="button"
                  onClick={() => setLens('matrix')}
                  className="font-mono text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
                >
                  Inspect 5 worst days &amp; mFRR table →
                </button>
              </div>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full glass-card rounded-xl p-4 overflow-auto thin-scroll grid grid-cols-1 xl:grid-cols-12 gap-4">
              <div className="xl:col-span-5 space-y-2">
                <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400">
                  Five worst day-ahead days ({variable})
                </h3>
                <div className="glass-well rounded-lg overflow-hidden">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                        <th className="py-2 px-2.5 text-left">Day</th>
                        <th className="py-2 px-2.5 text-right">Actual</th>
                        <th className="py-2 px-2.5 text-right">Forecast</th>
                        <th className="py-2 px-2.5 text-right">Miss</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                      {biggestMisses.map((r: any) => (
                        <tr key={r.day_fi}>
                          <td className="py-2 px-2.5 font-medium">
                            {dayFmt(`${r.day_fi}T12:00:00Z`)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono">
                            {fmt(Math.round(r.mean_actual_mw))}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono">
                            {fmt(Math.round(r.mean_forecast_mw))}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono font-semibold text-rose-600 dark:text-rose-400">
                            {fmt(Math.round(r.mae_mw))} MW
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="xl:col-span-7 space-y-2">
                <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400">
                  Grid reaction when forecast is wrong (mFRR Balancing)
                </h3>
                <div className="glass-well rounded-lg overflow-hidden">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                        <th className="py-2 px-2.5 text-left">Surprise</th>
                        <th className="py-2 px-2.5 text-right">Slots</th>
                        <th className="py-2 px-2.5 text-right">mFRR need</th>
                        <th className="py-2 px-2.5 text-right">Up / Down</th>
                        <th className="py-2 px-2.5 text-right">Price</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                      {(b?.bins || [])
                        .filter((r: any) => r.slots >= 20)
                        .map((r: any, idx: number) => (
                          <tr key={idx}>
                            <td className="py-2 px-2.5 font-medium">
                              {binLabel(r)}
                            </td>
                            <td className="py-2 px-2.5 text-right font-mono">
                              {fmt(r.slots)}
                            </td>
                            <td className="py-2 px-2.5 text-right font-mono">
                              {signed(r.mean_mfrr_need_mw)} MW
                            </td>
                            <td className="py-2 px-2.5 text-right font-mono">
                              +{fmt(Math.round(r.mean_mfrr_up_mw))} /{' '}
                              {signed(r.mean_mfrr_down_mw)}
                            </td>
                            <td className="py-2 px-2.5 text-right font-mono">
                              {r.median_imbalance_price == null
                                ? '–'
                                : `${fmt(r.median_imbalance_price, 1)} €`}
                            </td>
                          </tr>
                        ))}
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
                  label: 'Forecast Scorecard SQL',
                  filePath: 'sql/analysis/13_forecast_scorecard.sql',
                },
                {
                  label: 'mFRR Balancing SQL',
                  filePath: 'sql/analysis/17_forecast_error_vs_balancing.sql',
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
   CHAPTER: CONFORMAL FORECAST RANGES
   ───────────────────────────────────────────────────────── */
const METHOD_NAMES: Record<string, string> = {
  global: 'Global',
  by_hour: 'By hour',
  mondrian: 'Mondrian',
  adaptive: 'Adaptive (published)',
};

export const RangesView: React.FC<ViewProps> = ({ data, onSelectChapter }) => {
  const { ranges, sql, errors } = data;
  const [lens, setLens] = useState<LensMode>('pulse');
  const [syncIdx, setSyncIdx] = useState<number | null>(null);

  if (!ranges || !ranges.wind) {
    return (
      <div className="p-6 glass-card rounded-xl">
        <p className="text-sm text-rose-600 dark:text-rose-400">
          {errors.ranges || 'Loading forecast ranges...'}
        </p>
      </div>
    );
  }

  const when = dayWord(ranges.wind.target_day);
  const mw = (n: number) => `${fmt(Math.round(n))} MW`;
  const bt = ranges.wind.backtest;

  const gain = (v: 'wind' | 'consumption', lv: '0.8' | '0.95') => {
    const m = ranges[v].backtest.methods;
    return (
      100 * (1 - m.adaptive[lv].interval_score / m.global[lv].interval_score)
    );
  };

  const renderRecordChart = (rec: any[], color: string, label: string) => (
    <SvgLineChart
      height={110}
      forceZero={false}
      directLabels={false}
      yUnit="MW"
      ariaLabel={label}
      syncIndex={syncIdx}
      onIndexChange={setSyncIdx}
      series={[
        {
          name: 'Measured',
          short: 'Measured',
          values: rec.map((x: any) => x.actual_mw ?? NaN),
          color: 'var(--ink)',
          width: 1.4,
        },
      ]}
      bands={[
        {
          lo: rec.map((x: any) => x.lo80_mw),
          hi: rec.map((x: any) => x.hi80_mw),
          color,
          opacity: 0.3,
        },
      ]}
      labels={rec.map((x: any) => `${x.day_fi} ${hrs(x.hour_fi)}`)}
      xTick={(i, l) =>
        l.endsWith('12:00') && i % 48 < 24
          ? dayFmt(`${l.slice(0, 10)}T12:00:00Z`).replace(/ \d{4}$/, '')
          : null
      }
      tipTitle={(l) =>
        `${dayFmt(`${l.slice(0, 10)}T12:00:00Z`)} ${l.slice(11)} Finnish time`
      }
      tipValue={mw}
      tipExtra={(i) => [
        `80% range: ${mw(rec[i].lo80_mw)} – ${mw(rec[i].hi80_mw)}`,
        rec[i].actual_mw == null
          ? ''
          : rec[i].actual_mw >= rec[i].lo80_mw &&
            rec[i].actual_mw <= rec[i].hi80_mw
          ? 'Status: inside 80% range'
          : 'Status: outside 80% range',
      ]}
    />
  );

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      <div className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-emerald-600 dark:text-emerald-400">
            CONFORMAL PREDICTION &amp; COVERAGE BACKTEST
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            How far off can the forecast for {when.replace(/^on /, '')} be?
          </h1>
        </div>

        <LensBar
          lens={lens}
          setLens={setLens}
          matrixLabel="4-Method Backtest"
        />
      </div>

      {/* 4-KPI Strip */}
      <div className="flex-none grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-emerald-600 dark:text-emerald-400 leading-tight">
            ±{fmt(Math.round(ranges.wind.mean_width80_mw / 2))} MW
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            wind 80% range {when}
          </span>
        </div>
        <div className={`px-3.5 py-2 rounded-xl glass-kpi ${ranges.wind.record_coverage80 >= 0.78 ? 'telemetry-nominal' : 'telemetry-warning'}`}>
          <strong className="block text-lg sm:text-xl font-mono font-bold text-slate-900 dark:text-white leading-tight">
            {fmt(ranges.wind.record_coverage80 * 100, 0)}%
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            wind hours inside it (last {ranges.wind.record_days} days)
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-indigo">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-indigo-600 dark:text-indigo-400 leading-tight">
            ±{fmt(Math.round(ranges.consumption.mean_width80_mw / 2))} MW
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            consumption 80% range {when}
          </span>
        </div>
        <div className={`px-3.5 py-2 rounded-xl glass-kpi ${ranges.consumption.record_coverage80 >= 0.78 ? 'telemetry-nominal' : 'telemetry-warning'}`}>
          <strong className="block text-lg sm:text-xl font-mono font-bold text-slate-900 dark:text-white leading-tight">
            {fmt(ranges.consumption.record_coverage80 * 100, 0)}%
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            demand hours inside it (last {ranges.consumption.record_days} days)
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
              Grouping errors by time of day and forecast level, and letting the
              target miss rate adapt day by day, scores{' '}
              <strong className="font-mono text-emerald-600 dark:text-emerald-400">
                {fmt(gain('wind', '0.8'), 0)}–
                {fmt(
                  Math.max(
                    gain('wind', '0.95'),
                    gain('consumption', '0.8'),
                    gain('consumption', '0.95')
                  ),
                  0
                )}
                % better
              </strong>{' '}
              than one set of global quantiles.
            </p>
            <div className="p-3 rounded-lg glass-well text-[11.5px] text-slate-600 dark:text-slate-300 leading-relaxed">
              <strong className="text-slate-900 dark:text-white block mb-0.5">
                Method ({fmt(bt.days)} replayed days):
              </strong>
              {ranges.method}
            </div>
          </div>

          <div className="pt-2.5 border-t border-slate-200/70 dark:border-white/10 flex items-center justify-between shrink-0">
            <button
              type="button"
              onClick={() => onSelectChapter('model')}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
            >
              <span>Can public weather data beat Fingrid?</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="lg:col-span-8 min-h-0 flex flex-col overflow-hidden">
          {lens === 'pulse' && (
            <div key="pulse" className="lens-enter h-full glass-card rounded-xl p-3.5 flex flex-col justify-between min-h-0 overflow-hidden">
              <div className="flex-none flex flex-wrap items-center justify-between gap-2 mb-1">
                <h3 className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                  Did the 80% ranges hold? The last 14 days
                </h3>
                <span className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
                  Solid line = Measured · Shaded band = 80% range issued day
                  before
                </span>
              </div>

              <div className="flex-1 min-h-0 flex flex-col justify-between gap-1.5 overflow-hidden">
                <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                  <div className="flex-none text-[10.5px] font-mono text-emerald-600 dark:text-emerald-400">
                    Wind power (MW)
                  </div>
                  <div className="flex-1 min-h-0">
                    {renderRecordChart(
                      ranges.wind.record,
                      'var(--real)',
                      'Last 14 days: measured wind against the 80% range'
                    )}
                  </div>
                </div>
                <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                  <div className="flex-none text-[10.5px] font-mono text-indigo-600 dark:text-indigo-400">
                    Consumption (MW)
                  </div>
                  <div className="flex-1 min-h-0">
                    {renderRecordChart(
                      ranges.consumption.record,
                      'var(--cons)',
                      'Last 14 days: measured consumption against the 80% range'
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full glass-card rounded-xl p-4 flex flex-col justify-between overflow-auto thin-scroll">
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                  Backtest: every day replayed with only what was known then
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 mb-3">
                  {fmt(bt.days)} days replayed (
                  {dayFmt(`${bt.first_day}T12:00:00Z`)} –{' '}
                  {dayFmt(`${bt.last_day}T12:00:00Z`)}). Each cell: coverage %,
                  mean width, and Winkler interval score (lower is better).
                </p>

                <div className="glass-well rounded-lg overflow-hidden">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                        <th className="py-2.5 px-3 text-left">Method</th>
                        <th className="py-2.5 px-3 text-right">Wind 80%</th>
                        <th className="py-2.5 px-3 text-right">Wind 95%</th>
                        <th className="py-2.5 px-3 text-right">
                          Consumption 80%
                        </th>
                        <th className="py-2.5 px-3 text-right">
                          Consumption 95%
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                      {Object.keys(METHOD_NAMES).map((k) => (
                        <tr
                          key={k}
                          className={
                            k === 'adaptive'
                              ? 'telemetry-row-good'
                              : ''
                          }
                        >
                          <td className="py-2.5 px-3 font-medium">
                            {METHOD_NAMES[k]}
                          </td>
                          {(
                            [
                              ['wind', '0.8'],
                              ['wind', '0.95'],
                              ['consumption', '0.8'],
                              ['consumption', '0.95'],
                            ] as const
                          ).map(([v, lv]) => {
                            const c = ranges[v].backtest.methods[k][lv];
                            return (
                              <td
                                key={`${v}-${lv}`}
                                className="py-2.5 px-3 text-right font-mono"
                              >
                                <strong className="block text-slate-900 dark:text-white">
                                  {fmt(c.coverage * 100, 1)}%
                                </strong>
                                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                                  {fmt(Math.round(c.mean_width_mw))} MW ·{' '}
                                  {fmt(Math.round(c.interval_score))}
                                </span>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
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
                    label: 'Hourly Forecast Errors SQL',
                    filePath: 'sql/analysis/25_forecast_errors_hourly.sql',
                  },
                  {
                    label: 'Conformal Ranges Python',
                    filePath: 'src/forecast_ranges.py',
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
   CHAPTER: PUBLIC WEATHER MODEL VS. FINGRID
   ───────────────────────────────────────────────────────── */
const WM_NAMES: Record<string, string> = {
  fingrid: 'Fingrid day-ahead',
  weather: 'Public-weather model',
  weather_fingrid: 'Fingrid + learned correction',
};

const DAY_NAMES: Record<string, string> = {
  weekday: 'Ordinary weekday',
  weekend: 'Weekend',
  holiday: 'Public holiday',
  holiday_eve: 'Eve of a holiday',
  bridge_day: 'Bridge day',
  christmas_period: 'Christmas period (24 Dec – 6 Jan)',
  july: 'July (industry on holiday)',
};

export const WeatherModelView: React.FC<ViewProps> = ({ data }) => {
  const { weatherModel: d, leadTime: lead, sql, errors } = data;
  const [lens, setLens] = useState<LensMode>('pulse');
  const [syncIdx, setSyncIdx] = useState<number | null>(null);

  if (!d || !d.wind) {
    return (
      <div className="p-6 glass-card rounded-xl">
        <p className="text-sm text-rose-600 dark:text-rose-400">
          {errors.weatherModel || 'Loading public weather model comparison...'}
        </p>
      </div>
    );
  }

  const mw = (n: number) => `${fmt(Math.round(n))} MW`;
  const W = d.wind.backtest;
  const C = d.consumption.backtest;
  const worse = (b: any, k: string) =>
    `${fmt(Math.abs(b.skill_vs_fingrid[k]) * 100, 0)}% ${
      b.skill_vs_fingrid[k] < 0 ? 'worse' : 'better'
    }`;

  const pVal = (b: any, k: string) =>
    k === 'fingrid'
      ? 'reference'
      : b.diebold_mariano[k].p_value < 0.001
      ? 'p < 0.001'
      : `p = ${fmt(b.diebold_mariano[k].p_value, 2)}`;

  const corr = (k: 'wind' | 'consumption') =>
    d[k].backtest.diebold_mariano.weather_fingrid.p_value;
  const change = (k: 'wind' | 'consumption') =>
    `${fmt(
      Math.abs(d[k].backtest.skill_vs_fingrid.weather_fingrid) * 100,
      1
    )}% ${
      d[k].backtest.skill_vs_fingrid.weather_fingrid < 0 ? 'larger' : 'smaller'
    }`;
  const beaten = (['wind', 'consumption'] as const).some(
    (k) => corr(k) < 0.05 && d[k].backtest.skill_vs_fingrid.weather_fingrid > 0
  );

  const render14DayChart = (rec: any[], label: string) => (
    <SvgLineChart
      height={110}
      forceZero={false}
      directLabels={false}
      yUnit="MW"
      ariaLabel={label}
      syncIndex={syncIdx}
      onIndexChange={setSyncIdx}
      series={[
        {
          name: 'Measured',
          short: 'Measured',
          values: rec.map((x: any) => x.actual_mw ?? NaN),
          color: 'var(--ink)',
          width: 1.4,
        },
        {
          name: 'Fingrid',
          short: 'Fingrid',
          values: rec.map((x: any) => x.fingrid_mw ?? NaN),
          color: 'var(--fc-da)',
          width: 1.4,
        },
        {
          name: 'Public weather',
          short: 'Public',
          values: rec.map((x: any) => x.weather_mw ?? NaN),
          color: 'var(--wm)',
          width: 1.4,
          dash: '4 3',
        },
      ]}
      labels={rec.map((x: any) => `${x.day_fi} ${hrs(x.hour_fi)}`)}
      xTick={(i, l) =>
        l.endsWith('12:00') && i % 48 < 24
          ? dayFmt(`${l.slice(0, 10)}T12:00:00Z`).replace(/ \d{4}$/, '')
          : null
      }
      tipTitle={(l) =>
        `${dayFmt(`${l.slice(0, 10)}T12:00:00Z`)} ${l.slice(11)} Finnish time`
      }
      tipValue={mw}
    />
  );

  const lw = lead?.variables?.wind;
  const lc = lead?.variables?.consumption;

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      <div className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-orange-600 dark:text-orange-400">
            OPEN-METEO BENCHMARK &amp; FORECAST LEAD TIME
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Can public data beat Fingrid&apos;s forecast?
          </h1>
        </div>

        <LensBar
          lens={lens}
          setLens={setLens}
          matrixLabel="Backtest, Lead Time & Holidays"
        />
      </div>

      {/* 4 KPIs */}
      <div className="flex-none grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-sky-600 dark:text-sky-400 leading-tight">
            {mw(W.mae_mw.fingrid)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Fingrid&apos;s wind error
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-orange-600 dark:text-orange-400 leading-tight">
            {mw(W.mae_mw.weather)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            public-weather wind error ({worse(W, 'weather')})
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-sky-600 dark:text-sky-400 leading-tight">
            {mw(C.mae_mw.fingrid)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Fingrid&apos;s consumption error
          </span>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
          <strong className="block text-lg sm:text-xl font-mono font-bold text-orange-600 dark:text-orange-400 leading-tight">
            {mw(C.mae_mw.weather)}
          </strong>
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 truncate">
            public-weather demand error ({worse(C, 'weather')})
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
              <strong className="text-slate-900 dark:text-white">
                {beaten ? 'Partly.' : 'No.'}
              </strong>{' '}
              Used to correct Fingrid&apos;s forecast, a ridge model on public
              Open-Meteo weather and the Finnish calendar leaves the error{' '}
              {change('wind')} for wind (p = {fmt(corr('wind'), 2)}) and{' '}
              {change('consumption')} for consumption (p ={' '}
              {fmt(corr('consumption'), 2)}).
            </p>
            {lw && lc && (
              <div className="p-3 rounded-lg glass-well text-[11.5px] text-slate-600 dark:text-slate-300 leading-relaxed">
                <strong className="text-slate-900 dark:text-white block mb-0.5">
                  Why public weather loses:
                </strong>
                For wind, fresher weather closes{' '}
                {fmt(
                  Math.min(
                    (lw.leads[0].mae_mw -
                      lw.leads[lw.leads.length - 1].mae_mw) /
                      (lw.leads[0].mae_mw - lw.fingrid_mae_mw),
                    1
                  ) * 100,
                  0
                )}
                % of the gap to Fingrid. For consumption, fresher weather does
                not help ({mw(lc.leads[0].mae_mw)} →{' '}
                {mw(lc.leads[lc.leads.length - 1].mae_mw)}): Fingrid knows
                industrial schedules beyond weather.
              </div>
            )}
          </div>

          <p className="text-[10.5px] text-slate-500 dark:text-slate-400 pt-2.5 border-t border-slate-200/70 dark:border-white/10 shrink-0">
            Weather data: Open-Meteo (CC BY 4.0) · Power data: Fingrid Open
            Data.
          </p>
        </div>

        <div className="lg:col-span-8 min-h-0 flex flex-col overflow-hidden">
          {lens === 'pulse' && (
            <div key="pulse" className="lens-enter h-full glass-card rounded-xl p-3.5 flex flex-col justify-between min-h-0 overflow-hidden">
              <div className="flex-none flex flex-wrap items-center justify-between gap-2 mb-1">
                <h3 className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                  The last 14 days (Measured vs. Fingrid vs. Public-weather
                  model)
                </h3>
                <div className="flex items-center gap-3 text-[11px] text-slate-600 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--ink)' }}
                    />
                    <span>Measured</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--fc-da)' }}
                    />
                    <span>Fingrid</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i
                      className="w-3 h-0.5 inline-block"
                      style={{ backgroundColor: 'var(--wm)' }}
                    />
                    <span>Public weather (dashed)</span>
                  </span>
                </div>
              </div>

              <div className="flex-1 min-h-0 flex flex-col justify-between gap-1.5 overflow-hidden">
                <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                  <div className="flex-none text-[10.5px] font-mono text-slate-500 dark:text-slate-400">
                    Wind power (MW)
                  </div>
                  <div className="flex-1 min-h-0">
                    {render14DayChart(
                      d.wind.record,
                      "Last 14 days: measured wind, Fingrid's forecast and the public-weather model"
                    )}
                  </div>
                </div>
                <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                  <div className="flex-none text-[10.5px] font-mono text-slate-500 dark:text-slate-400">
                    Consumption (MW)
                  </div>
                  <div className="flex-1 min-h-0">
                    {render14DayChart(
                      d.consumption.record,
                      "Last 14 days: measured consumption, Fingrid's forecast and the public-weather model"
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full glass-card rounded-xl p-4 overflow-auto thin-scroll grid grid-cols-1 xl:grid-cols-12 gap-4">
              <div className="xl:col-span-6 space-y-3">
                <div>
                  <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400 mb-1.5">
                    Diebold-Mariano Backtest ({fmt(W.days)} days)
                  </h3>
                  <div className="glass-well rounded-lg overflow-hidden">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                          <th className="py-2 px-2.5 text-left">Forecast</th>
                          <th className="py-2 px-2.5 text-right">Wind MAE</th>
                          <th className="py-2 px-2.5 text-right">Demand MAE</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                        {Object.keys(WM_NAMES).map((k) => (
                          <tr key={k}>
                            <td className="py-2 px-2.5 font-medium">
                              {WM_NAMES[k]}
                            </td>
                            {[W, C].map((b, idx) => (
                              <td
                                key={idx}
                                className="py-2 px-2.5 text-right font-mono"
                              >
                                <strong className="block text-slate-900 dark:text-white">
                                  {mw(b.mae_mw[k])}
                                </strong>
                                <span className="text-[10.5px] text-slate-500">
                                  {pVal(b, k)}
                                </span>
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {lw && lc && (
                  <div>
                    <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400 mb-1.5">
                      Weather Forecast Lead-Time Decay
                    </h3>
                    <div className="glass-well rounded-lg overflow-hidden">
                      <table className="w-full text-xs border-collapse">
                        <thead>
                          <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                            <th className="py-2 px-2.5 text-left">
                              Forecast age
                            </th>
                            <th className="py-2 px-2.5 text-right">
                              Wind error
                            </th>
                            <th className="py-2 px-2.5 text-right">
                              Demand error
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                          {lw.leads.map((x: any, i: number) => (
                            <tr key={x.lead}>
                              <td className="py-2 px-2.5 font-medium">
                                {x.lead === 'newest'
                                  ? 'Newest (hindsight)'
                                  : `${x.lead.replace(
                                      ' (published)',
                                      ''
                                    )} before`}
                              </td>
                              <td className="py-2 px-2.5 text-right font-mono">
                                {mw(x.mae_mw)}
                              </td>
                              <td className="py-2 px-2.5 text-right font-mono">
                                {mw(lc.leads[i].mae_mw)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>

              <div className="xl:col-span-6 space-y-2">
                <h3 className="text-xs font-mono uppercase text-slate-500 dark:text-slate-400">
                  Does Fingrid miss more on holidays?
                </h3>
                <div className="glass-well rounded-lg overflow-hidden">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100/80 dark:bg-[#12192a] text-slate-500 dark:text-slate-400 font-mono">
                        <th className="py-2 px-2.5 text-left">Kind of day</th>
                        <th className="py-2 px-2.5 text-right">Days</th>
                        <th className="py-2 px-2.5 text-right">Demand MAE</th>
                        <th className="py-2 px-2.5 text-right">Bias</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/70 dark:divide-white/10">
                      {(d.fingrid_by_day_type || []).map((r: any) => (
                        <tr key={r.kind}>
                          <td className="py-2 px-2.5 font-medium">
                            {DAY_NAMES[r.kind] || r.kind}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono">
                            {fmt(r.days)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono">
                            {mw(r.mae_mw)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono">
                            {r.bias_mw > 0 ? '+' : r.bias_mw < 0 ? '−' : ''}
                            {mw(Math.abs(r.bias_mw))}
                          </td>
                        </tr>
                      ))}
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
                    label: 'Weather Model Panel SQL',
                    filePath: 'sql/analysis/26_weather_model_panel.sql',
                  },
                  {
                    label: 'Weather Model Python',
                    filePath: 'src/weather_model.py',
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
