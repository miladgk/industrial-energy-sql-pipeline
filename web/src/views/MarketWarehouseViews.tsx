import React, { useState } from 'react';
import {
  ObservatoryData,
  fmt,
  dayFmt,
  pct,
} from '../dataLoader';
import { SvgLineChart } from '../components/SvgLineChart';
import { AllocationBars } from '../components/AllocationBars';
import { SqlEnginePanel, CodeFileSpec } from '../components/CodeInspector';
import { ChapterId } from './OverviewView';
import { Copy, Check } from 'lucide-react';

interface ViewProps {
  data: ObservatoryData;
  onSelectChapter: (ch: ChapterId) => void;
}

type LensMode = 'visual' | 'matrix' | 'sql';

function LensBar({
  lens,
  setLens,
  visualLabel = 'Visual Pulse',
  matrixLabel = 'Evidence Matrix',
  sqlLabel = 'SQL & Engine',
}: {
  lens: LensMode;
  setLens: (l: LensMode) => void;
  visualLabel?: string;
  matrixLabel?: string;
  sqlLabel?: string;
}) {
  return (
    <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg glass-well">
      <button
        type="button"
        onClick={() => setLens('visual')}
        className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all cursor-pointer ${
          lens === 'visual'
            ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
            : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
        }`}
      >
        {visualLabel}
      </button>
      <button
        type="button"
        onClick={() => setLens('matrix')}
        className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all cursor-pointer ${
          lens === 'matrix'
            ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
            : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
        }`}
      >
        {matrixLabel}
      </button>
      <button
        type="button"
        onClick={() => setLens('sql')}
        className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all cursor-pointer ${
          lens === 'sql'
            ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/60 dark:border-white/10'
            : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
        }`}
      >
        {sqlLabel}
      </button>
    </div>
  );
}

/* ============================================================================
   Wind Power Balance & Nordic Reservoir Storage
   ============================================================================ */
export const WindBalanceView: React.FC<ViewProps> = ({ data }) => {
  const [lens, setLens] = useState<LensMode>('visual');
  const wa = data.windAlloc;
  const hf = data.hydroFlex;

  // Whole percentages, or '–' when the file is missing.
  const sh = (x: any) => (x?.share != null ? `${Math.round(Number(x.share) * 100)}%` : '–');
  const wCables = sh(wa?.wind?.imports);
  const wHydro = sh(wa?.wind?.hydro);
  const wOther = sh(wa?.wind?.other);
  const wCons = sh(wa?.wind?.consumption);
  const borders = wa?.breakdown?.wind?.borders;

  const p10 = hf?.share_at_storage?.find((s: any) => s.percentile === 10) || hf?.share_at_storage?.[0];
  const p90 = hf?.share_at_storage?.find((s: any) => s.percentile === 90) || hf?.share_at_storage?.[2];
  const dryHydro = sh(p10?.shares?.hydro);
  const fullHydro = sh(p90?.shares?.hydro);
  const signedZ = (z: any) => (z == null ? '–' : `${Number(z) < 0 ? '−' : '+'}${fmt(Math.abs(Number(z)), 2)}`);

  const dailyState: any[] = hf?.daily_state || [];
  const stateSampled = dailyState.filter((_: any, idx: number) => idx % 7 === 0 || idx === dailyState.length - 1);

  const annChannels = [
    { key: 'imports', label: 'Lower net imports (cross-border cables)' },
    { key: 'hydro', label: 'Less Finnish hydro output (water saved)' },
    { key: 'other', label: 'Less thermal & district-heat CHP' },
    { key: 'consumption', label: 'More domestic consumption (e-boilers)' },
  ];

  const borderLabels: Record<string, string> = {
    sweden_north: 'Northern Sweden (SE1 AC)',
    sweden_central: 'Central Sweden (SE3 Fenno-Skan)',
    estonia: 'Estonia (EstLink 1 & 2)',
    norway: 'Northern Norway (NO4)',
    unmeasured: 'Unmeasured border residual',
  };

  const plantLabels: Record<string, string> = {
    chp_district_heating: 'District-heating CHP',
    chp_industrial: 'Industrial CHP',
    reserve_and_small: 'Reserve & small thermal',
    rest: 'Other domestic thermal',
  };

  const files: CodeFileSpec[] = [
    {
      label: 'SQL Panel',
      filePath: 'sql/analysis/24_wind_allocation_panel.sql',
    },
    {
      label: 'Python FE Engine',
      filePath: 'src/wind_allocation.py',
    },
    {
      label: 'SQL Hydrology',
      filePath: 'sql/analysis/27_hydrology_state.sql',
    },
    {
      label: 'Python Hydro Flex',
      filePath: 'src/hydro_flex.py',
    },
  ];

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-xl glass-card">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-teal-600 dark:text-teal-400">
            Exact Grid Accounting Identity · SYKE &amp; NVE Reservoir Hydrology
          </div>
          <h1 className="font-display text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Where an Extra Megawatt of Wind Actually Goes ({fmt(wa?.hours, 0)} Verified Hours)
          </h1>
        </div>
        <LensBar
          lens={lens}
          setLens={setLens}
          visualLabel="Visual Pulse"
          matrixLabel="Borders, Seasons & Hydro Matrix"
          sqlLabel="SQL & Engine"
        />
      </div>

      {/* KPI Strip */}
      <div className="shrink-0 grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">1. Cross-Border Cables</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-sky-600 dark:text-sky-400 leading-tight">
            {wCables}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Sweden SE1 ({sh(borders?.sweden_north)}) + SE3 ({sh(borders?.sweden_central)}) + Estonia ({sh(borders?.estonia)})
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">2. Flexible Consumption</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-amber-600 dark:text-amber-400 leading-tight">
            {wCons}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Electric district-heating boilers &amp; load
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">3. Thermal CHP &amp; Hydro</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-teal-600 dark:text-teal-400 leading-tight">
            {wOther} + {wHydro}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            {wOther} CHP fuel saved · {wHydro} domestic hydro saved
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-indigo">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Low vs High Reservoir Fill</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-slate-900 dark:text-white leading-tight">
            {dryHydro} → {fullHydro}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Hydro share at P10 dry vs P90 full storage
          </div>
        </div>
      </div>

      {/* Main Split Body */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        {/* Left Column */}
        <div className="lg:col-span-4 flex flex-col justify-between p-4 rounded-xl glass-card min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-2.5">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              3-Second Thermodynamic Verdict
            </div>
            <h2 className="font-display text-sm sm:text-base font-bold text-slate-900 dark:text-white leading-snug">
              Because generation plus net imports equals consumption in every hour, the four responses sum to 100.0%.
            </h2>
            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
              Controlling for temperature and hour/weekday/month fixed effects across {fmt(wa?.hours)} hours, Sweden&apos;s connected grid absorbs {borders ? `${fmt((Number(borders.sweden_north?.share) + Number(borders.sweden_central?.share)) * 100, 0)}%` : '–'} of every extra Finnish wind megawatt: SE1 {borders ? `${fmt(Number(borders.sweden_north?.share) * 100, 1)}%` : '–'} and SE3 {borders ? `${fmt(Number(borders.sweden_central?.share) * 100, 1)}%` : '–'}.
            </p>

            <div className="p-3 rounded-lg glass-well space-y-1">
              <div className="text-[10px] font-mono uppercase tracking-wider text-teal-600 dark:text-teal-400 font-semibold">
                Real SYKE + NVE Reservoir Physics ({fmt(hf?.hours)} hrs)
              </div>
              <p className="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
                When five major Finnish lakes (Lokka, Porttipahta, Oulujärvi, Saimaa, Näsijärvi) are low (10th percentile, z = {signedZ(p10?.storage_z)}), hydro dams absorb <strong className="font-mono">{dryHydro}</strong> of extra wind. When lakes are full (90th percentile, z = {signedZ(p90?.storage_z)}), hydro absorption drops to <strong className="font-mono">{fullHydro}</strong>.
              </p>
            </div>
          </div>

          <div className="pt-2.5 border-t border-slate-200/70 dark:border-white/10 text-[11px] font-mono text-slate-500 dark:text-slate-400 flex items-center justify-between shrink-0">
            <span>Identity r vs measured net export</span>
            <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
              {fmt(wa?.net_import_check?.r_identity_vs_measured_194, 4)}
            </span>
          </div>
        </div>

        {/* Right Lens Deck */}
        <div className="lg:col-span-8 flex flex-col min-h-0 rounded-xl glass-card p-3.5 overflow-hidden">
          {lens === 'visual' && (
            <div key="visual" className="lens-enter h-full flex flex-col justify-between min-h-0 overflow-hidden gap-2">
              <div className="flex-none">
                <div className="text-xs font-semibold text-slate-900 dark:text-white mb-1.5">
                  Where 1 Extra MW Goes — Interactive 100% Power Balance Bars
                </div>
                <AllocationBars windAlloc={wa} compact={false} />
              </div>

              {stateSampled.length > 0 && (
                <div className="flex-1 min-h-0 flex flex-col pt-2 border-t border-slate-200/70 dark:border-white/10 overflow-hidden">
                  <div className="flex-none flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-slate-900 dark:text-white">
                      SYKE Reservoir Storage &amp; Tornionjoki Inflow Z-Score vs. 2000–2022 Norm
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">
                      0 = seasonal norm (SD units)
                    </span>
                  </div>
                  <div className="flex-1 min-h-0">
                    <SvgLineChart
                      ariaLabel="SYKE reservoir storage and inflow z-scores"
                      labels={stateSampled.map((r: any) => String(r.day))}
                      referenceLines={[
                        {
                          y: 0,
                          label: '0σ norm',
                          color: 'var(--ink-2)',
                          dash: '4 3',
                          position: 'right',
                        },
                      ]}
                      series={[
                        {
                          name: 'Reservoir storage z-score',
                          short: 'Storage z',
                          color: '#38bdf8',
                          width: 2.1,
                          values: stateSampled.map((r: any) => Number(r.storage_z)),
                        },
                        {
                          name: 'Tornionjoki inflow z-score',
                          short: 'Inflow z',
                          color: '#2dd4bf',
                          width: 1.4,
                          dash: '4 3',
                          values: stateSampled.map((r: any) => Number(r.inflow_z)),
                        },
                      ]}
                      height={135}
                      forceZero={true}
                      directLabels={true}
                      xTick={(i, l) => (i % 24 === 0 ? l.slice(0, 7) : null)}
                      yFmt={(v: number) => `${v > 0 ? '+' : ''}${fmt(v, 1)}σ`}
                      tipTitle={(l: string) => dayFmt(l)}
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full overflow-y-auto thin-scroll pr-1 space-y-4">
              <div>
                <div className="text-xs font-semibold text-slate-900 dark:text-white mb-2">
                  Annual Power Balance: +1 MW Wind vs +1 MW Nuclear ({fmt(wa?.hours, 0)} hrs)
                </div>
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-800 text-[10px] font-mono uppercase text-slate-400">
                      <th className="py-1.5 px-2">Balancing Channel</th>
                      <th className="py-1.5 px-2 text-right">Share of +1 MW Wind</th>
                      <th className="py-1.5 px-2 text-right">95% Newey-West CI</th>
                      <th className="py-1.5 px-2 text-right">Share of +1 MW Nuclear</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                    {annChannels.map((ch) => {
                      const wObj = wa?.wind?.[ch.key];
                      const nObj = wa?.nuclear?.[ch.key];
                      return (
                        <tr key={ch.key} className="hover:bg-slate-50/80 dark:hover:bg-slate-900/40">
                          <td className="py-1.5 px-2 font-sans font-medium text-slate-900 dark:text-white">
                            {ch.label}
                          </td>
                          <td className="py-1.5 px-2 text-right font-bold text-sky-600 dark:text-sky-400">
                            {pct(wObj?.share ?? 0)}
                          </td>
                          <td className="py-1.5 px-2 text-right text-slate-500">
                            {pct(wObj?.ci_low ?? 0)} – {pct(wObj?.ci_high ?? 0)}
                          </td>
                          <td className="py-1.5 px-2 text-right text-slate-600 dark:text-slate-300">
                            {nObj ? pct(nObj.share ?? 0) : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-200 dark:border-slate-800">
                <div>
                  <div className="text-xs font-semibold text-slate-900 dark:text-white mb-1.5">
                    Border Cables &amp; Domestic CHP Breakdown
                  </div>
                  <div className="space-y-1 text-[11px]">
                    {Object.entries(wa?.breakdown?.wind?.borders || {}).map(([k, v]: [string, any]) => (
                      <div key={k} className="flex items-center justify-between py-1 px-2 rounded glass-well">
                        <span className="text-slate-700 dark:text-slate-300">{borderLabels[k] || k}</span>
                        <span className="font-mono font-bold text-sky-600 dark:text-sky-400">{pct(v.share)}</span>
                      </div>
                    ))}
                    {Object.entries(wa?.breakdown?.wind?.plants || {}).map(([k, v]: [string, any]) => (
                      <div key={k} className="flex items-center justify-between py-1 px-2 rounded glass-well">
                        <span className="text-slate-700 dark:text-slate-300">{plantLabels[k] || k}</span>
                        <span className="font-mono font-bold text-teal-600 dark:text-teal-400">{pct(v.share)}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-xs font-semibold text-slate-900 dark:text-white mb-1.5">
                    By Reservoir Storage Percentile (SYKE + NVE)
                  </div>
                  <table className="w-full text-left border-collapse text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-800 text-[10px] font-mono uppercase text-slate-400">
                        <th className="py-1 px-1.5">Storage Level</th>
                        <th className="py-1 px-1.5 text-right">Cables</th>
                        <th className="py-1 px-1.5 text-right">Hydro</th>
                        <th className="py-1 px-1.5 text-right">CHP</th>
                        <th className="py-1 px-1.5 text-right">Load</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                      {(hf?.share_at_storage || []).map((row: any) => (
                        <tr key={row.percentile}>
                          <td className="py-1 px-1.5 font-sans font-medium text-slate-900 dark:text-white">
                            P{row.percentile} ({fmt(row.storage_z, 2)}σ)
                          </td>
                          <td className="py-1 px-1.5 text-right text-sky-600 dark:text-sky-400">
                            {pct(row.shares?.imports?.share ?? 0)}
                          </td>
                          <td className="py-1 px-1.5 text-right font-bold text-teal-600 dark:text-teal-400">
                            {pct(row.shares?.hydro?.share ?? 0)}
                          </td>
                          <td className="py-1 px-1.5 text-right">{pct(row.shares?.other?.share ?? 0)}</td>
                          <td className="py-1 px-1.5 text-right">{pct(row.shares?.consumption?.share ?? 0)}</td>
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
              <SqlEnginePanel files={files} sqlData={data.sql} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/* ============================================================================
   Wind & Day-Ahead Spot Price
   ============================================================================ */
export const PriceWindView: React.FC<ViewProps> = ({ data, onSelectChapter }) => {
  const [lens, setLens] = useState<LensMode>('visual');
  const pw = data.priceWind;
  const bins: any[] = pw?.by_wind_bin || [];
  const capYears: any[] = pw?.capture_by_year || [];

  const slopeGw = pw?.per_gw?.eur_per_gw;
  const lowBin = bins[0];
  const highBin = bins.find((b: any) => b.gw_from === 5) || bins[bins.length - 1];
  const latestCap = capYears[capYears.length - 1] || capYears[0];
  const capRatioPct = latestCap ? Math.round(Number(latestCap.ratio) * 100) : '–';

  const binLabel = (b: any) => (b.gw_to == null ? `${b.gw_from}+ GW` : `${b.gw_from}–${b.gw_to} GW`);

  const files: CodeFileSpec[] = [
    {
      label: 'SQL Panel',
      filePath: 'sql/analysis/29_price_wind_panel.sql',
    },
    {
      label: 'Python Market Engine',
      filePath: 'src/price_wind.py',
    },
  ];

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-xl glass-card">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-amber-600 dark:text-amber-400">
            Merit-Order Cannibalization · ENTSO-E Spot Market ({fmt(pw?.hours, 0)} Hours)
          </div>
          <h1 className="font-display text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            What +1 GW of Wind Does to Finland&apos;s Electricity Price
          </h1>
        </div>
        <LensBar
          lens={lens}
          setLens={setLens}
          visualLabel="Visual Pulse"
          matrixLabel="Bins, Water & Capture Matrix"
          sqlLabel="SQL & Engine"
        />
      </div>

      {/* KPI Strip */}
      <div className="shrink-0 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Each +1 GW of Wind</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-sky-600 dark:text-sky-400 leading-tight">
            −{fmt(slopeGw, 1)} €/MWh
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            95% CI −{fmt(pw?.per_gw?.ci_low, 1)} to −{fmt(pw?.per_gw?.ci_high, 1)} €/MWh
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-warning">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Calm (0–1 GW) vs Windy (5–6 GW)</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-amber-600 dark:text-amber-400 leading-tight">
            {fmt(lowBin?.median, 0)} → {fmt(highBin?.median, 1)} €
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Median spot price · {highBin ? pct(highBin.share_zero_or_below) : '–'} ≤ 0 €/MWh
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Wind Value Capture ({latestCap?.year ?? '–'})</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-emerald-600 dark:text-emerald-400 leading-tight">
            {capRatioPct}% of avg
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Wind earns {fmt(latestCap?.wind_captured, 1)} vs {fmt(latestCap?.average, 1)} €/MWh time-avg
          </div>
        </div>
      </div>

      {/* Main Split Body */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        {/* Left Column */}
        <div className="lg:col-span-4 flex flex-col justify-between p-4 rounded-xl glass-card min-h-0 overflow-y-auto thin-scroll">
          <div className="space-y-2.5">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              3-Second Market Verdict
            </div>
            <h2 className="font-display text-sm sm:text-base font-bold text-slate-900 dark:text-white leading-snug">
              Wind farms bid near 0 €/MWh, pushing expensive thermal fuels off the merit order and cannibalizing their own revenue.
            </h2>
            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
              Above 5 GW of forecast wind, imported hydro and domestic CHP are already backed down, electric district-heating boilers are saturated, and {highBin ? pct(highBin.share_zero_or_below) : '–'} of hours clear at <strong>zero or negative prices</strong>.
            </p>

            <div className="p-3 rounded-lg glass-well space-y-1">
              <div className="text-[10px] font-mono uppercase tracking-wider text-amber-600 dark:text-amber-400 font-semibold">
                Reservoir Storage Interaction (p = {fmt(pw?.storage_interaction?.p_value, 3)})
              </div>
              <p className="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
                At full reservoirs (90th percentile), each GW of wind depresses day-ahead price by <strong className="font-mono">−{fmt(pw?.at_storage?.[2]?.eur_per_gw, 1)} €/MWh</strong> vs <strong className="font-mono">−{fmt(pw?.at_storage?.[0]?.eur_per_gw, 1)} €/MWh</strong> when reservoirs are dry (10th percentile).
              </p>
            </div>
          </div>

          <div className="pt-2.5 border-t border-slate-200/70 dark:border-white/10 text-[11px] font-mono text-slate-500 dark:text-slate-400 space-y-1.5 shrink-0">
            <div className="flex items-center justify-between">
              <span>Demand sensitivity (+1 GW load)</span>
              <span className="text-amber-600 dark:text-amber-400 font-semibold">
                +{fmt(pw?.consumption_per_gw?.eur_per_gw, 1)} €/MWh
              </span>
            </div>
            <button
              type="button"
              onClick={() => onSelectChapter('europe')}
              className="w-full flex items-center justify-between text-left text-sky-600 dark:text-sky-400 hover:underline cursor-pointer"
            >
              <span>How Finland&apos;s price compares with the rest of Europe</span>
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>

        {/* Right Lens Deck */}
        <div className="lg:col-span-8 flex flex-col min-h-0 rounded-xl glass-card p-4 overflow-hidden">
          {lens === 'visual' && (
            <div key="visual" className="lens-enter h-full flex flex-col justify-between min-h-0 overflow-hidden">
              <div className="flex-none flex flex-wrap items-center justify-between gap-2 mb-1">
                <span className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                  Day-Ahead Spot Price (€/MWh) Across Forecast Wind GW Bins
                </span>
                <span className="text-[11px] font-mono text-slate-400">
                  Median (solid) · 25th–75th percentile band
                </span>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                <SvgLineChart
                  ariaLabel="Day-ahead spot price by wind power bin"
                  labels={bins.map(binLabel)}
                  referenceLines={[
                    ...(latestCap?.average != null
                      ? [
                          {
                            y: Number(latestCap.average),
                            label: `time-avg ${fmt(latestCap.average, 0)} €/MWh`,
                            color: 'var(--syn)',
                            dash: '4 3',
                            position: 'left' as const,
                          },
                        ]
                      : []),
                    {
                      y: 0,
                      label: '0 €/MWh floor',
                      color: 'var(--fault)',
                      dash: '3 3',
                      position: 'left',
                    },
                  ]}
                  series={[
                    {
                      name: '75th percentile',
                      short: 'P75',
                      color: '#64748b',
                      width: 1.4,
                      dash: '3 3',
                      values: bins.map((b: any) => Number(b.p75)),
                    },
                    {
                      name: 'Median price (P50)',
                      short: 'Median',
                      color: '#38bdf8',
                      width: 2.5,
                      values: bins.map((b: any) => Number(b.median)),
                    },
                    {
                      name: 'Mean price',
                      short: 'Mean',
                      color: '#f59e0b',
                      width: 1.8,
                      dash: '5 3',
                      values: bins.map((b: any) => Number(b.mean)),
                    },
                    {
                      name: '25th percentile',
                      short: 'P25',
                      color: '#2dd4bf',
                      width: 1.4,
                      dash: '3 3',
                      values: bins.map((b: any) => Number(b.p25)),
                    },
                  ]}
                  height={215}
                  forceZero={true}
                  directLabels={true}
                  xTick={(_i, l) => l}
                  yFmt={(v: number) => fmt(v, 0) + ' €'}
                />
              </div>
            </div>
          )}

          {lens === 'matrix' && (
            <div key="matrix" className="lens-enter h-full overflow-y-auto thin-scroll pr-1 space-y-4">
              <div>
                <div className="text-xs font-semibold text-slate-900 dark:text-white mb-2">
                  Spot Price Distribution by Forecast Wind Generation Bin
                </div>
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-800 text-[10px] font-mono uppercase text-slate-400">
                      <th className="py-1.5 px-2">Wind Bin</th>
                      <th className="py-1.5 px-2 text-right">Hours</th>
                      <th className="py-1.5 px-2 text-right">Median (P50)</th>
                      <th className="py-1.5 px-2 text-right">P25 – P75</th>
                      <th className="py-1.5 px-2 text-right">Mean</th>
                      <th className="py-1.5 px-2 text-right">≤ 0 €/MWh</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                    {bins.map((b: any) => (
                      <tr
                        key={binLabel(b)}
                        className={`hover:bg-slate-50/80 dark:hover:bg-slate-900/40 ${
                          Number(b.share_zero_or_below) >= 0.1 ? 'telemetry-row-warn' : ''
                        }`}
                      >
                        <td className="py-1.5 px-2 font-sans font-medium text-slate-900 dark:text-white">
                          {binLabel(b)}
                        </td>
                        <td className="py-1.5 px-2 text-right text-slate-500">{fmt(b.hours, 0)}</td>
                        <td className="py-1.5 px-2 text-right font-bold text-sky-600 dark:text-sky-400">
                          {fmt(b.median, 1)} €
                        </td>
                        <td className="py-1.5 px-2 text-right">
                          {fmt(b.p25, 1)} – {fmt(b.p75, 1)} €
                        </td>
                        <td className="py-1.5 px-2 text-right">{fmt(b.mean, 1)} €</td>
                        <td className="py-1.5 px-2 text-right font-semibold text-amber-600 dark:text-amber-400">
                          {fmt(Number(b.share_zero_or_below) * 100, 1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-200 dark:border-slate-800">
                <div>
                  <div className="text-xs font-semibold text-slate-900 dark:text-white mb-1.5">
                    Price Drop per +1 GW Wind by Reservoir Storage
                  </div>
                  <table className="w-full text-left border-collapse text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-800 text-[10px] font-mono uppercase text-slate-400">
                        <th className="py-1 px-1.5">Storage Level</th>
                        <th className="py-1 px-1.5 text-right">+1 GW Wind Effect</th>
                        <th className="py-1 px-1.5 text-right">95% CI</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                      {(pw?.at_storage || []).map((r: any) => (
                        <tr key={r.percentile}>
                          <td className="py-1 px-1.5 font-sans font-medium text-slate-900 dark:text-white">
                            P{r.percentile} ({fmt(r.storage_z, 2)}σ)
                          </td>
                          <td className="py-1 px-1.5 text-right font-bold text-sky-600 dark:text-sky-400">
                            −{fmt(r.eur_per_gw, 1)} €
                          </td>
                          <td className="py-1 px-1.5 text-right text-slate-500">
                            −{fmt(r.ci_low, 1)} to −{fmt(r.ci_high, 1)} €
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div>
                  <div className="text-xs font-semibold text-slate-900 dark:text-white mb-1.5">
                    Annual Wind Capture Price vs Market Average
                  </div>
                  <table className="w-full text-left border-collapse text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-800 text-[10px] font-mono uppercase text-slate-400">
                        <th className="py-1 px-1.5">Year</th>
                        <th className="py-1 px-1.5 text-right">Time-Avg</th>
                        <th className="py-1 px-1.5 text-right">Wind-Earned</th>
                        <th className="py-1 px-1.5 text-right">Capture</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/60 dark:divide-slate-800/60 font-mono">
                      {capYears.map((y: any) => (
                        <tr key={y.year}>
                          <td className="py-1 px-1.5 font-sans font-medium text-slate-900 dark:text-white">{y.year}</td>
                          <td className="py-1 px-1.5 text-right">{fmt(y.average, 1)} €</td>
                          <td className="py-1 px-1.5 text-right text-sky-600 dark:text-sky-400">
                            {fmt(y.wind_captured, 1)} €
                          </td>
                          <td className="py-1 px-1.5 text-right font-bold text-emerald-600 dark:text-emerald-400">
                            {fmt(Number(y.ratio) * 100, 0)}%
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
              <SqlEnginePanel files={files} sqlData={data.sql} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/* ============================================================================
   Engineering & SQL Warehouse Craft
   ============================================================================ */
export const EngineeringView: React.FC<ViewProps> = ({ data }) => {
  const [lens, setLens] = useState<LensMode>('visual');
  const eng = data.engineering;
  const parts: any[] = eng?.partitioning?.partitions || [];
  const totalRows = eng?.partitioning?.total_rows;

  const [mode, setMode] = useState<'single' | 'full'>('single');
  const [selectedPart, setSelectedPart] = useState<string>(() => {
    const def =
      parts.find((p) => p.partition === 'fingrid_observation_2026_09') ||
      parts.find((p) => p.rows > 0) ||
      parts[0];
    return def ? def.partition : '';
  });
  const [copiedCmd, setCopiedCmd] = useState(false);

  const activePartObj = parts.find((p) => p.partition === selectedPart) || parts[0];

  const scannedParts = mode === 'full' ? parts.length : 1;
  const scannedRows = mode === 'full' ? totalRows : Number(activePartObj?.rows) || 0;
  const prunedPct = totalRows > 0 ? ((totalRows - scannedRows) / totalRows) * 100 : 0;

  const bm = eng?.benchmark || {};
  const execMs = mode === 'full' ? bm.no_index_ms : bm.partitioned_ms;

  const testLayers = Object.entries(eng?.tests?.by_layer || {});

  const setupCmd = `git clone https://github.com/miladgk/industrial-energy-sql-pipeline.git
cd industrial-energy-sql-pipeline
cp config_template.yaml config.yaml
pip install -r requirements.txt
docker compose up -d
make db-setup snapshot-restore quality-checks
make api        # http://localhost:8000/docs
make test`;

  const handleCopyCmd = async () => {
    try {
      await navigator.clipboard.writeText(setupCmd);
      setCopiedCmd(true);
      setTimeout(() => setCopiedCmd(false), 1800);
    } catch {
      setCopiedCmd(false);
    }
  };

  const sqlFiles: CodeFileSpec[] = (data.sql?.files || []).slice(0, 6).map((f: any) => ({
    label: f.path.split('/').pop() || f.path,
    filePath: f.path,
  }));

  return (
    <div className="h-full flex flex-col gap-2.5 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-xl glass-card">
        <div className="min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-600 dark:text-sky-400">
            PostgreSQL Declarative RANGE Partitioning · Star Schema &amp; CI Benchmarks
          </div>
          <h1 className="font-display text-lg sm:text-xl font-bold text-slate-900 dark:text-white tracking-tight truncate">
            Inside the SQL Warehouse: Partition Pruning, Index Benchmarks &amp; {eng?.tests?.total ?? '–'} CI Tests
          </h1>
        </div>
        <LensBar
          lens={lens}
          setLens={setLens}
          visualLabel="Partition Pruning Lab"
          matrixLabel="Index Benchmarks & CI Suite"
          sqlLabel="SQL Warehouse & Local CLI"
        />
      </div>

      {/* KPI Strip */}
      <div className="shrink-0 grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Fact Table Rows</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-sky-600 dark:text-sky-400 leading-tight">
            {fmt(totalRows, 0)}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Across {parts.length} monthly RANGE partitions
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Index &amp; Pruning Speedup</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-emerald-600 dark:text-emerald-400 leading-tight">
            {fmt(bm.speedup_index_vs_none, 1)}× faster
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            {fmt(bm.partitioned_ms, 2)} ms pruned vs {fmt(bm.no_index_ms, 2)} ms seq scan
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-signal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Star Schema Grain</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-teal-600 dark:text-teal-400 leading-tight">
            (dataset_id, ts)
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            {eng?.datasets ?? '–'} live Fingrid &amp; weather streams
          </div>
        </div>
        <div className="px-3.5 py-2 rounded-xl glass-kpi telemetry-nominal">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">Automated Verification</div>
          <div className="font-display text-lg sm:text-xl font-bold font-mono tabular-nums text-slate-900 dark:text-white leading-tight">
            {eng?.tests?.total ?? '–'} CI tests
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            {eng?.tests?.ci_matrix ?? '–'}
          </div>
        </div>
      </div>

      {/* Main Workspace */}
      <div className="flex-1 min-h-0 rounded-xl glass-card p-4 overflow-hidden flex flex-col">
        {lens === 'visual' && (
          <div key="visual" className="lens-enter h-full grid grid-cols-1 lg:grid-cols-12 gap-4 min-h-0">
            {/* Left Partition Simulator Controls */}
            <div className="lg:col-span-5 flex flex-col justify-between space-y-2.5 overflow-y-auto thin-scroll pr-1">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-sky-600 dark:text-sky-400">
                    Interactive PostgreSQL Planner Lab
                  </span>
                  <div className="flex items-center gap-1 p-0.5 rounded-lg glass-well">
                    <button
                      type="button"
                      onClick={() => setMode('single')}
                      className={`px-2.5 py-1 text-[11px] font-mono rounded-md cursor-pointer ${
                        mode === 'single'
                          ? 'bg-sky-500 text-slate-950 font-semibold'
                          : 'text-slate-600 dark:text-slate-400'
                      }`}
                    >
                      1-Month Filter
                    </button>
                    <button
                      type="button"
                      onClick={() => setMode('full')}
                      className={`px-2.5 py-1 text-[11px] font-mono rounded-md cursor-pointer ${
                        mode === 'full'
                          ? 'bg-amber-500 text-slate-950 font-semibold'
                          : 'text-slate-600 dark:text-slate-400'
                      }`}
                    >
                      No Time Filter
                    </button>
                  </div>
                </div>

                <h2 className="font-display text-sm sm:text-base font-bold text-slate-900 dark:text-white">
                  Click any monthly child table on the right to inspect how PostgreSQL prunes {fmt(prunedPct, 1)}% of the warehouse at plan time.
                </h2>

                <div className="grid grid-cols-2 gap-2">
                  <div className="p-2 rounded-lg glass-well">
                    <div className="text-[10px] font-mono uppercase text-slate-400">Partitions Scanned</div>
                    <div className="text-base font-bold font-mono text-sky-600 dark:text-sky-400">
                      {scannedParts} / {parts.length}
                    </div>
                  </div>
                  <div className="p-2 rounded-lg glass-well">
                    <div className="text-[10px] font-mono uppercase text-slate-400">Rows Read</div>
                    <div className="text-base font-bold font-mono text-slate-900 dark:text-white">
                      {fmt(scannedRows, 0)}
                    </div>
                  </div>
                  <div className="p-2 rounded-lg glass-well">
                    <div className="text-[10px] font-mono uppercase text-slate-400">Rows Pruned</div>
                    <div className="text-base font-bold font-mono text-emerald-600 dark:text-emerald-400">
                      {fmt(prunedPct, 1)}% skipped
                    </div>
                  </div>
                  <div className="p-2 rounded-lg glass-well">
                    <div className="text-[10px] font-mono uppercase text-slate-400">EXPLAIN ANALYZE</div>
                    <div className="text-base font-bold font-mono text-amber-600 dark:text-amber-400">
                      {fmt(execMs, 2)} ms
                    </div>
                  </div>
                </div>
              </div>

              <pre className="p-2.5 rounded-lg glass-well text-slate-800 dark:text-slate-100 font-mono text-[10.5px] leading-relaxed overflow-x-auto">
                {mode === 'single'
                  ? `EXPLAIN (ANALYZE, BUFFERS)
SELECT dataset_id, AVG(value)
FROM fingrid_observation
WHERE start_time >= '2026-09-01' AND start_time < '2026-10-01'
GROUP BY dataset_id;
-- Index Scan on ${activePartObj?.partition}
-- Subplans Removed: ${parts.length - 1} (${fmt(prunedPct, 1)}% pruned)`
                  : `EXPLAIN (ANALYZE, BUFFERS)
SELECT dataset_id, AVG(value)
FROM fingrid_observation
GROUP BY dataset_id;
-- Parallel Append across all ${parts.length} partitions
-- Execution Time: ${fmt(execMs, 2)} ms`}
              </pre>
            </div>

            {/* Right 40-Partition Interactive Grid */}
            <div className="lg:col-span-7 flex flex-col min-h-0 pl-1 gap-2">
              <div className="shrink-0 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-900 dark:text-white">
                  {parts.length} Monthly Child Tables (`fingrid_observation_YYYY_MM`)
                </span>
                <span className="text-[11px] font-mono text-slate-400">
                  {mode === 'single' ? `1 active · ${parts.length - 1} pruned by planner` : `All ${parts.length} scanned`}
                </span>
              </div>
              <div className="flex-1 min-h-0 grid grid-cols-5 sm:grid-cols-8 auto-rows-fr gap-1.5 overflow-y-auto thin-scroll pr-0.5">
                {(() => {
                  const maxRows = Math.max(1, ...parts.map((x) => Number(x.rows) || 0));
                  return parts.map((p) => {
                    const isActive = mode === 'full' || p.partition === activePartObj?.partition;
                    const shortLabel = p.partition
                      .replace('fingrid_observation_', '')
                      .replace('_', '-');
                    const fillPct = Math.round(((Number(p.rows) || 0) / maxRows) * 100);
                    return (
                      <button
                        key={p.partition}
                        type="button"
                        onClick={() => {
                          setMode('single');
                          setSelectedPart(p.partition);
                        }}
                        className={`flex flex-col justify-between p-2 rounded-lg border text-left transition-all cursor-pointer min-h-0 ${
                          isActive
                            ? 'bg-sky-500/20 border-sky-400/70 text-slate-900 dark:text-white shadow-sm'
                            : 'glass-well text-slate-400 dark:text-slate-500 opacity-70 hover:opacity-100'
                        }`}
                      >
                        <div className="font-mono text-[10.5px] font-bold truncate">{shortLabel}</div>
                        <div className="space-y-1 mt-1">
                          <div className="font-mono text-[9.5px] truncate">{fmt((p.rows || 0) / 1000, 0)}k</div>
                          <div className="h-1 w-full rounded-full bg-slate-200/70 dark:bg-white/10 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                isActive ? 'bg-sky-400' : 'bg-slate-400/50 dark:bg-slate-500/50'
                              }`}
                              style={{ width: `${Math.max(fillPct > 0 ? 8 : 0, fillPct)}%` }}
                            />
                          </div>
                        </div>
                      </button>
                    );
                  });
                })()}
              </div>
              <div className="shrink-0 pt-2 border-t border-slate-200/70 dark:border-white/10 flex items-center justify-between text-[11px] font-mono text-slate-500">
                <span>Selected: {activePartObj?.partition}</span>
                <span>{fmt(activePartObj?.rows, 0)} rows</span>
              </div>
            </div>
          </div>
        )}

        {lens === 'matrix' && (
          <div key="matrix" className="lens-enter h-full grid grid-cols-1 lg:grid-cols-12 gap-4 min-h-0 overflow-y-auto thin-scroll">
            <div className="lg:col-span-6 space-y-3">
              <div className="text-xs font-semibold text-slate-900 dark:text-white">
                Warm Benchmark: {bm.query || '1 week of 1-minute grid frequency'}
              </div>
              <div className="space-y-2.5">
                {[
                  {
                    label: 'Sequential Scan (No Index / No Partitioning)',
                    ms: Number(bm.no_index_ms) || 0,
                    note: `${fmt(bm.rows_discarded_without_index)} rows filtered after disk read`,
                    color: 'bg-rose-500',
                  },
                  {
                    label: 'Composite B-Tree Index `(dataset_id, start_time)`',
                    ms: Number(bm.indexed_ms) || 0,
                    note: 'Index Only Scan across monolithic table',
                    color: 'bg-sky-500',
                  },
                  {
                    label: 'Declarative Monthly Partitioning + Composite Index',
                    ms: Number(bm.partitioned_ms) || 0,
                    note: `Scans only ${bm.partitions_read?.[0] || 'fingrid_observation_2026_09'} (23.3× speedup)`,
                    color: 'bg-emerald-500',
                  },
                ].map((item) => {
                  const maxMs = Number(bm.no_index_ms) || 1;
                  const wPct = Math.max(5, Math.min(100, (item.ms / maxMs) * 100));
                  return (
                    <div
                      key={item.label}
                      className="p-3 rounded-lg glass-well"
                    >
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="font-medium text-slate-900 dark:text-white">{item.label}</span>
                        <span className="font-mono font-bold text-sky-600 dark:text-sky-400">{fmt(item.ms, 2)} ms</span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                        <div className={`h-full ${item.color} rounded-full`} style={{ width: `${wPct}%` }} />
                      </div>
                      <div className="text-[10.5px] font-mono text-slate-400 mt-1">{item.note}</div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="lg:col-span-6 space-y-3">
              <div className="text-xs font-semibold text-slate-900 dark:text-white">
                Automated Pytest Verification Matrix ({eng?.tests?.total ?? '–'} Tests Across {Object.keys(eng?.tests?.by_layer || {}).length || '–'} Layers)
              </div>
              <div className="grid grid-cols-2 gap-2">
                {testLayers.map(([layer, count]: [string, any]) => (
                  <div
                    key={layer}
                    className="p-2.5 rounded-lg glass-well flex items-center justify-between"
                  >
                    <span className="text-xs font-medium capitalize text-slate-800 dark:text-slate-200">{layer} tests</span>
                    <span className="font-mono text-xs font-bold text-emerald-600 dark:text-emerald-400">
                      {count} PASS
                    </span>
                  </div>
                ))}
              </div>
              <div className="p-3 rounded-lg glass-well text-xs space-y-1">
                <div className="font-mono text-[11px] text-sky-600 dark:text-sky-400 font-semibold">
                  CI Matrix &amp; Load Testing
                </div>
                <div className="text-slate-600 dark:text-slate-300">
                  Matrix: <span className="font-mono">{eng?.tests?.ci_matrix}</span>
                </div>
                <div className="text-slate-600 dark:text-slate-300">
                  Load suite: <span className="font-mono">{eng?.tests?.load_test}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {lens === 'sql' && (
          <div key="sql" className="lens-enter h-full grid grid-cols-1 lg:grid-cols-12 gap-4 min-h-0">
            <div className="lg:col-span-5 flex flex-col justify-between p-4 rounded-xl glass-well">
              <div className="space-y-3">
                <div className="text-[10px] font-mono uppercase tracking-widest text-sky-600 dark:text-sky-400">
                  Reproducible Docker + PostgreSQL Stack
                </div>
                <h3 className="font-display text-base font-bold text-slate-900 dark:text-white">
                  Run the Entire Warehouse &amp; Every Panel Locally
                </h3>
                <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                  Every chart and statistical table in this cockpit is built deterministically from Fingrid Open Data, Open-Meteo archives, SYKE hydrology, NVE reservoirs, ENTSO-E spot prices, Ember and Traficom.
                </p>
                <div className="relative">
                  <pre className="p-3 rounded-lg bg-slate-950 text-sky-300 font-mono text-[11px] leading-relaxed border border-slate-800 overflow-x-auto">
                    <code>{setupCmd}</code>
                  </pre>
                  <button
                    type="button"
                    onClick={handleCopyCmd}
                    className="absolute top-2 right-2 inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[10px] font-mono cursor-pointer"
                  >
                    {copiedCmd ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    {copiedCmd ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>
              <div className="text-[11px] font-mono text-slate-500">
                PostgreSQL 15 in Docker (CI: 14–16) · Python 3.11 · No proprietary dependencies
              </div>
            </div>

            <div className="lg:col-span-7 flex flex-col min-h-0">
              <SqlEnginePanel
                files={
                  sqlFiles.length > 0
                    ? sqlFiles
                    : [
                        {
                          label: 'Wind Balance SQL',
                          filePath: 'sql/analysis/24_wind_allocation_panel.sql',
                        },
                      ]
                }
                sqlData={data.sql}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
