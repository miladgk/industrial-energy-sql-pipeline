import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  Search,
  ArrowRight,
  Sun,
  Moon,
  Terminal,
  Compass,
  Check,
} from 'lucide-react';
import { ObservatoryData } from '../dataLoader';
import { ChapterId } from '../views/OverviewView';
import type { ChapterMeta } from '../App';

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  chapters: ChapterMeta[];
  activeTab: ChapterId;
  data: ObservatoryData;
  theme: 'light' | 'dark';
  onSelectChapter: (id: ChapterId) => void;
  onToggleTheme: () => void;
}

const CHAPTER_KEYWORDS: Record<ChapterId, { hint: string; keywords: string }> = {
  overview: {
    hint: '6-chamber 100vh bento cockpit & tomorrow pulse',
    keywords: 'home cockpit summary dashboard bento tomorrow past year',
  },
  forecasts: {
    hint: 'Day-ahead vs intraday MAE & mFRR balancing absorption',
    keywords: 'wind consumption scorecard error bias mfrr balancing surprise',
  },
  ranges: {
    hint: '80% & 95% adaptive conformal prediction intervals',
    keywords: 'uncertainty conformal intervals winkler backtest coverage',
  },
  model: {
    hint: 'Open-Meteo weather benchmark vs Fingrid + Diebold-Mariano',
    keywords: 'weather ml ridge holidays lead time decay open-meteo',
  },
  co2: {
    hint: '60-day rolling SQL regression & cleanest EV hours',
    keywords: 'carbon co2 intensity regr_slope regression cleanest ev charging',
  },
  cold: {
    hint: 'Heating threshold & piecewise MW-per-°C demand curve',
    keywords: 'temperature arctic cold weather freeze heating elasticity',
  },
  events: {
    hint: 'Islands-and-gaps SQL detection & 50 Hz excursions',
    keywords: 'frequency 50hz excursion nuclear drop inertia price spike anomaly',
  },
  strikes: {
    hint: 'March–April 2024 industrial strike counterfactual & placebos',
    keywords: 'strikes counterfactual placebo industrial output gwh',
  },
  wind: {
    hint: 'Cross-border cables, CHP fuel & SYKE/NVE hydro storage',
    keywords: 'allocation balance cables sweden estonia hydro reservoir syke nve',
  },
  price: {
    hint: 'Merit-order cannibalization (€/MWh per GW) & negative prices',
    keywords: 'spot price entso-e negative capture cannibalization merit order',
  },
  europe: {
    hint: "Ember: Finland's price, CO₂ and wind + solar against Europe",
    keywords: 'europe eu ember countries wholesale price carbon intensity rank nuclear hydro',
  },
  ev: {
    hint: 'Traficom fleet vs weather-adjusted consumption growth by hour',
    keywords: 'electric cars ev bev phev charging traficom fleet boilers night evening growth',
  },
  craft: {
    hint: 'PostgreSQL RANGE partition pruning, indexes & the CI test suite',
    keywords: 'sql warehouse partition pruning explain analyze index benchmark ci cli',
  },
};

interface CommandItem {
  id: string;
  section: 'Chapters' | 'Actions';
  title: string;
  subtitle: string;
  badge?: string;
  active?: boolean;
  icon: 'chapter' | 'theme' | 'copy';
  searchText: string;
  perform: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  open,
  onClose,
  chapters,
  activeTab,
  data,
  theme,
  onSelectChapter,
  onToggleTheme,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [copiedCli, setCopiedCli] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIdx(0);
      const t = window.setTimeout(() => inputRef.current?.focus(), 20);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  const items: CommandItem[] = useMemo(() => {
    const chapterItems: CommandItem[] = chapters.map((ch) => {
      const meta = CHAPTER_KEYWORDS[ch.id];
      const badge = ch.metricBadge(data);
      return {
        id: `ch-${ch.id}`,
        section: 'Chapters',
        title: ch.label,
        subtitle: `${ch.group} · ${meta.hint}`,
        badge,
        active: ch.id === activeTab,
        icon: 'chapter',
        searchText: `${ch.label} ${ch.shortTitle} ${ch.group} ${meta.hint} ${meta.keywords} ${badge}`.toLowerCase(),
        perform: () => {
          onSelectChapter(ch.id);
          onClose();
        },
      };
    });

    const actionItems: CommandItem[] = [
      {
        id: 'action-theme',
        section: 'Actions',
        title:
          theme === 'dark'
            ? 'Switch to Daylight Paper theme'
            : 'Switch to Obsidian & Aurora theme',
        subtitle: 'Toggle light and dark observatory contrast palettes',
        badge: theme === 'dark' ? 'Light' : 'Dark',
        icon: 'theme',
        searchText: 'theme dark light daylight obsidian aurora mode appearance',
        perform: () => {
          onToggleTheme();
          onClose();
        },
      },
      {
        id: 'action-copy-cli',
        section: 'Actions',
        title: 'Copy local SQL & Docker setup commands',
        subtitle: 'git clone + docker compose + make snapshot-restore',
        badge: copiedCli ? 'Copied' : 'Clipboard',
        icon: 'copy',
        searchText: 'copy cli docker git clone setup terminal postgres',
        perform: () => {
          const cmd = `git clone https://github.com/miladgk/industrial-energy-sql-pipeline.git\ncd industrial-energy-sql-pipeline\ncp config_template.yaml config.yaml\npip install -r requirements.txt\ndocker compose up -d\nmake db-setup snapshot-restore quality-checks`;
          navigator.clipboard?.writeText(cmd);
          setCopiedCli(true);
          window.setTimeout(() => {
            setCopiedCli(false);
            onClose();
          }, 500);
        },
      },
    ];

    return [...chapterItems, ...actionItems];
  }, [chapters, activeTab, data, theme, copiedCli, onSelectChapter, onToggleTheme, onClose]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    const tokens = q.split(/\s+/).filter(Boolean);
    return items.filter((item) =>
      tokens.every((tok) => item.searchText.includes(tok))
    );
  }, [items, query]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  useEffect(() => {
    if (selectedIdx >= filtered.length && filtered.length > 0) {
      setSelectedIdx(filtered.length - 1);
    }
  }, [filtered.length, selectedIdx]);

