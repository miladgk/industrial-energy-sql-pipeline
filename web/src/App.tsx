/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useState } from 'react';
import { loadAllObservatoryData, loadLatestFingrid, LatestFingrid, ObservatoryData, fmt } from './dataLoader';
import { OverviewView, ChapterId } from './views/OverviewView';
import { ForecastsView, RangesView, WeatherModelView } from './views/ForecastingViews';
import { Co2View, EventsView, ColdView, StrikesView } from './views/CarbonClimateViews';
import { WindBalanceView, PriceWindView, EngineeringView } from './views/MarketWarehouseViews';
import { EuropeView, EvChargingView } from './views/EuropeCarsViews';
import { LiveTicker } from './components/LiveTicker';
import { Sun, Moon, Github, AlertCircle, Search } from 'lucide-react';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import { CommandPalette } from './components/CommandPalette';

export interface ChapterMeta {
  id: ChapterId;
  group: string;
  label: string;
  shortTitle: string;
  metricBadge: (d: ObservatoryData) => string;
}

export const CHAPTERS: ChapterMeta[] = [
  {
    id: 'overview',
    group: 'Command Center',
    label: 'Executive Overview',
    shortTitle: 'Overview',
    metricBadge: (d) => (d.engineering?.datasets ? `${d.engineering.datasets} sets` : '–'),
  },
  {
    id: 'forecasts',
    group: 'Forecasting',
    label: 'Forecasts vs. Reality',
    shortTitle: 'Forecasts',
    metricBadge: (d) => {
      const w = (d.scorecard?.summary || []).find(
        (s: any) => s.variable === 'wind' && s.product === 'day_ahead'
      );
      return w ? `${fmt(Math.round(w.mae_mw))} MW` : '–';
    },
  },
  {
    id: 'ranges',
    group: 'Forecasting',
    label: "Tomorrow's Ranges",
    shortTitle: 'Ranges',
    metricBadge: (d) => {
      const w = d.ranges?.wind?.mean_width80_mw;
      return w ? `±${fmt(Math.round(w / 2))} MW` : '–';
    },
  },
  {
    id: 'model',
    group: 'Forecasting',
    label: 'Public Data vs. Fingrid',
    shortTitle: 'Weather ML',
    metricBadge: (d) => {
      const m = d.weatherModel?.wind?.backtest?.mae_mw?.weather;
      return m ? `${fmt(Math.round(m))} MW` : '–';
    },
  },
  {
    id: 'co2',
    group: 'Carbon & Climate',
    label: 'CO₂ Intensity Model',
    shortTitle: 'CO₂ Model',
    metricBadge: (d) => {
      const c = d.co2?.cleanest_hour?.co2;
      return c != null ? `${fmt(c, 1)} g` : '–';
    },
  },
  {
    id: 'cold',
    group: 'Carbon & Climate',
    label: 'Thermodynamics of Cold',
    shortTitle: 'Cold Physics',
    metricBadge: (d) => {
      const wd = d.temperature?.fits?.find((f: any) => f.day_type === 'weekday');
      return wd ? `+${fmt(Math.round(wd.mw_per_degree))} MW/°C` : '–';
    },
  },
  {
    id: 'events',
    group: 'Markets & Grid Physics',
    label: 'Grid Events (50 Hz)',
    shortTitle: 'Grid Events',
    metricBadge: (d) => {
      if (!d.events?.counts) return '–';
      const freqYear =
        (d.events.counts.frequency_low?.year || 0) + (d.events.counts.frequency_high?.year || 0);
      return `${fmt(freqYear, 0)}`;
    },
  },
  {
    id: 'strikes',
    group: 'Markets & Grid Physics',
    label: 'The 2024 Strikes',
    shortTitle: '2024 Strikes',
    metricBadge: (d) => {
      const ev: any[] = d.strikes?.events || [];
      if (!ev.length) return '–';
      const big = ev.reduce((a, e) => (Math.abs(e.gwh) > Math.abs(a.gwh) ? e : a));
      return `${fmt(Math.abs(big.gwh), 0)} GWh`;
    },
  },
  {
    id: 'wind',
    group: 'Markets & Grid Physics',
    label: 'Wind Power Balance',
    shortTitle: 'Wind Balance',
    metricBadge: (d) => {
      const s = d.windAlloc?.wind?.imports?.share;
      return s != null ? `${Math.round(Number(s) * 100)}%` : '–';
    },
  },
  {
    id: 'price',
    group: 'Markets & Grid Physics',
    label: 'Wind & Spot Price',
    shortTitle: 'Spot Price',
    metricBadge: (d) => {
      const s = d.priceWind?.per_gw?.eur_per_gw;
      return s != null ? `−${fmt(Number(s), 1)} €` : '–';
    },
  },
  {
    id: 'europe',
    group: 'Markets & Grid Physics',
    label: 'Finland in Europe',
    shortTitle: 'Europe',
    metricBadge: (d) => {
      const rk = d.europe?.finland_rank;
      return rk ? `${rk.price_eur_mwh} of ${rk.of}` : '–';
    },
  },
  {
    id: 'ev',
    group: 'Markets & Grid Physics',
    label: 'Electric Cars',
    shortTitle: 'Electric Cars',
    metricBadge: (d) => {
      const a = d.evCharging?.added_mw?.central;
      return a != null ? `+${fmt(a, 0)} MW` : '–';
    },
  },
  {
    id: 'craft',
    group: 'Warehouse Craft',
    label: 'Engineering & SQL',
    shortTitle: 'SQL Craft',
    metricBadge: (d) => {
      const sp = d.engineering?.benchmark?.speedup_index_vs_none;
      return sp ? `${fmt(Math.round(sp))}×` : '–';
    },
  },
];

