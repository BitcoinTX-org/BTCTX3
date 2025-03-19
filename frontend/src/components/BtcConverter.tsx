import React, { useState, useEffect } from "react";
import api from "../api"; // Your centralized Axios/fetch wrapper
import "../styles/converter.css";

// Define response types for API calls
interface LiveBtcPriceResponse {
  USD: number;
}

interface HistoricalBtcPriceResponse {
  USD: number;
}

const BtcConverter: React.FC = () => {
  // State: Mode selection (manual, auto, or date)
  const [mode, setMode] = useState<"manual" | "auto" | "date">("auto");
  const [btcPrice, setBtcPrice] = useState<number>(0);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [usdValue, setUsdValue] = useState<string>("");
  const [btcValue, setBtcValue] = useState<string>("");
  const [satsValue, setSatsValue] = useState<string>("");

  // Auto mode: Fetch live price periodically
  useEffect(() => {
    if (mode !== "auto") return;

    const fetchLivePrice = async () => {
      try {
        const res = await api.get<LiveBtcPriceResponse>("/bitcoin/price");
        if (res.data && typeof res.data.USD === "number") {
          setBtcPrice(res.data.USD);
        } else {
          setBtcPrice(0);
        }
      } catch (err) {
        console.error("Failed to fetch live BTC price:", err);
        setBtcPrice(0);
      }
    };

    fetchLivePrice();
    const intervalId = setInterval(fetchLivePrice, 120_000);
    return () => clearInterval(intervalId);
  }, [mode]);

  // Date mode: Fetch historical price when date is selected
  useEffect(() => {
    if (mode !== "date" || !selectedDate) return;

    const fetchHistoricalPrice = async () => {
      try {
        const res = await api.get<HistoricalBtcPriceResponse>(
          `/bitcoin/price/history?date=${selectedDate}`
        );
        if (res.data && typeof res.data.USD === "number") {
          setBtcPrice(res.data.USD);
        } else {
          setBtcPrice(0);
        }
      } catch (err) {
        console.error("Failed to fetch historical BTC price:", err);
        setBtcPrice(0);
      }
    };

    fetchHistoricalPrice();
  }, [mode, selectedDate]);

  // Mode switch handler
  const handleModeChange = (newMode: "manual" | "auto" | "date") => {
    setMode(newMode);
    setSelectedDate("");
    if (newMode === "manual") {
      setBtcPrice(0);
    }
  };

  // Helper: Round to 5 decimal places
  const round = (num: number) => Math.round(num * 100_000) / 100_000;

  // Conversion Logic
  const handleUsdChange = (value: string) => {
    setUsdValue(value);
    const usdNum = parseFloat(value) || 0;
    const btcNum = usdNum / btcPrice;
    const satsNum = btcNum * 100_000_000;
    setBtcValue(btcNum ? round(btcNum).toString() : "");
    setSatsValue(satsNum ? Math.floor(satsNum).toString() : "");
  };

  const handleBtcChange = (value: string) => {
    setBtcValue(value);
    const btcNum = parseFloat(value) || 0;
    const usdNum = btcNum * btcPrice;
    const satsNum = btcNum * 100_000_000;
    setUsdValue(usdNum ? round(usdNum).toString() : "");
    setSatsValue(satsNum ? Math.floor(satsNum).toString() : "");
  };

  const handleSatsChange = (value: string) => {
    setSatsValue(value);
    const satsNum = parseFloat(value) || 0;
    const btcNum = satsNum / 100_000_000;
    const usdNum = btcNum * btcPrice;
    setBtcValue(btcNum ? round(btcNum).toString() : "");
    setUsdValue(usdNum ? round(usdNum).toString() : "");
  };

  // Render
  return (
    <div className="converter">
      <div className="converter-title">Sats Converter</div>

      {/* Three mode buttons */}
      <div className="price-toggle">
        <button
          className={mode === "manual" ? "toggle-btn active" : "toggle-btn"}
          onClick={() => handleModeChange("manual")}
        >
          Manual
        </button>
        <button
          className={mode === "auto" ? "toggle-btn active" : "toggle-btn"}
          onClick={() => handleModeChange("auto")}
        >
          Auto
        </button>
        <button
          className={mode === "date" ? "toggle-btn active" : "toggle-btn"}
          onClick={() => handleModeChange("date")}
        >
          Date
        </button>
      </div>

      {/* Manual mode: Show editable price input */}
      {mode === "manual" && (
        <div className="manual-price-row">
          <label htmlFor="manualPrice">BTC Price (USD)</label>
          <input
            id="manualPrice"
            type="number"
            value={btcPrice}
            onChange={(e) => {
              const val = parseFloat(e.target.value);
              setBtcPrice(isNaN(val) ? 0 : val);
            }}
          />
        </div>
      )}

      {/* Auto mode: Show live price */}
      {mode === "auto" && (
        <div className="auto-price-row">
          <p>
            BTC Price: $
            {btcPrice.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </p>
        </div>
      )}

      {/* Date mode: Show date picker and price */}
      {mode === "date" && (
        <div className="date-price-row">
          <label htmlFor="datePicker">Select Date</label>
          <input
            id="datePicker"
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
          />
          <p>
            BTC Price: $
            {btcPrice.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </p>
        </div>
      )}

      {/* Conversion fields */}
      <div className="converter-row">
        <label htmlFor="usdInput">USD</label>
        <input
          id="usdInput"
          type="number"
          value={usdValue}
          onChange={(e) => handleUsdChange(e.target.value)}
        />
      </div>
      <div className="converter-row">
        <label htmlFor="btcInput">BTC</label>
        <input
          id="btcInput"
          type="number"
          value={btcValue}
          onChange={(e) => handleBtcChange(e.target.value)}
        />
      </div>
      <div className="converter-row">
        <label htmlFor="satsInput">Satoshi</label>
        <input
          id="satsInput"
          type="number"
          value={satsValue}
          onChange={(e) => handleSatsChange(e.target.value)}
        />
      </div>
    </div>
  );
};

export default BtcConverter;