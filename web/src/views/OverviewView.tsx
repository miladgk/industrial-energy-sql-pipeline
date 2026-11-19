import React, { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import {
  ObservatoryData,
  fmt,
  dayFmt,
  dayWord,
  hrs,
  hourSpan,
} from '../dataLoader';
import { SvgLineChart } from '../components/SvgLineChart';
import { AllocationBars } from '../components/AllocationBars';

export type ChapterId =
  | 'overview'
  | 'forecasts'
  | 'ranges'
  | 'model'
  | 'co2'
  | 'events'
  | 'cold'
  | 'strikes'
  | 'wind'
  | 'price'
  | 'europe'
  | 'ev'
  | 'craft';

interface OverviewViewProps {
  data: ObservatoryData;
  onSelectChapter: (ch: ChapterId) => void;
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

export const OverviewView: React.FC<OverviewViewProps> = ({
  data,
  onSelectChapter,
}) => {
  const {
    recent,
    scorecard,
    co2,
    events,
    temperature,
    windAlloc,
    ranges,
    engineering,
  } = data;

  const [heroMode, setHeroMode] = useState<'ranges' | 'grid'>('ranges');
  const [heroSyncIdx, setHeroSyncIdx] = useState<number | null>(null);
  const activeHeroMode = heroMode === 'ranges' && !ranges ? 'grid' : heroMode;

  const mw = (n: number) => `${fmt(Math.round(n))} MW`;

  // Proof bar numbers
  const totalRows = engineering?.partitioning?.total_rows;
  const datasetCount = engineering?.datasets ?? '–';
  const windDa = scorecard?.summary?.find(
    (r: any) => r.variable === 'wind' && r.product === 'day_ahead'
  );
  const co2Saving = co2?.backtest?.saving_pct;
  const totalEvents = events?.counts
    ? (Object.values(events.counts) as any[]).reduce(
        (acc: number, c: any) => acc + (c.year || 0),
        0
      )
    : null;

  // CO2 summary
  const co2When = co2?.target_day ? dayWord(co2.target_day) : 'tomorrow';
  const co2Hours = co2?.hours || [];
  const co2CleanIdx = co2?.cleanest_hour
    ? co2Hours.findIndex(
        (x: any) => x.hour_start === co2.cleanest_hour.hour_start
      )
    : -1;
  const co2DirtyIdx = co2?.dirtiest_hour
    ? co2Hours.findIndex(
        (x: any) => x.hour_start === co2.dirtiest_hour.hour_start
      )
    : -1;

  // Events summary
  const freqYear = events?.counts
    ? (events.counts.frequency_low?.year || 0) +
      (events.counts.frequency_high?.year || 0)
    : null;
  const freqMinutes = events?.frequency_by_minute || [];
  const freqMean =
    freqMinutes.length > 0
      ? freqMinutes.reduce(
          (a: number, m: any) => a + Number(m.pct_outside || 0),
          0
        ) / freqMinutes.length
      : null;
  const worstMin =
    freqMinutes.length > 0
      ? freqMinutes.reduce(
          (a: any, m: any) => (m.pct_outside > a.pct_outside ? m : a),
          freqMinutes[0]
        )
      : null;

  // Cold summary
  const wdFit = temperature?.fits?.find((f: any) => f.day_type === 'weekday');
  const tempBins = temperature?.bins || [];
  const freezeBinIdx = tempBins.findIndex((b: any) => b.from_c <= 0 && b.to_c > 0);
  const heatBinIdx = wdFit
    ? tempBins.findIndex(
        (b: any) =>
          b.from_c <= wdFit.balance_point_c && b.to_c > wdFit.balance_point_c
      )
    : -1;
  const tempModel =
    wdFit && tempBins.length
      ? tempBins.map(
          (b: any) =>
            wdFit.base_mw +
            wdFit.mw_per_degree *
              Math.max(wdFit.balance_point_c - (b.from_c + b.to_c) / 2, 0)
        )
      : [];

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      {/* 3-SECOND EXISTENTIAL THESIS & MONUMENTAL PROOF RIBBON */}
      <section className="flex-none glass-card rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-[240px] flex-1">
          <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
            <span>FINLAND NATIONAL GRID</span>
            <span aria-hidden="true">·</span>
            <span>{datasetCount} LIVE SQL STREAMS</span>
          </div>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight">
              Finland&apos;s electricity grid, read in SQL.
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate hidden xl:inline">
              Human certainty vs. Arctic nature: scoring forecast error, finding
              tomorrow&apos;s cleanest hours, and logging 50 Hz shocks.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-5 shrink-0">
          <div className="border-l border-slate-200 dark:border-white/15 pl-3">
            <strong className="block text-base sm:text-lg font-mono font-bold text-slate-900 dark:text-white leading-none" id="proof-rows">
              {totalRows != null ? fmt(totalRows) : '–'}
            </strong>
            <span className="text-[10.5px] text-slate-500 dark:text-slate-400">
              data rows stored
            </span>
          </div>
          <div className="border-l border-slate-200 dark:border-white/15 pl-3">
            <strong className="block text-base sm:text-lg font-mono font-bold text-sky-600 dark:text-sky-400 leading-none" id="proof-wind">
              {windDa ? `${fmt(Math.round(windDa.mae_mw))} MW` : '–'}
            </strong>
            <span className="text-[10.5px] text-slate-500 dark:text-slate-400">
              avg wind forecast miss
            </span>
          </div>
          <div className="border-l border-slate-200 dark:border-white/15 pl-3">
            <strong className="block text-base sm:text-lg font-mono font-bold text-emerald-600 dark:text-emerald-400 leading-none" id="proof-co2">
              {co2Saving != null ? `${fmt(co2Saving, 1)}%` : '–'}
            </strong>
            <span className="text-[10.5px] text-slate-500 dark:text-slate-400">
              less CO₂ in picked hour
            </span>
          </div>
          <div className="border-l border-slate-200 dark:border-white/15 pl-3">
            <strong className="block text-base sm:text-lg font-mono font-bold text-amber-600 dark:text-amber-400 leading-none" id="proof-events">
              {totalEvents != null ? fmt(totalEvents) : '–'}
            </strong>
            <span className="text-[10.5px] text-slate-500 dark:text-slate-400">
              unusual grid events
            </span>
          </div>
        </div>
      </section>

      {/* ZERO-SCROLL SPATIAL BENTO GRID (FITS REMAINING 100vh) */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 lg:grid-rows-2 gap-2.5">
        {/* FOCAL HERO CHAMBER (LEFT 5 COLS, 2 ROWS FULL HEIGHT) */}
        <article className="lg:col-span-5 lg:row-span-2 glass-card rounded-xl p-3.5 flex flex-col justify-between gap-2 min-h-0 overflow-hidden">
          <div className="flex-none">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Forecasts &amp; Uncertainty
                </div>
                <h2 className="text-base font-bold text-slate-900 dark:text-white truncate">
                  {activeHeroMode === 'ranges' && ranges?.wind
                    ? `Wind & consumption ${dayWord(ranges.wind.target_day)}.`
                    : 'Wind & consumption, past year.'}
                </h2>
              </div>

              <div
                className="inline-flex items-center gap-0.5 p-0.5 glass-well rounded-lg shrink-0"
                role="group"
                aria-label="Hero chart view"
              >
                <button
                  type="button"
                  onClick={() => {
                    setHeroMode('ranges');
                    setHeroSyncIdx(null);
                  }}
                  className={`px-2.5 py-0.5 text-[11px] font-mono rounded-md transition-all whitespace-nowrap cursor-pointer ${
                    activeHeroMode === 'ranges'
                      ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  Tomorrow
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setHeroMode('grid');
                    setHeroSyncIdx(null);
                  }}
                  className={`px-2.5 py-0.5 text-[11px] font-mono rounded-md transition-all whitespace-nowrap cursor-pointer ${
                    activeHeroMode === 'grid'
                      ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  Past year
                </button>
              </div>
            </div>

            {/* Dual KPI Compact Readout */}
            {activeHeroMode === 'ranges' && ranges?.wind ? (
              <div className="grid grid-cols-2 gap-2 mt-2 px-2.5 py-1.5 rounded-lg glass-well">
                <div className="min-w-0">
                  <strong className="block text-sm font-mono font-bold text-emerald-600 dark:text-emerald-400 leading-tight">
                    ±{fmt(Math.round(ranges.wind.mean_width80_mw / 2))} MW
                  </strong>
                  <span className="block text-[10.5px] text-slate-500 dark:text-slate-400 truncate">
                    wind uncertainty (80% band)
                  </span>
                </div>
                <div className="min-w-0">
                  <strong className="block text-sm font-mono font-bold text-indigo-600 dark:text-indigo-400 leading-tight">
                    ±{fmt(Math.round(ranges.consumption.mean_width80_mw / 2))} MW
                  </strong>
                  <span className="block text-[10.5px] text-slate-500 dark:text-slate-400 truncate">
                    demand uncertainty (80% band)
                  </span>
                </div>
              </div>
            ) : recent?.summary ? (
              <div className="grid grid-cols-2 gap-2 mt-2 px-2.5 py-1.5 rounded-lg glass-well">
                <div className="min-w-0">
                  <strong className="block text-sm font-mono font-bold text-emerald-600 dark:text-emerald-400 leading-tight">
                    {fmt(recent.summary.wind_mean_mw)} MW
                  </strong>
                  <span className="block text-[10.5px] text-slate-500 dark:text-slate-400 truncate">
                    avg wind production
                  </span>
                </div>
                <div className="min-w-0">
                  <strong className="block text-sm font-mono font-bold text-indigo-600 dark:text-indigo-400 leading-tight">
                    {recent.summary.wind_share_pct}%
                  </strong>
                  <span className="block text-[10.5px] text-slate-500 dark:text-slate-400 truncate">
                    wind share of demand
                  </span>
                </div>
              </div>
            ) : null}
          </div>

          {/* Chart Canvas — Flex-constrained so it never overlaps */}
          <div
            key={activeHeroMode}
            className="lens-enter flex-1 min-h-0 flex flex-col justify-between gap-1.5 overflow-hidden"
          >
            {activeHeroMode === 'ranges' && ranges?.wind ? (
              <>
                <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                  <div className="flex-none text-[10px] font-mono uppercase text-slate-500 dark:text-slate-400 mb-0.5">
                    Wind power · 80% &amp; 95% conformal bands
                  </div>
                  <div className="flex-1 min-h-0">
                    <SvgLineChart
                      height={145}
                      forceZero={true}
                      yUnit="MW"
                      ariaLabel="Tomorrow's wind forecast with 80% and 95% ranges"
                      syncIndex={heroSyncIdx}
                      onIndexChange={setHeroSyncIdx}
                      series={[
                        {
                          name: 'Fingrid forecast',
                          short: 'Forecast',
                          values: ranges.wind.hours.map((h: any) => h.forecast_mw),
                          color: 'var(--real)',
                          width: 2,
                        },
                      ]}
                      bands={[
                        {
                          lo: ranges.wind.hours.map((h: any) => h.lo95_mw),
                          hi: ranges.wind.hours.map((h: any) => h.hi95_mw),
                          color: 'var(--real)',
                          opacity: 0.14,
                        },
                        {
                          lo: ranges.wind.hours.map((h: any) => h.lo80_mw),
                          hi: ranges.wind.hours.map((h: any) => h.hi80_mw),
                          color: 'var(--real)',
                          opacity: 0.28,
                        },
                      ]}
                      labels={ranges.wind.hours.map((h: any) => hrs(h.hour_fi))}
                      xTick={(i, l) => (i % 6 === 0 ? l : null)}
                      tipTitle={(l) => `${l} Finnish time`}
                      tipValue={mw}
                      tipExtra={(i) => [
                        `80%: ${mw(ranges.wind.hours[i].lo80_mw)} – ${mw(
                          ranges.wind.hours[i].hi80_mw
                        )}`,
                        `95%: ${mw(ranges.wind.hours[i].lo95_mw)} – ${mw(
                          ranges.wind.hours[i].hi95_mw
                        )}`,
                      ]}
                    />
                  </div>
                </div>

                <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                  <div className="flex-none text-[10px] font-mono uppercase text-slate-500 dark:text-slate-400 mb-0.5">
                    Consumption · 80% &amp; 95% conformal bands
                  </div>
                  <div className="flex-1 min-h-0">
                    <SvgLineChart
                      height={145}
                      forceZero={false}
                      yUnit="MW"
                      ariaLabel="Tomorrow's consumption forecast with 80% and 95% ranges"
                      syncIndex={heroSyncIdx}
                      onIndexChange={setHeroSyncIdx}
                      series={[
                        {
                          name: 'Fingrid forecast',
                          short: 'Forecast',
                          values: ranges.consumption.hours.map(
                            (h: any) => h.forecast_mw
                          ),
                          color: 'var(--cons)',
                          width: 2,
                        },
                      ]}
                      bands={[
                        {
                          lo: ranges.consumption.hours.map((h: any) => h.lo95_mw),
                          hi: ranges.consumption.hours.map((h: any) => h.hi95_mw),
                          color: 'var(--cons)',
                          opacity: 0.14,
                        },
                        {
                          lo: ranges.consumption.hours.map((h: any) => h.lo80_mw),
                          hi: ranges.consumption.hours.map((h: any) => h.hi80_mw),
                          color: 'var(--cons)',
                          opacity: 0.28,
                        },
                      ]}
                      labels={ranges.consumption.hours.map((h: any) =>
                        hrs(h.hour_fi)
                      )}
                      xTick={(i, l) => (i % 6 === 0 ? l : null)}
                      tipTitle={(l) => `${l} Finnish time`}
                      tipValue={mw}
                      tipExtra={(i) => [
                        `80%: ${mw(ranges.consumption.hours[i].lo80_mw)} – ${mw(
                          ranges.consumption.hours[i].hi80_mw
                        )}`,
                        `95%: ${mw(ranges.consumption.hours[i].lo95_mw)} – ${mw(
                          ranges.consumption.hours[i].hi95_mw
                        )}`,
                      ]}
                    />
                  </div>
                </div>
              </>
            ) : recent?.days ? (
              <div className="flex-1 min-h-0">
                <SvgLineChart
                  height={280}
                  directLabels={true}
                  yUnit="MW"
                  ariaLabel="Daily wind and consumption, last 12 months"
                  series={[
                    {
                      name: 'Consumption',
                      short: 'Demand',
                      values: recent.days.map((d: any) => d.consumption_mw),
                      color: 'var(--cons)',
                      width: 1.7,
                    },
                    {
                      name: 'Wind',
                      short: 'Wind',
                      values: recent.days.map((d: any) => d.wind_mw),
                      color: 'var(--real)',
                      width: 2,
                    },
                  ]}
                  labels={recent.days.map((d: any) => d.day)}
                  xTick={(_i, l, narrow) =>
                    l.slice(8) === '01' &&
                    (!narrow || (+l.slice(5, 7) - 1) % 2 === 0)
                      ? MONTHS[+l.slice(5, 7) - 1]
                      : null
                  }
                  tipTitle={(l) => dayFmt(`${l}T00:00:00Z`)}
                  tipValue={(v) => `${fmt(Math.round(v))} MW`}
                />
              </div>
            ) : null}
          </div>

          <div className="flex-none pt-2 border-t border-slate-200/70 dark:border-white/10 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() =>
                onSelectChapter(
                  activeHeroMode === 'ranges' ? 'ranges' : 'forecasts'
                )
              }
              className="inline-flex items-center gap-1 text-xs font-medium text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
            >
              <span>
                {activeHeroMode === 'ranges'
                  ? 'Did the ranges hold? Backtest'
                  : 'Forecast scorecard & balancing'}
              </span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => onSelectChapter('model')}
              className="text-xs font-mono text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white cursor-pointer"
            >
              Public weather vs Fingrid →
            </button>
          </div>
        </article>

        {/* CHAMBER 2 (TOP MIDDLE, 3 COLS): CLEANEST HOURS TOMORROW */}
        <article className="lg:col-span-3 lg:row-span-1 glass-card rounded-xl p-3.5 flex flex-col justify-between gap-1.5 min-h-0 overflow-hidden">
          <div className="flex-none">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  CO₂ Intensity
                </div>
                <h2 className="text-sm sm:text-base font-bold text-slate-900 dark:text-white truncate">
                  Cleanest hours {co2When}.
                </h2>
              </div>
              <button
                type="button"
                onClick={() => onSelectChapter('co2')}
                className="text-xs font-mono text-sky-600 dark:text-sky-400 hover:underline inline-flex items-center gap-0.5 shrink-0 cursor-pointer"
              >
                <span>Model</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2 mt-1.5 px-2.5 py-1 rounded-lg glass-well">
              <div className="min-w-0">
                <strong className="block text-xs sm:text-sm font-mono font-bold text-emerald-600 dark:text-emerald-400 leading-tight truncate">
                  {co2?.best_3h ? hourSpan(co2.best_3h.hour_fi, 3) : '–'}
                </strong>
                <span className="block text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  cleanest 3h window
                </span>
              </div>
              <div className="min-w-0">
                <strong className="block text-xs sm:text-sm font-mono font-bold text-slate-900 dark:text-white leading-tight truncate">
                  {co2?.cleanest_hour
                    ? `${fmt(co2.cleanest_hour.co2, 1)} g/kWh`
                    : '–'}
                </strong>
                <span className="block text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  lowest CO₂ intensity
                </span>
              </div>
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {co2Hours.length > 0 && (
              <SvgLineChart
                height={125}
                yUnit="g CO₂/kWh"
                ariaLabel="Forecast CO2 intensity by hour"
                referenceLines={
                  co2?.day_mean_forecast != null
                    ? [
                        {
                          y: co2.day_mean_forecast,
                          label: `mean ${fmt(co2.day_mean_forecast, 0)}g`,
                          color: 'var(--syn)',
                          position: 'right',
                        },
                      ]
                    : []
                }
                series={[
                  {
                    name: 'CO₂ Forecast',
                    values: co2Hours.map((x: any) => x.co2_forecast),
                    color: 'var(--fc-da)',
                    width: 2,
                  },
                ]}
                labels={co2Hours.map((x: any) => hrs(x.hour_fi))}
                points={[
                  ...(co2CleanIdx >= 0
                    ? [
                        {
                          i: co2CleanIdx,
                          v: co2.cleanest_hour.co2,
                          color: 'var(--real)',
                          label: `clean ${hrs(co2.cleanest_hour.hour_fi)}`,
                          dy: 12,
                        },
                      ]
                    : []),
                  ...(co2DirtyIdx >= 0
                    ? [
                        {
                          i: co2DirtyIdx,
                          v: co2.dirtiest_hour.co2,
                          color: 'var(--fault)',
                          label: `peak ${hrs(co2.dirtiest_hour.hour_fi)}`,
                          dy: -6,
                        },
                      ]
                    : []),
                ]}
                xTick={(i, l) => (i % 6 === 0 ? l : null)}
                tipTitle={(l) => `${l} Finnish time`}
                tipValue={(v) => `${fmt(v, 1)} gCO₂/kWh`}
              />
            )}
          </div>
        </article>

        {/* CHAMBER 3 (TOP RIGHT, 4 COLS): GRID FREQUENCY EXCURSIONS */}
        <article className="lg:col-span-4 lg:row-span-1 glass-card rounded-xl p-3.5 flex flex-col justify-between gap-1.5 min-h-0 overflow-hidden">
          <div className="flex-none">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Grid Frequency (Target 50 Hz)
                </div>
                <h2 className="text-sm sm:text-base font-bold text-slate-900 dark:text-white truncate">
                  Off-target frequency by minute.
                </h2>
              </div>
              <button
                type="button"
                onClick={() => onSelectChapter('events')}
                className="text-xs font-mono text-sky-600 dark:text-sky-400 hover:underline inline-flex items-center gap-0.5 shrink-0 cursor-pointer"
              >
                <span>Event log</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2 mt-1.5 px-2.5 py-1 rounded-lg glass-well">
              <div className="min-w-0">
                <strong className="block text-xs sm:text-sm font-mono font-bold text-amber-600 dark:text-amber-400 leading-tight truncate">
                  {freqYear != null ? fmt(freqYear) : '–'}
                </strong>
                <span className="block text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  outside 49.9–50.1 Hz (1y)
                </span>
              </div>
              <div className="min-w-0">
                <strong className="block text-xs sm:text-sm font-mono font-bold text-rose-600 dark:text-rose-400 leading-tight truncate">
                  {worstMin
                    ? `:${String(worstMin.minute_of_hour).padStart(
                        2,
                        '0'
                      )} (${fmt(worstMin.pct_outside, 1)}%)`
                    : '–'}
                </strong>
                <span className="block text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  worst minute of hour
                </span>
              </div>
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {freqMinutes.length > 0 && (
              <SvgLineChart
                height={125}
                yUnit="% outside 49.9–50.1 Hz"
                ariaLabel="Frequency excursions by minute of the hour"
                referenceLines={
                  freqMean != null
                    ? [
                        {
                          y: freqMean,
                          label: `avg ${fmt(freqMean, 2)}%`,
                          color: 'var(--syn)',
                          position: 'right',
                        },
                      ]
                    : []
                }
                series={[
                  {
                    name: 'Outside 49.9–50.1 Hz',
                    values: freqMinutes.map((m: any) => m.pct_outside),
                    color: 'var(--fc-da)',
                    width: 2,
                  },
                ]}
                labels={freqMinutes.map(
                  (m: any) => `:${String(m.minute_of_hour).padStart(2, '0')}`
                )}
                points={
                  worstMin
                    ? [
                        {
                          i: freqMinutes.indexOf(worstMin),
                          v: worstMin.pct_outside,
                          color: 'var(--fault)',
                          label: `:${worstMin.minute_of_hour}`,
                          dy: -6,
                        },
                      ]
                    : []
                }
                xTick={(i, l) => (i % 15 === 0 ? l : null)}
                tipTitle={(l) => `Minute ${l} of the hour`}
                tipValue={(v) => `${fmt(v, 2)}% outside band`}
              />
            )}
          </div>
        </article>

        {/* CHAMBER 4 (BOTTOM MIDDLE, 3 COLS): THERMODYNAMICS OF COLD */}
        <article className="lg:col-span-3 lg:row-span-1 glass-card rounded-xl p-3.5 flex flex-col justify-between gap-1.5 min-h-0 overflow-hidden">
          <div className="flex-none">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Weather &amp; Demand
                </div>
                <h2 className="text-sm sm:text-base font-bold text-slate-900 dark:text-white truncate">
                  Extra demand per °C colder.
                </h2>
              </div>
              <button
                type="button"
                onClick={() => onSelectChapter('cold')}
                className="text-xs font-mono text-sky-600 dark:text-sky-400 hover:underline inline-flex items-center gap-0.5 shrink-0 cursor-pointer"
              >
                <span>Model</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2 mt-1.5 px-2.5 py-1 rounded-lg glass-well">
              <div className="min-w-0">
                <strong className="block text-xs sm:text-sm font-mono font-bold text-sky-600 dark:text-sky-400 leading-tight truncate">
                  {wdFit ? `+${fmt(Math.round(wdFit.mw_per_degree))} MW` : '–'}
                </strong>
                <span className="block text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  per °C colder (weekdays)
                </span>
              </div>
              <div className="min-w-0">
                <strong className="block text-xs sm:text-sm font-mono font-bold text-slate-900 dark:text-white leading-tight truncate">
                  {wdFit ? `${fmt(wdFit.r2 * 100, 0)}%` : '–'}
                </strong>
                <span className="block text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  explained by temperature
                </span>
              </div>
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {tempBins.length > 0 && (
              <SvgLineChart
                height={125}
                forceZero={false}
                yUnit="MW avg"
                ariaLabel="Consumption against temperature"
                vLines={[
                  ...(freezeBinIdx >= 0
                    ? [{ i: freezeBinIdx, label: '0°C', color: 'var(--rec)', dash: '3 3' }]
                    : []),
                  ...(heatBinIdx >= 0 && wdFit
                    ? [
                        {
                          i: heatBinIdx,
                          label: `${wdFit.balance_point_c}°C`,
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
                    values: tempBins.map((b: any) => b.weekday_mw ?? NaN),
                    color: 'var(--fc-da)',
                    width: 2,
                    dots: true,
                  },
                  {
                    name: 'Weekends',
                    short: 'Weekend',
                    values: tempBins.map((b: any) => b.weekend_mw ?? NaN),
                    color: 'var(--fc-id)',
                    width: 1.5,
                  },
                  {
                    name: 'Model',
                    short: 'Fit',
                    values: tempModel,
                    color: 'var(--ink-2)',
                    width: 1.2,
                    dash: '4 3',
                  },
                ]}
                labels={tempBins.map((b: any) => `${b.from_c}`)}
                xTick={(i, l) =>
                  i % 3 === 0 ? `${(+l < 0 ? '−' : '') + Math.abs(+l)} °C` : null
                }
                tipTitle={(l) => `${l}°C band`}
                tipValue={(v) => `${fmt(Math.round(v))} MW`}
              />
            )}
          </div>
        </article>

        {/* CHAMBER 5 (BOTTOM RIGHT, 4 COLS): WHERE EXTRA WIND GOES + WAREHOUSE SPEED */}
        <article className="lg:col-span-4 lg:row-span-1 glass-card rounded-xl p-3.5 flex flex-col justify-between gap-1 min-h-0 overflow-hidden">
          <div className="flex-none flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Power Balance &amp; Warehouse Craft
              </div>
              <h2 className="text-sm sm:text-base font-bold text-slate-900 dark:text-white truncate">
                Where +1 MW of wind goes.
              </h2>
            </div>

            <div className="flex items-center gap-2.5 shrink-0">
              <button
                type="button"
                onClick={() => onSelectChapter('wind')}
                className="text-xs font-mono text-sky-600 dark:text-sky-400 hover:underline inline-flex items-center gap-0.5 cursor-pointer"
              >
                <span>Balance</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => onSelectChapter('price')}
                className="text-xs font-mono text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white cursor-pointer"
              >
                Price →
              </button>
              <button
                type="button"
                onClick={() => onSelectChapter('europe')}
                className="text-xs font-mono text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white cursor-pointer"
              >
                Europe →
              </button>
            </div>
          </div>

          <div className="flex-1 min-h-0 flex flex-col justify-center overflow-hidden">
            <AllocationBars windAlloc={windAlloc} compact={true} />
          </div>

          <div className="flex-none pt-1.5 border-t border-slate-200/70 dark:border-white/10 flex flex-wrap items-center justify-between gap-2 text-[11px]">
            <div className="flex items-center gap-2.5 font-mono">
              <span>
                <strong className="text-emerald-600 dark:text-emerald-400">
                  {engineering?.benchmark
                    ? `${fmt(
                        Math.round(engineering.benchmark.speedup_index_vs_none)
                      )}×`
                    : '–'}
                </strong>{' '}
                <span className="text-slate-500 dark:text-slate-400">
                  index speedup
                </span>
              </span>
              <span className="text-slate-300 dark:text-slate-700">·</span>
              <span>
                <strong className="text-slate-900 dark:text-white">
                  {engineering?.tests ? engineering.tests.total : '–'}
                </strong>{' '}
                <span className="text-slate-500 dark:text-slate-400">
                  CI tests
                </span>
              </span>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={() => onSelectChapter('ev')}
                className="text-[11px] font-mono text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white cursor-pointer"
              >
                Electric cars →
              </button>
              <button
                type="button"
                onClick={() => onSelectChapter('strikes')}
                className="text-[11px] font-mono text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white cursor-pointer"
              >
                2024 Strikes →
              </button>
              <button
                type="button"
                onClick={() => onSelectChapter('craft')}
                className="text-[11px] font-mono text-sky-600 dark:text-sky-400 hover:underline inline-flex items-center gap-0.5 cursor-pointer"
              >
                <span>SQL &amp; Partitions</span>
                <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
          </div>
        </article>
      </div>
    </div>
  );
};
