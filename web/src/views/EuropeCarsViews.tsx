import React, { useState } from 'react';
import { ObservatoryData, fmt, dayFmt, pct, hrs } from '../dataLoader';
import { SvgLineChart } from '../components/SvgLineChart';
import { SqlEnginePanel, CodeFileSpec } from '../components/CodeInspector';
import { ChapterId } from './OverviewView';

interface ViewProps {
  data: ObservatoryData;
  onSelectChapter: (ch: ChapterId) => void;
}

type LensMode = 'visual' | 'matrix' | 'sql';

const LENS_ON =
  'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10';
const LENS_OFF = 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200';

function LensBar({ lens, setLens, matrixLabel }: { lens: LensMode; setLens: (l: LensMode) => void; matrixLabel: string }) {
  const tabs: [LensMode, string][] = [
    ['visual', 'Visual Pulse'],
    ['matrix', matrixLabel],
    ['sql', 'SQL & Engine'],
  ];
  return (
    <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg glass-well" role="group" aria-label="Chapter lens">
      {tabs.map(([id, label]) => (
        <button
          key={id}
          type="button"
          aria-pressed={lens === id}
          onClick={() => setLens(id)}
          className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all cursor-pointer ${lens === id ? LENS_ON : LENS_OFF}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Missing({ text }: { text: string }) {
  return (
    <div className="p-6 glass-card rounded-xl">
      <p className="text-sm text-rose-600 dark:text-rose-400" role="alert">
        {text}
      </p>
    </div>
  );
}

function Kpi({ id, tone, label, value, sub, valueClass }: { id: string; tone: string; label: string; value: string; sub: string; valueClass: string }) {
  return (
    <div className={`px-3.5 py-2 rounded-xl glass-kpi ${tone} min-w-0`}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400 truncate">{label}</div>
      <div id={id} className={`font-display text-lg sm:text-xl font-bold font-mono tabular-nums leading-tight ${valueClass}`}>
        {value}
      </div>
      <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate" title={sub}>
        {sub}
      </div>
    </div>
  );
}

const TH = 'py-1.5 px-2 text-[10px] font-mono uppercase text-slate-400';
const ordinal = (n: number) =>
  `${n}${n % 10 === 1 && n % 100 !== 11 ? 'st' : n % 10 === 2 && n % 100 !== 12 ? 'nd' : n % 10 === 3 && n % 100 !== 13 ? 'rd' : 'th'}`;
const monthFmt = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' });

/* ============================================================================
   Finland in Europe (Ember): price, carbon intensity and wind + solar
   ============================================================================ */
export const EuropeView: React.FC<ViewProps> = ({ data, onSelectChapter }) => {
  const [lens, setLens] = useState<LensMode>('visual');
  const d = data.europe;
  if (!d?.countries?.length || !d.finland_rank) {
    return <Missing text={data.errors.europe || 'Loading the European comparison…'} />;
  }

  const fi = d.countries.find((c: any) => c.area === 'Finland');
  const rk = d.finland_rank;
  const eu = d.eu;
  const cr = d.correlations;
  const ys: any[] = d.years || [];
  const span = `${monthFmt(d.window_first_month)} – ${monthFmt(d.window_last_month)}`;
  const sig = (x: any) => x.p_value < 0.05;
  const maxPrice = Math.max(...d.countries.map((c: any) => c.price));

  const firstEu = ys.find((y) => y.eu_intensity != null);
  const lastY = ys[ys.length - 1];
  const withEu = ys.filter((y) => y.eu_price != null);
  const widest = withEu.length
    ? withEu.reduce((a, y) => (y.eu_price - y.fi_price > a.eu_price - a.fi_price ? y : a))
    : null;
  const cheaperYears = withEu.filter((y) => y.fi_price < y.eu_price).length;
  const ck = d.price_check;

  const files: CodeFileSpec[] = [
    { label: 'SQL Comparison', filePath: 'sql/analysis/30_europe_comparison.sql' },
    { label: 'Python Ember Engine', filePath: 'src/europe.py' },
  ];

  const yearChart = (fiKey: string, euKey: string, unit: string, digits: number, aria: string) => (
    <SvgLineChart
      ariaLabel={aria}
      labels={ys.map((y) => String(y.year))}
      series={[
        { name: 'Finland', short: 'Finland', color: 'var(--rec)', width: 2.4, values: ys.map((y) => y[fiKey]) },
        { name: 'EU', short: 'EU', color: 'var(--ink-2)', width: 1.6, dash: '4 3', values: ys.map((y) => y[euKey]) },
      ]}
      height={150}
      forceZero={true}
      directLabels={true}
      yUnit={unit}
      xTick={(i, l, narrow) => ((narrow || ys.length > 8) && i % 2 ? null : l)}
      tipValue={(v) => `${fmt(v, digits)} ${unit}`}
    />
  );

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden" id="chapter-europe">
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-xl glass-card">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-600 dark:text-sky-400">
            Ember · {rk.of} European Countries · {span}
          </div>
          <h1 className="font-display text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Finland in Europe: Price, Carbon and Wind
          </h1>
        </div>
        <LensBar lens={lens} setLens={setLens} matrixLabel="Country Matrix" />
      </div>

      <div className="shrink-0 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <Kpi
          id="eu-rank-price"
          tone="telemetry-signal"
          label="Wholesale Price Rank"
          value={`${ordinal(rk.price_eur_mwh)} of ${rk.of}`}
          sub={`cheapest: ${fmt(fi?.price, 1)} €/MWh (EU ${fmt(eu?.price_demand_weighted, 1)})`}
          valueClass="text-sky-600 dark:text-sky-400"
        />
        <Kpi
          id="eu-intensity"
          tone="telemetry-nominal"
          label="CO₂ per kWh Generated"
          value={`${fmt(fi?.intensity, 0)} g`}
          sub={`EU ${fmt(eu?.intensity, 0)} g · ${ordinal(rk.intensity_g_kwh)} cleanest`}
          valueClass="text-emerald-600 dark:text-emerald-400"
        />
        <Kpi
          id="eu-wind-solar"
          tone="telemetry-warning"
          label="Wind + Solar Share"
          value={fi ? pct(fi.wind_solar) : '–'}
          sub={`${ordinal(rk.wind_solar_share)} of ${rk.of}; nuclear ${fi ? pct(fi.nuclear) : '–'}, hydro ${fi ? pct(fi.hydro) : '–'}`}
          valueClass="text-amber-600 dark:text-amber-400"
        />
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        <div className="lg:col-span-4 flex flex-col justify-between p-4 rounded-xl glass-card min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-2.5">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">The Twelve-Month Verdict</div>
            <h2 className="font-display text-sm sm:text-base font-bold text-slate-900 dark:text-white leading-snug">
              Finland had the {rk.price_eur_mwh === 1 ? 'lowest' : `${ordinal(rk.price_eur_mwh)} lowest`} wholesale price of the {rk.of} countries, with electricity about {fmt(eu.intensity / fi.intensity, 1)}× cleaner than the EU&apos;s.
            </h2>
            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed" id="eu-takeaway">
              Its wind and solar share is only middling: low-carbon Finland rests on nuclear and hydro as well as wind. Across the {cr.intensity_g_kwh.n} countries, dirtier electricity tends to be more expensive (rank correlation <strong className="font-mono">{fmt(cr.intensity_g_kwh.r, 2)}</strong>, p = {fmt(cr.intensity_g_kwh.p_value, 3)}{sig(cr.intensity_g_kwh) ? '' : ', could be chance'}), but a larger wind and solar share alone {sig(cr.wind_solar_share) ? 'also goes with lower prices' : 'does not clearly go with lower prices'} ({fmt(cr.wind_solar_share.r, 2)}, p = {fmt(cr.wind_solar_share.p_value, 2)}).
            </p>
            <div className="p-3 rounded-lg glass-well space-y-1">
              <div className="text-[10px] font-mono uppercase tracking-wider text-sky-600 dark:text-sky-400 font-semibold">
                Year by Year
              </div>
              <p className="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed" id="eu-years-takeaway">
                {firstEu && lastY ? (
                  <>
                    Since {firstEu.year} Finnish generation fell from {fmt(firstEu.fi_intensity, 0)} to {fmt(lastY.fi_intensity, 0)} g/kWh (EU {fmt(firstEu.eu_intensity, 0)} → {fmt(lastY.eu_intensity, 0)}), as wind and solar rose from {pct(firstEu.fi_wind_solar)} to {pct(lastY.fi_wind_solar)} and Olkiluoto 3 started in 2023. Finland was cheaper than the EU in {cheaperYears} of {withEu.length} years{widest ? `, by the widest margin in ${widest.year} (${fmt(widest.fi_price, 0)} vs ${fmt(widest.eu_price, 0)} €/MWh)` : ''}; in {lastY.year} it ranked {ordinal(lastY.fi_price_rank)} cheapest of {lastY.countries}.
                  </>
                ) : (
                  '–'
                )}
              </p>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
              Countries differ in everything at once (hydro, nuclear, links to neighbours, gas), so this describes Europe; it does not show what would happen to one country&apos;s price if it changed its mix.
            </p>
          </div>
          <div className="pt-2.5 mt-2 border-t border-slate-200/70 dark:border-white/10 text-[11px] font-mono text-slate-500 dark:text-slate-400 space-y-1.5 shrink-0">
            <div className="flex items-center justify-between gap-2">
              <span>Ember vs this warehouse ({ck?.months} months)</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">±{fmt(ck?.mean_abs_diff_plain, 2)} €/MWh</span>
            </div>
            <button
              type="button"
              onClick={() => onSelectChapter('price')}
              className="w-full flex items-center justify-between text-left text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
            >
              <span>What wind does to Finland&apos;s price</span>
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>

        <div className="lg:col-span-8 flex flex-col min-h-0 rounded-xl glass-card p-4 overflow-hidden">
          {lens === 'visual' && (
            <div key="visual" className="lens-enter h-full flex flex-col gap-2 min-h-0 overflow-hidden">
              <div className="flex-none flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">Finland and the EU, Year by Year</span>
                <span className="text-[11px] font-mono text-slate-400">Finland (solid) · EU, demand-weighted (dashed)</span>
              </div>
              <div className="flex-1 min-h-0 flex flex-col gap-1">
                <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">Day-ahead wholesale price, €/MWh</div>
                <div className="flex-1 min-h-[120px]">{yearChart('fi_price', 'eu_price', '€/MWh', 1, 'Yearly wholesale price, Finland and the EU')}</div>
              </div>
              <div className="flex-1 min-h-0 flex flex-col gap-1">
                <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">Carbon intensity of generation, gCO₂/kWh</div>
                <div className="flex-1 min-h-[120px]">{yearChart('fi_intensity', 'eu_intensity', 'g/kWh', 0, 'Yearly carbon intensity of generation, Finland and the EU')}</div>
              </div>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full overflow-y-auto thin-scroll pr-1 space-y-3">
              <div className="text-xs font-semibold text-slate-900 dark:text-white">
                {rk.of} Countries, Last Twelve Complete Months · Sorted by Price
              </div>
              <table className="w-full text-left border-collapse text-xs" id="eu-table">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-800">
                    <th className={TH}>Country</th>
                    <th className={`${TH} text-right`}>Price €/MWh</th>
                    <th className={`${TH} text-right`} title="Life-cycle emissions per kWh generated">gCO₂/kWh</th>
                    <th className={`${TH} text-right`}>Wind + Solar</th>
                    <th className={`${TH} text-right`}>Low-Carbon</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                  {d.countries.map((c: any) => {
                    const me = c.area === 'Finland';
                    return (
                      <tr key={c.area} className={me ? 'bg-sky-500/10 font-semibold' : 'hover:bg-slate-50/80 dark:hover:bg-slate-900/40'}>
                        <td className={`py-1 px-2 font-sans ${me ? 'text-sky-700 dark:text-sky-300' : 'text-slate-900 dark:text-white'}`}>{c.area}</td>
                        <td className="py-1 px-2 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <span className="hidden sm:block h-1 rounded-full bg-[var(--rec)] opacity-70" style={{ width: `${Math.max(4, (60 * c.price) / maxPrice)}px` }} aria-hidden="true" />
                            <span className="w-10 text-right">{fmt(c.price, 1)}</span>
                          </div>
                        </td>
                        <td className="py-1 px-2 text-right">{fmt(c.intensity, 0)}</td>
                        <td className="py-1 px-2 text-right">{pct(c.wind_solar)}</td>
                        <td className="py-1 px-2 text-right">{pct(c.clean)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {d.incomplete?.length > 0 && (
                <p className="text-[11px] text-slate-500 dark:text-slate-400">Left out for missing months: {d.incomplete.join(', ')}.</p>
              )}
              <div className="pt-2 border-t border-slate-200 dark:border-slate-800 space-y-2 text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
                <div className="text-xs font-semibold text-slate-900 dark:text-white">Does Ember agree with this warehouse?</div>
                <p id="eu-check">
                  Ember&apos;s monthly price for Finland against the hourly ENTSO-E prices in this warehouse, {monthFmt(ck.first)} – {monthFmt(ck.last)} ({ck.months} months): the plain mean of the hours differs from Ember&apos;s figure by {fmt(ck.mean_abs_diff_plain, 2)} €/MWh on average (at most {fmt(ck.max_abs_diff_plain, 2)}). Weighting the hours by Finnish consumption moves them further away ({fmt(ck.mean_abs_diff_load_weighted, 2)} €/MWh), so for Finland Ember&apos;s figure behaves like the plain mean. Both come from ENTSO-E, so this checks that the two pipelines agree, not that either is independently right.
                </p>
                <div className="text-xs font-semibold text-slate-900 dark:text-white">How it works</div>
                <p>
                  Price: mean of Ember&apos;s monthly day-ahead prices (for countries with several bidding zones, Ember&apos;s national figure). Carbon intensity: Ember&apos;s life-cycle emissions of all generation divided by generation, so imports do not count. EU price: the EU countries&apos; prices weighted by their demand (Ember publishes no EU price). Rank correlations are Spearman&apos;s, with p-values from 10,000 shuffles. Data:{' '}
                  <a className="text-sky-600 dark:text-sky-400 hover:underline" href="https://ember-energy.org/data/" target="_blank" rel="noopener noreferrer">Ember</a> (CC BY 4.0).
                </p>
              </div>
            </div>
          )}

          {lens === 'sql' && (
            <div key="sql" className="lens-enter h-full min-h-0">
              <SqlEnginePanel files={files} sqlData={data.sql} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/* ============================================================================
   Electric cars (Traficom) against weather-adjusted consumption growth
   ============================================================================ */
export const EvChargingView: React.FC<ViewProps> = ({ data, onSelectChapter }) => {
  const [lens, setLens] = useState<LensMode>('visual');
  const d = data.evCharging;
  if (!d?.fleet?.length || !d.growth) {
    return <Missing text={data.errors.evCharging || 'Loading the electric car estimate…'} />;
  }

  const last = d.fleet[d.fleet.length - 1];
  const E = d.energy_now;
  const A = d.added_mw;
  const g = d.growth;
  const rest = g.without_boilers;
  const boil = g.boilers;
  const all = g.consumption;
  const sc = d.scenarios;
  const c = rest.night_minus_evening;
  const k = (n: number) => `${fmt(n / 1000, 0)}k`;
  const mwr = (x: any) => `${fmt(x.estimate, 0)} MW (${fmt(x.ci_low, 0)} to ${fmt(x.ci_high, 0)})`;
  const q = String(last.quarter).replace('Q', ' Q');
  const fmtD = (iso: string) => dayFmt(`${iso}T12:00:00Z`);
  const inside = (v: number) => c.ci_low <= v && v <= c.ci_high;
  const eveOut = !inside(sc.evening.night_minus_evening);
  const nightOut = !inside(sc.night.night_minus_evening);
  const fl: any[] = d.fleet;
  const hourLabels = Array.from({ length: 24 }, (_, h) => hrs(h));

  const files: CodeFileSpec[] = [
    { label: 'SQL Hourly Panel', filePath: 'sql/analysis/31_consumption_boilers_hourly.sql' },
    { label: 'Python Growth Model', filePath: 'src/ev_charging.py' },
  ];

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden" id="chapter-ev">
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-xl glass-card">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-indigo-600 dark:text-indigo-300">
            Traficom Fleet · Fingrid Consumption · {fmtD(d.later.first)} – {fmtD(d.later.last)}
          </div>
          <h1 className="font-display text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Do Electric Cars Show Up in Finland&apos;s Consumption?
          </h1>
        </div>
        <LensBar lens={lens} setLens={setLens} matrixLabel="Estimate & Timing Matrix" />
      </div>

      <div className="shrink-0 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <Kpi
          id="car-bev"
          tone="telemetry-signal"
          label={`Battery-Electric Fleet (${q})`}
          value={k(last.bev)}
          sub={`cars and vans in traffic, plus ${k(last.phev)} plug-in hybrids`}
          valueClass="text-sky-600 dark:text-sky-400"
        />
        <Kpi
          id="car-twh"
          tone="telemetry-indigo"
          label="Charging Energy a Year"
          value={`${fmt(E.central.gwh_per_year / 1000, 1)} TWh`}
          sub={`${fmt(E.low.gwh_per_year / 1000, 1)}–${fmt(E.high.gwh_per_year / 1000, 1)} TWh · ${fmt((100 * E.central.mw) / d.mean_consumption_mw, 1)}% of consumption`}
          valueClass="text-indigo-600 dark:text-indigo-300"
        />
        <Kpi
          id="car-added"
          tone="telemetry-warning"
          label="Added by Cars in the Past Year"
          value={`+${fmt(A.central, 0)} MW`}
          sub={`${fmt(A.low, 0)}–${fmt(A.high, 0)} MW vs +${fmt(rest.mean.estimate, 0)} MW growth in all else but boilers`}
          valueClass="text-amber-600 dark:text-amber-400"
        />
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        <div className="lg:col-span-4 flex flex-col justify-between p-4 rounded-xl glass-card min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-2.5">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">The Verdict</div>
            <h2 className="font-display text-sm sm:text-base font-bold text-slate-900 dark:text-white leading-snug">
              The cars&apos; estimated +{fmt(A.central, 0)} MW is about {pct(A.central / rest.mean.estimate)} of the year&apos;s growth outside electric boilers: most of the growth is something else.
            </h2>
            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed" id="car-takeaway">
              Weather-adjusted consumption grew by {mwr(all.mean)}. Electric boilers account for {fmt(boil.mean.estimate, 0)} MW of it; the rest grew by {mwr(rest.mean)}, with heat pumps, data centres, industry and other electrification in the same numbers. The timing says more: growth outside the boilers was{' '}
              <strong className="font-mono">{fmt(Math.abs(c.estimate), 0)} MW</strong>{' '}
              {c.estimate >= 0 ? 'larger at night (00–06) than in the evening (17–22)' : 'larger in the evening (17–22) than at night (00–06)'} (95% interval {fmt(c.ci_low, 0)} to {fmt(c.ci_high, 0)}).
            </p>
            <div className="p-3 rounded-lg glass-well space-y-1">
              <div className="text-[10px] font-mono uppercase tracking-wider text-indigo-600 dark:text-indigo-300 font-semibold">
                When do they charge?
              </div>
              <p className="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
                {eveOut
                  ? `If the new cars all charged in the evening, the evening would have grown about ${fmt(-sc.evening.night_minus_evening, 0)} MW more than the night, which the data rule out unless something else grew at night by as much. `
                  : 'Charging all in the evening would fit the data too. '}
                {nightOut
                  ? `All of it at night would have made the night ${fmt(sc.night.night_minus_evening, 0)} MW ahead, just outside the interval, so charging that leans to the night (or is spread over the day) fits best.`
                  : 'Charging all at night, as spot-price contracts and timers encourage, fits the data.'}
              </p>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
              A difference between two blocks of hours is the most this can say: the cars cannot be separated from everything else that grew in the same year.
            </p>
          </div>
          <div className="pt-2.5 mt-2 border-t border-slate-200/70 dark:border-white/10 text-[11px] font-mono text-slate-500 dark:text-slate-400 shrink-0">
            <button
              type="button"
              onClick={() => onSelectChapter('co2')}
              className="w-full flex items-center justify-between text-left text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
            >
              <span>Tomorrow&apos;s cleanest hours to charge</span>
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>

        <div className="lg:col-span-8 flex flex-col min-h-0 rounded-xl glass-card p-4 overflow-hidden">
          {lens === 'visual' && (
            <div key="visual" className="lens-enter h-full flex flex-col gap-2 min-h-0 overflow-hidden">
              <div className="flex-[3] min-h-0 flex flex-col gap-1">
                <div className="flex-none flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">Where in the Day Did Consumption Grow?</span>
                  <span className="text-[11px] font-mono text-slate-400">Year on year, weather-adjusted · cars if charged 17–22 / 22–06 (dashed)</span>
                </div>
                <div className="flex-1 min-h-[150px]">
                  <SvgLineChart
                    ariaLabel="Weather-adjusted growth of consumption by hour of the day, with what electric cars would add"
                    labels={hourLabels}
                    series={[
                      { name: 'Without electric boilers', short: 'Other', color: 'var(--al-imports)', width: 2.4, values: rest.by_hour },
                      { name: 'Electric boilers', short: 'Boilers', color: 'var(--al-hydro)', width: 2, values: boil.by_hour },
                      { name: 'Cars, if charged 17–22', short: 'Cars eve', color: 'var(--al-cons)', width: 1.4, dash: '4 3', values: sc.evening.by_hour },
                      { name: 'Cars, if charged 22–06', short: 'Cars night', color: 'var(--al-other)', width: 1.4, dash: '4 3', values: sc.night.by_hour },
                    ]}
                    bands={[
                      {
                        lo: rest.by_hour.map((v: number, i: number) => v - rest.ci95_by_hour[i]),
                        hi: rest.by_hour.map((v: number, i: number) => v + rest.ci95_by_hour[i]),
                        color: 'var(--al-imports)',
                        opacity: 0.12,
                      },
                    ]}
                    height={190}
                    forceZero={true}
                    directLabels={true}
                    yUnit="MW"
                    xTick={(i, l, narrow) => (i % (narrow ? 6 : 3) === 0 ? l : null)}
                    tipTitle={(l) => `${l}–${l.slice(0, 2)}:59 Finnish time`}
                    tipValue={(v) => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v), 0)} MW`}
                    tipExtra={(i) => [`95% interval, without boilers: ±${fmt(rest.ci95_by_hour[i], 0)} MW`]}
                  />
                </div>
              </div>
              <div className="flex-[2] min-h-0 flex flex-col gap-1 pt-1 border-t border-slate-200/70 dark:border-white/10">
                <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
                  Cars and vans in traffic, end of each quarter (Traficom)
                </div>
                <div className="flex-1 min-h-[110px]">
                  <SvgLineChart
                    ariaLabel="Battery-electric and plug-in hybrid cars and vans in traffic by quarter"
                    labels={fl.map((x) => String(x.quarter))}
                    series={[
                      { name: 'Battery electric', short: 'BEV', color: 'var(--al-imports)', width: 2.2, values: fl.map((x) => x.bev) },
                      { name: 'Plug-in hybrid', short: 'PHEV', color: 'var(--al-other)', width: 2, values: fl.map((x) => x.phev) },
                    ]}
                    height={130}
                    forceZero={true}
                    directLabels={true}
                    yUnit="cars"
                    yFmt={(v) => (v >= 1000 ? `${fmt(v / 1000, 0)}k` : fmt(v, 0))}
                    xTick={(_i, l) => (l.endsWith('Q1') && Number(l.slice(0, 4)) % 2 === 0 ? l.slice(0, 4) : null)}
                    tipTitle={(l) => l.replace('Q', ' Q')}
                    tipValue={(v) => fmt(v, 0)}
                  />
                </div>
              </div>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full overflow-y-auto thin-scroll pr-1 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <div className="text-xs font-semibold text-slate-900 dark:text-white mb-1.5">Charging Energy, Today&apos;s Fleet</div>
                  <table className="w-full text-left border-collapse text-[11px]" id="car-energy-table">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-800">
                        <th className={TH}>Case</th>
                        <th className={`${TH} text-right`}>GWh / year</th>
                        <th className={`${TH} text-right`}>Mean MW</th>
                        <th className={`${TH} text-right`}>Added in year</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                      {(['low', 'central', 'high'] as const).map((key) => (
                        <tr key={key} className={key === 'central' ? 'font-semibold' : ''}>
                          <td className="py-1 px-2 font-sans text-slate-900 dark:text-white capitalize">{key}</td>
                          <td className="py-1 px-2 text-right">{fmt(E[key].gwh_per_year, 0)}</td>
                          <td className="py-1 px-2 text-right">{fmt(E[key].mw, 1)}</td>
                          <td className="py-1 px-2 text-right text-amber-600 dark:text-amber-400">+{fmt(A[key], 1)} MW</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <div className="text-xs font-semibold text-slate-900 dark:text-white mb-1.5">Night (00–06) minus Evening (17–22)</div>
                  <table className="w-full text-left border-collapse text-[11px]" id="car-timing-table">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-800">
                        <th className={TH}>Series</th>
                        <th className={`${TH} text-right`}>Night − evening</th>
                        <th className={`${TH} text-right`}>Inside 95%?</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                      <tr className="font-semibold">
                        <td className="py-1 px-2 font-sans text-slate-900 dark:text-white">Measured, without boilers</td>
                        <td className="py-1 px-2 text-right">{fmt(c.estimate, 0)} MW</td>
                        <td className="py-1 px-2 text-right text-slate-500">{fmt(c.ci_low, 0)} to {fmt(c.ci_high, 0)}</td>
                      </tr>
                      {[
                        ['Cars, if charged 17–22', sc.evening.night_minus_evening],
                        ['Cars, if charged 22–06', sc.night.night_minus_evening],
                      ].map(([label, v]) => (
                        <tr key={label as string}>
                          <td className="py-1 px-2 font-sans text-slate-900 dark:text-white">{label}</td>
                          <td className="py-1 px-2 text-right">{fmt(v as number, 0)} MW</td>
                          <td className={`py-1 px-2 text-right font-semibold ${inside(v as number) ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                            {inside(v as number) ? 'yes' : 'no'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="pt-2 border-t border-slate-200 dark:border-slate-800 space-y-2 text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
                <div className="text-xs font-semibold text-slate-900 dark:text-white">The estimate</div>
                <p id="car-energy">
                  At their first inspection, at age {d.km.age}, battery-electric cars had driven {fmt(d.km.bev.km_per_year)} km a year and plug-in hybrids {fmt(d.km.phev.km_per_year)} ({fmt(d.km.bev.cars)} and {fmt(d.km.phev.cars)} cars inspected in {d.km.inspection_year}). At {d.assumptions.kwh_per_km[1]} kWh per km from the grid ({d.assumptions.kwh_per_km[0]}–{d.assumptions.kwh_per_km[2]}, charging losses and winter included) and {pct(d.assumptions.phev_electric_share[1])} of a hybrid&apos;s km on electricity ({pct(d.assumptions.phev_electric_share[0])}–{pct(d.assumptions.phev_electric_share[2])}), today&apos;s fleet uses about {fmt(E.central.gwh_per_year / 1000, 2)} TWh a year, {fmt(E.central.mw, 0)} MW on average. The two kWh figures are assumptions, not measurements; the range carries them through.
                </p>
                <div className="text-xs font-semibold text-slate-900 dark:text-white">How it works</div>
                <p id="car-method">
                  Fleet: Traficom&apos;s cars and vans in traffic in mainland Finland by driving power, quarterly. Kilometres: mean odometer at the first periodic inspection (age {d.km.age}) divided by {d.km.age}; vans are assumed to drive like cars. Cars added over the year: fleet at the middle of the later year minus at the middle of the earlier ({k(d.earlier.fleet_mid.bev)} → {k(d.later.fleet_mid.bev)} battery electric), times km and kWh. Growth by hour: OLS of hourly consumption on 24 hour-of-day × later-year terms with hour, weekday and month fixed effects, heating degrees by quarter of the day and their 24-hour mean, sun elevation and holidays; Newey-West 95% intervals over 24 hours. {fmt(d.earlier.hours)} and {fmt(d.later.hours)} hours with boiler data. Data:{' '}
                  <a className="text-sky-600 dark:text-sky-400 hover:underline" href="https://trafi2.stat.fi/PXWeb/pxweb/en/TraFi/" target="_blank" rel="noopener noreferrer">Traficom statistics database</a> (CC BY 4.0).
                </p>
              </div>
            </div>
          )}

          {lens === 'sql' && (
            <div key="sql" className="lens-enter h-full min-h-0">
              <SqlEnginePanel files={files} sqlData={data.sql} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