  useEffect(() => {
    const activeEl = listRef.current?.querySelector<HTMLElement>(
      `[data-cmd-idx="${selectedIdx}"]`
    );
    activeEl?.scrollIntoView({ block: 'nearest' });
  }, [selectedIdx]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (!filtered.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((prev) => (prev + 1) % filtered.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((prev) => (prev - 1 + filtered.length) % filtered.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      filtered[selectedIdx]?.perform();
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4 bg-slate-950/55 backdrop-blur-xs"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.14 }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
          role="dialog"
          aria-modal="true"
          aria-label="Observatory quick jump command palette"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -6 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            onKeyDown={handleKeyDown}
            className="w-full max-w-xl glass-card rounded-xl overflow-hidden shadow-2xl border border-slate-200/80 dark:border-white/15 bg-white/95 dark:bg-[#0b1222]/95"
          >
            {/* Search Input Header */}
            <div className="flex items-center gap-2.5 px-3.5 py-2.5 border-b border-slate-200/80 dark:border-white/10">
              <Search className="w-4 h-4 text-sky-600 dark:text-sky-400 shrink-0" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Jump to chapter, SQL dataset, metric, or action…"
                className="flex-1 bg-transparent text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-none"
                aria-label="Search chapters and actions"
              />
              <button
                type="button"
                onClick={onClose}
                className="px-1.5 py-0.5 text-[10px] font-mono text-slate-500 dark:text-slate-400 rounded glass-well hover:text-slate-900 dark:hover:text-white cursor-pointer"
              >
                ESC
              </button>
            </div>

            {/* Results List */}
            <div
              ref={listRef}
              className="max-h-[54vh] overflow-y-auto thin-scroll p-1.5 space-y-0.5"
              role="listbox"
            >
              {filtered.length === 0 ? (
                <div className="py-8 text-center text-xs text-slate-500 dark:text-slate-400 font-mono">
                  No chapters or actions match &ldquo;{query}&rdquo;
                </div>
              ) : (
                filtered.map((item, idx) => {
                  const prevSection = idx > 0 ? filtered[idx - 1].section : null;
                  const showHeader = item.section !== prevSection;
                  const selected = idx === selectedIdx;

                  return (
                    <React.Fragment key={item.id}>
                      {showHeader && (
                        <div className="px-2.5 pt-2 pb-1 text-[10px] font-mono uppercase tracking-wider text-slate-400 dark:text-slate-500">
                          {item.section}
                        </div>
                      )}
                      <button
                        type="button"
                        data-cmd-idx={idx}
                        role="option"
                        aria-selected={selected}
                        onMouseEnter={() => setSelectedIdx(idx)}
                        onClick={item.perform}
                        className={`w-full flex items-center justify-between gap-3 px-2.5 py-2 rounded-lg text-left transition-colors cursor-pointer ${
                          selected
                            ? 'bg-sky-500/15 dark:bg-sky-500/20 text-slate-900 dark:text-white border border-sky-400/35'
                            : 'text-slate-700 dark:text-slate-200 border border-transparent hover:bg-slate-100/60 dark:hover:bg-white/5'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span
                            className={`shrink-0 w-6 h-6 rounded-md flex items-center justify-center ${
                              selected
                                ? 'bg-sky-500/20 text-sky-600 dark:text-sky-300'
                                : 'glass-well text-slate-500 dark:text-slate-400'
                            }`}
                          >
                            {item.icon === 'theme' ? (
                              theme === 'dark' ? (
                                <Sun className="w-3.5 h-3.5 text-amber-400" />
                              ) : (
                                <Moon className="w-3.5 h-3.5" />
                              )
                            ) : item.icon === 'copy' ? (
                              copiedCli ? (
                                <Check className="w-3.5 h-3.5 text-emerald-500" />
                              ) : (
                                <Terminal className="w-3.5 h-3.5" />
                              )
                            ) : (
                              <Compass className="w-3.5 h-3.5" />
                            )}
                          </span>

                          <div className="min-w-0">
                            <div className="text-xs font-semibold truncate flex items-center gap-2">
                              <span>{item.title}</span>
                              {item.active && (
                                <span className="text-[10px] font-mono text-sky-600 dark:text-sky-400 font-normal">
                                  · Current
                                </span>
                              )}
                            </div>
                            <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
                              {item.subtitle}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          {item.badge && (
                            <span className="text-[11px] font-mono tabular-nums text-slate-500 dark:text-slate-400">
                              {item.badge}
                            </span>
                          )}
                          <ArrowRight
                            className={`w-3.5 h-3.5 transition-opacity ${
                              selected
                                ? 'opacity-100 text-sky-600 dark:text-sky-400'
                                : 'opacity-0'
                            }`}
                          />
                        </div>
                      </button>
                    </React.Fragment>
                  );
                })
              )}
            </div>

            {/* Footer Shortcuts */}
            <div className="px-3.5 py-2 border-t border-slate-200/70 dark:border-white/10 flex items-center justify-between text-[10.5px] font-mono text-slate-500 dark:text-slate-400 bg-slate-50/70 dark:bg-black/20">
              <span>↑↓ Navigate · ↵ Open · Esc Close</span>
              <span>Finland Grid Observatory</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
