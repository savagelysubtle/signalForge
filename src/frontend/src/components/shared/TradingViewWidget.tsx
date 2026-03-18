import { useEffect, useRef } from 'react';

interface TradingViewWidgetProps {
  symbol: string;
}

export function TradingViewWidget({ symbol }: TradingViewWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Clear previous widget
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
      interval: "D",
      allow_symbol_change: true,
      studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"],
    });

    containerRef.current.appendChild(script);

    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [symbol]);

  return (
    <div className="w-full h-full" ref={containerRef} />
  );
}