const THEME_KEY = 'theme'; // same key as index.html's pre-paint script

/** First and last year with data in the warehouse's monthly partitions, e.g. "2023–2026". */
function warehouseYears(d: ObservatoryData): string | null {
  const parts: any[] = d.engineering?.partitioning?.partitions || [];
  const years = parts
    .filter((p) => Number(p.rows) > 0) // future months are created empty, ahead of time
    .map((p) => /_(\d{4})_\d{2}$/.exec(p.partition || '')?.[1])
    .filter(Boolean) as string[];
  if (!years.length) return null;
  const lo = years.reduce((a, b) => (a < b ? a : b));
  const hi = years.reduce((a, b) => (a > b ? a : b));
  return lo === hi ? lo : `${lo}–${hi}`;
}

export default function App() {
  const [data, setData] = useState<ObservatoryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ChapterId>(() => {
    const hash = window.location.hash.replace('#', '') as ChapterId;
    return CHAPTERS.some((c) => c.id === hash) ? hash : 'overview';
  });
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    document.documentElement.classList.contains('dark') ? 'dark' : 'light'
  );
  const [cmdOpen, setCmdOpen] = useState(false);
  const [latest, setLatest] = useState<LatestFingrid | null>(null);

  const isMac =
    typeof navigator !== 'undefined' &&
    /Mac|iPod|iPhone|iPad/i.test(navigator.platform || navigator.userAgent);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* private mode: the theme still switches, it is just not remembered */
    }
  }, [theme]);

  useEffect(() => {
    loadAllObservatoryData()
      .then((bundle) => setData({ ...bundle, loading: false }))
      .catch((err: any) => setError(err?.message || 'Failed to load observatory datasets.'));
    loadLatestFingrid().then(setLatest);
  }, []);

  useEffect(() => {
    const onHash = () => {
      const hash = window.location.hash.replace('#', '') as ChapterId;
      if (CHAPTERS.some((c) => c.id === hash)) setActiveTab(hash);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCmdOpen((prev) => !prev);
        return;
      }
      if (
        e.key === '/' &&
        !e.metaKey &&
        !e.ctrlKey &&
        !e.altKey &&
        !cmdOpen
      ) {
        const tag = (e.target as HTMLElement | null)?.tagName;
        const isEditable =
          tag === 'INPUT' ||
          tag === 'TEXTAREA' ||
          tag === 'SELECT' ||
          (e.target as HTMLElement | null)?.isContentEditable;
        if (!isEditable) {
          e.preventDefault();
          setCmdOpen(true);
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [cmdOpen]);

  const selectChapter = (id: ChapterId) => {
    setActiveTab(id);
    window.history.replaceState(null, '', `#${id}`);
  };

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6 text-slate-900 dark:text-slate-100">
        <div className="max-w-md w-full p-6 rounded-xl glass-card border-rose-500/30 space-y-3">
          <div className="flex items-center gap-2 text-rose-600 dark:text-rose-400 font-semibold">
            <AlertCircle className="w-5 h-5" />
            <span>Failed to Initialize Observatory Warehouse</span>
          </div>
          <p className="text-xs text-slate-600 dark:text-slate-400 font-mono">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-6 text-slate-900 dark:text-slate-100">
        <div className="w-8 h-8 rounded-full border-2 border-sky-500 border-t-transparent animate-spin mb-3" />
        <div className="font-mono text-xs uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Loading Finland's grid data…
        </div>
      </div>
    );
  }

  const groups = Array.from(new Set(CHAPTERS.map((c) => c.group)));

  return (
    <MotionConfig reducedMotion="user">
    <div className="min-h-screen lg:h-dvh lg:overflow-hidden flex flex-col text-slate-900 dark:text-slate-100 relative z-10">
      {/* Strict 3-Zone Top Bar */}
      <header className="shrink-0 h-11 glass-chrome border-b border-slate-200/80 dark:border-white/10 px-4 flex items-center justify-between gap-4 z-30">
        {/* Zone 1: Brand & Archive Identity */}
        <div className="flex items-center gap-2.5 min-w-0">
          <button
            type="button"
            onClick={() => selectChapter('overview')}
            className="flex items-center gap-2 text-left group cursor-pointer"
          >
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-sky-400 to-sky-600 flex items-center justify-center text-slate-950 font-mono font-bold text-xs shadow-sm">
              FI
            </div>
            <div className="truncate hidden sm:block">
              <span className="font-display font-bold text-xs sm:text-sm tracking-tight text-slate-900 dark:text-white group-hover:text-sky-600 dark:group-hover:text-sky-400 transition-colors">
                Grid in SQL
              </span>
              <span className="hidden md:inline text-slate-400 dark:text-slate-500 text-xs ml-2 font-mono">
                Finland&apos;s Living Energy Observatory
              </span>
            </div>
          </button>
        </div>

        {/* Zone 2: Horizontal Mobile/Tablet Quick Switcher */}
        <div className="flex lg:hidden items-center gap-1 overflow-x-auto no-scrollbar py-1 max-w-full">
          {CHAPTERS.map((c) => {
            const active = c.id === activeTab;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => selectChapter(c.id)}
                className={`px-2.5 py-1 rounded-md text-xs font-mono whitespace-nowrap transition-colors cursor-pointer ${
                  active
                    ? 'bg-sky-500 text-slate-950 font-semibold'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
              >
                {c.shortTitle}
              </button>
            );
          })}
        </div>

        {/* Zone 3: Warehouse Telemetry, Command Palette & Theme Toggle */}
        <div className="flex items-center gap-2.5 shrink-0">
          <LiveTicker latest={latest} />

          <div className="hidden xl:flex items-center gap-2 text-[11px] font-mono text-slate-500 dark:text-slate-400">
            <span>PostgreSQL</span>
            <span className="text-slate-300 dark:text-slate-700">·</span>
            <span className="tabular-nums" id="header-rows">
              {fmt(data.engineering?.partitioning?.total_rows, 0)} rows
            </span>
            {warehouseYears(data) && (
              <>
                <span className="text-slate-300 dark:text-slate-700">·</span>
                <span className="tabular-nums">{warehouseYears(data)}</span>
              </>
            )}
          </div>

          <button
            type="button"
            onClick={() => setCmdOpen(true)}
            className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg glass-well text-[11px] font-mono text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors whitespace-nowrap shrink-0 cursor-pointer"
            title="Quick jump to any chapter or action (Cmd/Ctrl + K)"
            aria-label="Open quick jump command palette"
          >
            <Search className="w-3.5 h-3.5 text-sky-600 dark:text-sky-400" />
            <span className="hidden md:inline">Quick jump</span>
            <kbd className="hidden sm:inline text-[10px] text-slate-400 dark:text-slate-500 pl-0.5">
              {isMac ? '⌘K' : 'Ctrl K'}
            </kbd>
          </button>

          <a
            href="https://github.com/miladgk/industrial-energy-sql-pipeline"
            target="_blank"
            rel="noreferrer"
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/10 transition-colors shrink-0"
            title="View SQL & Python repository on GitHub"
          >
            <Github className="w-4 h-4" />
          </a>

          <button
            type="button"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/10 transition-colors cursor-pointer shrink-0"
            aria-label="Toggle color theme"
            title={theme === 'dark' ? 'Switch to Daylight Paper theme' : 'Switch to Obsidian & Aurora theme'}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </header>

      {/* Main Spatial Cockpit Shell */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left Dispatch Rail (Desktop) */}
        <aside className="hidden lg:flex w-60 shrink-0 flex-col justify-between border-r border-slate-200/80 dark:border-white/10 glass-chrome p-2.5 select-none">
          <nav className="space-y-2.5 overflow-y-auto thin-scroll pr-0.5" aria-label="Observatory analytical chapters">
            {groups.map((grp) => (
              <div key={grp}>
                <div className="px-2.5 mb-0.5 text-[10px] font-mono uppercase tracking-wider text-slate-400 dark:text-slate-500">
                  {grp}
                </div>
                <div className="space-y-0.5">
                  {CHAPTERS.filter((c) => c.group === grp).map((ch) => {
                    const active = ch.id === activeTab;
                    return (
                      <button
                        key={ch.id}
                        type="button"
                        onClick={() => selectChapter(ch.id)}
                        className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left transition-all cursor-pointer ${
                          active
                            ? 'bg-gradient-to-r from-sky-500/25 to-sky-500/10 text-sky-700 dark:text-sky-300 font-semibold border border-sky-400/35 shadow-[0_4px_14px_-4px_rgba(56,189,248,0.35),inset_0_1px_0_rgba(255,255,255,0.2)]'
                            : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100/70 dark:hover:bg-white/5 border border-transparent'
                        }`}
                      >
                        <span className="text-xs truncate pr-2">{ch.label}</span>
                        <span
                          className={`text-[10px] font-mono tabular-nums shrink-0 ${
                            active ? 'text-sky-700 dark:text-sky-300 font-semibold' : 'text-slate-400 dark:text-slate-500'
                          }`}
                        >
                          {ch.metricBadge(data)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>

          {/* Compact Grid Physics Card */}
          <div className="pt-2 border-t border-slate-200/80 dark:border-white/10">
            <div className="p-2 rounded-lg glass-well space-y-0.5">
              <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 dark:text-slate-400">
                <span>NOMINAL GRID</span>
                <span className="text-emerald-600 dark:text-emerald-400 font-semibold">50.00 Hz · FI</span>
              </div>
              <div className="text-[10px] text-slate-500 dark:text-slate-400 leading-tight">
                Fingrid · Open-Meteo · SYKE · NVE · ENTSO-E · Ember · Traficom
              </div>
            </div>
          </div>
        </aside>

        {/* Zero-Scroll 100vh Primary Instrument Stage */}
        <main className="flex-1 min-h-0 p-2.5 sm:p-3 flex flex-col justify-between overflow-y-auto lg:overflow-hidden">
          <div className="flex-1 min-h-0 overflow-hidden relative">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                className="h-full min-h-0"
              >
                {activeTab === 'overview' && <OverviewView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'forecasts' && <ForecastsView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'ranges' && <RangesView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'model' && <WeatherModelView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'co2' && <Co2View data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'cold' && <ColdView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'events' && <EventsView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'strikes' && <StrikesView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'wind' && <WindBalanceView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'price' && <PriceWindView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'europe' && <EuropeView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'ev' && <EvChargingView data={data} onSelectChapter={selectChapter} />}
                {activeTab === 'craft' && <EngineeringView data={data} onSelectChapter={selectChapter} />}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Ultra-Compact Single-Line Attribution Bar */}
          <footer className="shrink-0 pt-1.5 mt-1.5 border-t border-slate-200/60 dark:border-white/10 flex flex-wrap items-center justify-between gap-2 text-[10px] font-mono text-slate-400 dark:text-slate-500">
            <div>
              Fingrid Open Data (CC BY 4.0) · Open-Meteo · SYKE · NVE · ENTSO-E · Ember (CC BY 4.0) · Traficom (CC BY 4.0)
            </div>
            <div>
              Static page · every number read from docs/data, refreshed daily
            </div>
          </footer>
        </main>
      </div>

      <CommandPalette
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        chapters={CHAPTERS}
        activeTab={activeTab}
        data={data}
        theme={theme}
        onSelectChapter={selectChapter}
        onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      />
    </div>
    </MotionConfig>
  );
}
