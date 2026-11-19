/** Relative URLs: the page works at a dev server's root and under the GitHub Pages project path. */
export const DATA_URLS = {
  recent: 'data/fingrid_recent_daily.json',
  scorecard: 'data/forecast_scorecard.json',
  co2: 'data/co2_forecast.json',
  events: 'data/grid_events.json',
  temperature: 'data/temperature.json',
  windAlloc: 'data/wind_allocation.json',
  ranges: 'data/forecast_ranges.json',
  sql: 'data/sql_sources.json',
  engineering: 'data/engineering.json',
  weatherModel: 'data/weather_model.json',
  leadTime: 'data/weather_lead_time.json',
  hydroFlex: 'data/hydro_flex.json',
  strikes: 'data/strike_effect.json',
  priceWind: 'data/price_wind.json',
  europe: 'data/europe.json',
  evCharging: 'data/ev_charging.json',
} as const;

/** Newest Fingrid values, written by the hourly Pages deploy (git-ignored, so it can be absent). */
export const LATEST_URL = 'data/fingrid_latest.json';

export type DatasetKey = keyof typeof DATA_URLS;

export interface ObservatoryData {
  recent: any | null;
  scorecard: any | null;
  co2: any | null;
  events: any | null;
  temperature: any | null;
  windAlloc: any | null;
  ranges: any | null;
  sql: any | null;
  engineering: any | null;
  weatherModel: any | null;
  leadTime: any | null;
  hydroFlex: any | null;
  strikes: any | null;
  priceWind: any | null;
  europe: any | null;
  evCharging: any | null;
  errors: Partial<Record<DatasetKey, string>>;
  loading: boolean;
}

export async function loadAllObservatoryData(): Promise<Omit<ObservatoryData, 'loading'>> {
  const keys = Object.keys(DATA_URLS) as DatasetKey[];
  const errors: Partial<Record<DatasetKey, string>> = {};
  const results: Partial<Record<DatasetKey, any>> = {};

  await Promise.all(
    keys.map(async (key) => {
      try {
        const res = await fetch(DATA_URLS[key]);
        if (!res.ok) {
          throw new Error(`${DATA_URLS[key]} returned HTTP ${res.status}`);
        }
        results[key] = await res.json();
      } catch (err: any) {
        results[key] = null;
        errors[key] = `${DATA_URLS[key]} could not be loaded; the rest of the page still works.`;
      }
    })
  );

  return {
    recent: results.recent ?? null,
    scorecard: results.scorecard ?? null,
    co2: results.co2 ?? null,
    events: results.events ?? null,
    temperature: results.temperature ?? null,
    windAlloc: results.windAlloc ?? null,
    ranges: results.ranges ?? null,
    sql: results.sql ?? null,
    engineering: results.engineering ?? null,
    weatherModel: results.weatherModel ?? null,
    leadTime: results.leadTime ?? null,
    hydroFlex: results.hydroFlex ?? null,
    strikes: results.strikes ?? null,
    priceWind: results.priceWind ?? null,
    europe: results.europe ?? null,
    evCharging: results.evCharging ?? null,
    errors,
  };
}

export interface LatestReading {
  value_mw: number;
  start_time: string;
  end_time: string;
}

export interface LatestFingrid {
  generated_at: string;
  wind_production: LatestReading;
  consumption: LatestReading;
}

/** The live row is optional: any failure (404, bad JSON, missing fields) just hides it. */
export async function loadLatestFingrid(): Promise<LatestFingrid | null> {
  try {
    const res = await fetch(LATEST_URL, { cache: 'no-store' });
    if (!res.ok) return null;
    const lt = await res.json();
    return lt?.wind_production && lt?.consumption && lt?.generated_at ? lt : null;
  } catch {
    return null;
  }
}

export function fmt(v: number | null | undefined, d = 0): string {
  if (v == null || !Number.isFinite(v)) return '–';
  return Number(v).toLocaleString('en-US', {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
}

export function dayFmt(iso: string): string {
  const dateStr = iso.includes('T') ? iso : `${iso}T12:00:00Z`;
  return new Date(dateStr).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

export function dayWord(isoDay: string): string {
  const fiDay = (offset: number) =>
    new Date(Date.now() + offset * 864e5).toLocaleDateString('en-CA', {
      timeZone: 'Europe/Helsinki',
    });
  if (isoDay === fiDay(0)) return 'today';
  if (isoDay === fiDay(1)) return 'tomorrow';
  return `on ${dayFmt(`${isoDay}T12:00:00Z`)}`;
}

export function signed(v: number): string {
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${fmt(Math.abs(Math.round(v)))}`;
}

export function hrs(h: number): string {
  return `${String(h).padStart(2, '0')}:00`;
}

export function hourSpan(h: number, n = 1): string {
  return `${hrs(h)}–${hrs((h + n) % 24)}`;
}

export function pct(v: number): string {
  return `${fmt(Math.abs(v) < 0.005 ? 0 : v * 100, 0)}%`;
}

export function getSqlSource(sqlData: any, path: string): string {
  if (!sqlData || !Array.isArray(sqlData.files)) return 'Source file not available.';
  const match = sqlData.files.find((f: any) => f.path === path);
  return match ? match.sql : `Source ${path} not found in bundle.`;
}
