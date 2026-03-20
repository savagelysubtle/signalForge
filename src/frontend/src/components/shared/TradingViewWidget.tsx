import { useEffect, useRef, useMemo } from 'react';

interface TradingViewWidgetProps {
  symbol: string;
  indicators?: string[];
  interval?: string;
}

const TV_STUDY_MAP: Record<string, string> = {
  "RSI": "RSI@tv-basicstudies",
  "MACD": "MACD@tv-basicstudies",
  "Bollinger Bands": "BB@tv-basicstudies",
  "Stochastic": "Stoch@tv-basicstudies",
  "ATR": "ATR@tv-basicstudies",
  "EMA_20": "MAExp@tv-basicstudies",
  "EMA_50": "MAExp@tv-basicstudies",
  "SMA_50": "MASimple@tv-basicstudies",
  "SMA_200": "MASimple@tv-basicstudies",
  "VWAP": "VWAP@tv-basicstudies",
  "OBV": "OBV@tv-basicstudies",
  "CCI": "CCI@tv-basicstudies",
  "Ichimoku": "IchimokuCloud@tv-basicstudies",
  "DMI": "DMI@tv-basicstudies",
  "Parabolic SAR": "PSAR@tv-basicstudies",
};

const BASELINE_STUDIES = ["RSI@tv-basicstudies", "MACD@tv-basicstudies"];

const INTERVAL_MAP: Record<string, string> = {
  "1H": "60",
  "2H": "120",
  "4H": "240",
  "D": "D",
  "W": "W",
  "M": "M",
};

export function TradingViewWidget({ symbol, indicators, interval }: TradingViewWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const studies = useMemo(() => {
    const mapped = (indicators ?? [])
      .map(ind => TV_STUDY_MAP[ind])
      .filter((s): s is string => s !== undefined);
    const combined = [...BASELINE_STUDIES, ...mapped];
    return [...new Set(combined)];
  }, [indicators]);

  const tvInterval = interval ? (INTERVAL_MAP[interval] ?? interval) : "D";

  useEffect(() => {
    if (!containerRef.current) return;

    containerRef.current.innerHTML = '';

    const script = document.createElement('script');
    script.src = 'https://s.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      symbol: symbol,
      width: "100%",
      height: "100%",
      colorTheme: "dark",
      isTransparent: true,
      locale: "en",
      interval: tvInterval,
      allow_symbol_change: true,
      studies: studies,
    });

    containerRef.current.appendChild(script);

    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [symbol, tvInterval, studies]);

  return (
    <div className="w-full h-full" ref={containerRef} />
  );
}
