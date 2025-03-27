import React, { useEffect, useState } from "react";
import api from "../api"; // Centralized API client
import "../styles/dashboard.css";

// Numeric helpers
import {
  parseDecimal,
  formatUsd,
  formatBtc,
  parseGainsAndLosses,
} from "../utils/format";

const Dashboard: React.FC = () => {
  // ------------------ 1) STATE DECLARATIONS ------------------
  const [balances, setBalances] = useState<AccountBalance[] | null>(null);
  const [bankBalance, setBankBalance] = useState<number>(0);
  const [exchangeUSDBalance, setExchangeUSDBalance] = useState<number>(0);
  const [exchangeBTCBalance, setExchangeBTCBalance] = useState<number>(0);
  const [walletBTCBalance, setWalletBTCBalance] = useState<number>(0);
  const [totalBTC, setTotalBTC] = useState<number>(0);
  // Removed totalUSD since it’s unused

  // Cost basis & Gains
  const [averageBtcCostBasis, setAverageBtcCostBasis] = useState<number | null>(null);
  const [gainsAndLosses, setGainsAndLosses] = useState<GainsAndLosses | null>(null);

  // BTC Price & error states
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [currentBtcPrice, setCurrentBtcPrice] = useState<number | null>(null);
  const [isPriceLoading, setIsPriceLoading] = useState(true);

  // ------------------ 2) FETCH LIVE BTC PRICE ------------------
  useEffect(() => {
    setIsPriceLoading(true);
    api
      .get("/bitcoin/price")
      .then((res) => {
        if (res.data && res.data.USD) {
          setCurrentBtcPrice(res.data.USD);
        }
      })
      .catch((err) => {
        console.error("Error fetching live BTC price:", err);
      })
      .finally(() => {
        setIsPriceLoading(false);
      });
  }, []);

  // ------------------ 3) FETCH AVERAGE COST BASIS ------------------
  useEffect(() => {
    api
      .get<AverageCostBasis>("/calculations/average-cost-basis")
      .then((res) => {
        setAverageBtcCostBasis(res.data.averageCostBasis);
      })
      .catch((err) => {
        console.error("Error fetching average cost basis:", err);
      });
  }, []);

  // ------------------ 4) FETCH ACCOUNT BALANCES ------------------
  useEffect(() => {
    api
      .get("/calculations/accounts/balances")
      .then((response) => {
        const data = response.data;
        if (!Array.isArray(data)) {
          throw new Error("Data is not an array. Received: " + JSON.stringify(data));
        }
        setBalances(data as AccountBalance[]);
      })
      .catch((err) => {
        console.error("Error fetching balances:", err);
        setFetchError(String(err));
      });
  }, []);

  // ------------------ 5) CALCULATE TOTALS ------------------
  useEffect(() => {
    if (!balances) return;

    let bank = 0;
    let exchUSD = 0;
    let exchBTC = 0;
    let wBTC = 0;
    let totalBtcTemp = 0;

    balances.forEach((acc) => {
      const numericBalance = parseDecimal(acc.balance);
      if (Number.isNaN(numericBalance)) {
        console.warn("NaN balance for account:", acc);
        return;
      }
      // Skip fee accounts
      if (acc.name === "BTC Fees" || acc.name === "USD Fees") {
        return;
      }
      // Identify known accounts
      if (acc.name === "Bank" && acc.currency === "USD") {
        bank = numericBalance;
      } else if (acc.name === "Wallet" && acc.currency === "BTC") {
        wBTC = numericBalance;
      } else if (acc.name === "Exchange USD" && acc.currency === "USD") {
        exchUSD = numericBalance;
      } else if (acc.name === "Exchange BTC" && acc.currency === "BTC") {
        exchBTC = numericBalance;
      }

      // Tally BTC total
      if (acc.currency === "BTC") {
        totalBtcTemp += numericBalance;
      }
    });

    setBankBalance(bank);
    setExchangeUSDBalance(exchUSD);
    setExchangeBTCBalance(exchBTC);
    setWalletBTCBalance(wBTC);
    setTotalBTC(totalBtcTemp);
  }, [balances]);

  // ------------------ 6) FETCH GAINS & LOSSES ------------------
  useEffect(() => {
    api
      .get<GainsAndLossesRaw>("/calculations/gains-and-losses")
      .then((response) => {
        const parsed = parseGainsAndLosses(response.data);
        setGainsAndLosses(parsed);
      })
      .catch((err) => {
        console.error("Error fetching gains & losses:", err);
        setFetchError(String(err));
      });
  }, []);

  // ------------------ 7) ERROR / LOADING HANDLING ------------------
  if (fetchError) {
    return (
      <div style={{ color: "red", margin: "2rem" }}>
        <h2>Error Loading Data</h2>
        <p>{fetchError}</p>
      </div>
    );
  }

  if (balances === null || gainsAndLosses === null) {
    return (
      <div className="dashboard">
        <h2>Loading data...</h2>
      </div>
    );
  }

  // ------------------ 8) UNREALIZED GAINS HELPER ------------------
  const renderUnrealizedGains = () => {
    if (isPriceLoading || currentBtcPrice === null || averageBtcCostBasis === null) {
      return "Loading...";
    }
    const gains = (currentBtcPrice - averageBtcCostBasis) * totalBTC;
    const isGain = gains >= 0;
    const signSymbol = isGain ? "+" : "-";
    const displayAmount = Math.abs(gains);
    return (
      <span className={isGain ? "text-gain" : "text-loss"}>
        {signSymbol}
        {formatUsd(displayAmount)}
      </span>
    );
  };

  // ------------------ 9) RENDER DASHBOARD ------------------
  return (
    <div className="dashboard">
      {/* =================== TOP ROW: 2 CARDS =================== */}
      <div className="top-row">
        {/* (1) Portfolio Overview */}
        <div className="card portfolio-overview">
          <h3>Portfolio Overview</h3>

          {/* Label on left, value on right (like Gains & Losses) */}
          <p>
            <strong>Bank (USD):</strong>
            <span>{formatUsd(bankBalance)}</span>
          </p>
          <p>
            <strong>Exchange (USD):</strong>
            <span>{formatUsd(exchangeUSDBalance)}</span>
          </p>
          <p>
            <strong>Exchange (BTC):</strong>
            <span>{formatBtc(exchangeBTCBalance)}</span>
          </p>
          <p>
            <strong>Wallet (BTC):</strong>
            <span>{formatBtc(walletBTCBalance)}</span>
          </p>

          <hr />

          <p>
            <strong>Total BTC:</strong>
            <span>{formatBtc(totalBTC)}</span>
          </p>
          <p>
            <strong>BTC Cost Basis:</strong>
            <span>
              {averageBtcCostBasis !== null ? formatUsd(averageBtcCostBasis) : "Loading..."}
            </span>
          </p>
          <p>
            <strong>Unrealized Gains/Losses:</strong>
            <span>{renderUnrealizedGains()}</span>
          </p>
        </div>

        {/* (2) Current Bitcoin Price */}
        <div className="card btc-price-container">
          {/* Title row with logo on the left, heading on the right */}
          <div className="btc-price-header">
            <h3>Current Bitcoin Price</h3>
          </div>

          {/* The big orange price in the center */}
          <div className="btc-price-large">
            {isPriceLoading ? (
              <span className="btc-price-value">Loading...</span>
            ) : currentBtcPrice !== null ? (
              <span className="btc-price-value">
                $
                {currentBtcPrice.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            ) : (
              <span className="btc-price-value">Error</span>
            )}
          </div>
        </div>
      </div>

      {/* =================== BOTTOM ROW: 2 CARDS =================== */}
      <div className="bottom-row">
        {/* (3) Realized Gains/Losses (FIFO) */}
        <div className="card realized-gains-container">
          <h3>Realized Gains/Losses (FIFO)</h3>

          <p>
            <strong>Short-Term Gains:</strong>
            <span className={gainsAndLosses.short_term_gains > 0 ? "text-gain" : ""}>
              {formatUsd(gainsAndLosses.short_term_gains)}
            </span>
          </p>
          <p>
            <strong>Short-Term Losses:</strong>
            <span className={gainsAndLosses.short_term_losses > 0 ? "text-loss" : ""}>
              {formatUsd(gainsAndLosses.short_term_losses)}
            </span>
          </p>
          <p>
            <strong>Net Short-Term:</strong>
            <span
              className={
                gainsAndLosses.short_term_net > 0
                  ? "text-gain"
                  : gainsAndLosses.short_term_net < 0
                  ? "text-loss"
                  : ""
              }
            >
              {formatUsd(gainsAndLosses.short_term_net)}
            </span>
          </p>

          <hr />

          <p>
            <strong>Long-Term Gains:</strong>
            <span className={gainsAndLosses.long_term_gains > 0 ? "text-gain" : ""}>
              {formatUsd(gainsAndLosses.long_term_gains)}
            </span>
          </p>
          <p>
            <strong>Long-Term Losses:</strong>
            <span className={gainsAndLosses.long_term_losses > 0 ? "text-loss" : ""}>
              {formatUsd(gainsAndLosses.long_term_losses)}
            </span>
          </p>
          <p>
            <strong>Net Long-Term:</strong>
            <span
              className={
                gainsAndLosses.long_term_net > 0
                  ? "text-gain"
                  : gainsAndLosses.long_term_net < 0
                  ? "text-loss"
                  : ""
              }
            >
              {formatUsd(gainsAndLosses.long_term_net)}
            </span>
          </p>

          <hr />

          <p>
            <strong>Total Net Capital Gains:</strong>
            <span
              className={
                gainsAndLosses.total_net_capital_gains > 0
                  ? "text-gain"
                  : gainsAndLosses.total_net_capital_gains < 0
                  ? "text-loss"
                  : ""
              }
            >
              {formatUsd(gainsAndLosses.total_net_capital_gains)}
            </span>
          </p>
          <p>
            <strong>Year to Date Gains:</strong>
            <span
              className={
                gainsAndLosses.year_to_date_capital_gains > 0
                  ? "text-gain"
                  : gainsAndLosses.year_to_date_capital_gains < 0
                  ? "text-loss"
                  : ""
              }
            >
              {formatUsd(gainsAndLosses.year_to_date_capital_gains)}
            </span>
          </p>
        </div>

        {/* (4) Income & Fees */}
        <div className="card income-fees-container">
          <h3>Income & Fees</h3>

          <p>
            <strong>Income (earned):</strong>
            <span>
              {formatUsd(gainsAndLosses.income_earned)} (
              <em>{formatBtc(gainsAndLosses.income_btc)}</em>)
            </span>
          </p>
          <p>
            <strong>Interest (earned):</strong>
            <span>
              {formatUsd(gainsAndLosses.interest_earned)} (
              <em>{formatBtc(gainsAndLosses.interest_btc)}</em>)
            </span>
          </p>
          <p>
            <strong>Rewards (earned):</strong>
            <span>
              {formatUsd(gainsAndLosses.rewards_earned)} (
              <em>{formatBtc(gainsAndLosses.rewards_btc)}</em>)
            </span>
          </p>

          <hr />

          <p>
            <strong>Total Income:</strong>
            <span>{formatUsd(gainsAndLosses.total_income)}</span>
          </p>

          <p>
            <strong>Gifts (received):</strong>
            <span>
              {formatUsd(gainsAndLosses.gifts_received)} (
              <em>{formatBtc(gainsAndLosses.gifts_btc)}</em>)
            </span>
          </p>
          <p className="gifts-note">
            <em>(not added to income or gains)</em>
          </p>

          <hr />

          <h4>Fees</h4>
          <p>
            <strong>Fees (USD):</strong>
            <span>{formatUsd(gainsAndLosses.fees.USD)}</span>
          </p>
          <p>
            <strong>Fees (BTC):</strong>
            <span>{formatBtc(gainsAndLosses.fees.BTC)}</span>
          </p>

          {isPriceLoading ? (
            <p>
              <strong>Total Fees in USD (approx):</strong>
              <span>Loading...</span>
            </p>
          ) : currentBtcPrice !== null ? (
            <p>
              <strong>Total Fees in USD (approx):</strong>
              <span>
                {formatUsd(
                  gainsAndLosses.fees.USD + gainsAndLosses.fees.BTC * currentBtcPrice
                )}
              </span>
            </p>
          ) : (
            <p>
              <strong>Total Fees in USD:</strong>
              <span>N/A</span>
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;