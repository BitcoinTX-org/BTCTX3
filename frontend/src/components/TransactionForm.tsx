//frontend/src/components/TransactionForm.tsx
import React, { useState, useEffect } from "react";
import { useForm, SubmitHandler } from "react-hook-form";
import axios from "axios";
import api from "../api";
import "../styles/transactionForm.css";
import { parseDecimal, formatUsd, parseTransaction } from "../utils/format";

/**
 * localDatetimeToIso:
 * Converts "datetime-local" (e.g. "2025-03-01T12:00")
 * to a full ISO8601 string for the backend.
 */
function localDatetimeToIso(localDatetime: string): string {
  return new Date(localDatetime).toISOString();
}

// Hardcoded account IDs
const EXTERNAL_ID = 99;
const EXCHANGE_USD_ID = 3;
const EXCHANGE_BTC_ID = 4;

/**
 * mapAccountToId:
 * Convert an AccountType + Currency to the numeric ID recognized by the backend.
 */
function mapAccountToId(account?: AccountType, currency?: Currency): number {
  if (account === "Bank") return 1;
  if (account === "Wallet") return 2;
  if (account === "Exchange") {
    return currency === "BTC" ? EXCHANGE_BTC_ID : EXCHANGE_USD_ID;
  }
  return 0;
}

/**
 * mapDoubleEntryAccounts:
 * Single-entry style => from/to IDs for the ledger.
 */
function mapDoubleEntryAccounts(data: TransactionFormData): IAccountMapping {
  switch (data.type) {
    case "Deposit":
      return {
        from_account_id: EXTERNAL_ID,
        to_account_id: mapAccountToId(data.account, data.currency),
      };
    case "Withdrawal":
      return {
        from_account_id: mapAccountToId(data.account, data.currency),
        to_account_id: EXTERNAL_ID,
      };
    case "Transfer":
      return {
        from_account_id: mapAccountToId(data.fromAccount, data.fromCurrency),
        to_account_id: mapAccountToId(data.toAccount, data.toCurrency),
      };
    case "Buy":
      return {
        from_account_id: EXCHANGE_USD_ID,
        to_account_id: EXCHANGE_BTC_ID,
      };
    case "Sell":
      return {
        from_account_id: EXCHANGE_BTC_ID,
        to_account_id: EXCHANGE_USD_ID,
      };
    default:
      return { from_account_id: 0, to_account_id: 0 };
  }
}

/**
 * mapTransactionToFormData:
 * Converts an ITransaction (fetched from backend) into TransactionFormData
 * so we can populate the form fields in edit mode.
 */
function mapTransactionToFormData(tx: ITransaction): TransactionFormData {
  // Common fields
  const baseData: TransactionFormData = {
    type: tx.type,
    timestamp: new Date(tx.timestamp).toISOString().slice(0, 16), // for datetime-local
    fee: tx.fee_amount ?? 0,
    // You can set defaults for everything else:
    costBasisUSD: tx.cost_basis_usd ?? 0,
    proceeds_usd: tx.proceeds_usd ?? 0,
  };

  // Helper to convert account_id => "Bank", "Wallet", "Exchange", etc.
  const accountIdToType = (id: number): AccountType => {
    switch (id) {
      case 1:
        return "Bank";
      case 2:
        return "Wallet";
      case 3:
      case 4:
        return "Exchange";
      default:
        return "External";
    }
  };

  // Helper to guess currency from ID
  const getCurrencyFromAccountId = (id: number): Currency =>
    id === 1 || id === 3 ? "USD" : "BTC";

  switch (tx.type) {
    case "Deposit": {
      const toAcctId = tx.to_account_id ?? 0;
      return {
        ...baseData,
        account: accountIdToType(toAcctId),
        currency: getCurrencyFromAccountId(toAcctId),
        amount: tx.amount,
        source: (tx.source ?? "N/A") as DepositSource,
      };
    }
    case "Withdrawal": {
      const fromAcctId = tx.from_account_id ?? 0;
      return {
        ...baseData,
        account: accountIdToType(fromAcctId),
        currency: getCurrencyFromAccountId(fromAcctId),
        amount: tx.amount,
        purpose: (tx.purpose ?? "N/A") as WithdrawalPurpose,
      };
    }
    case "Transfer": {
      const fromAcctId = tx.from_account_id ?? 0;
      const toAcctId = tx.to_account_id ?? 0;
      const fromAccount = accountIdToType(fromAcctId);
      const toAccount = accountIdToType(toAcctId);
      const fromCurrency = getCurrencyFromAccountId(fromAcctId);
      const toCurrency = getCurrencyFromAccountId(toAcctId);

      return {
        ...baseData,
        fromAccount,
        toAccount,
        fromCurrency,
        toCurrency,
        amountFrom: tx.amount,
        // If it was BTC with a fee, "amountTo" is (amount - fee).
        amountTo: tx.type === "Transfer" && fromCurrency === "BTC"
          ? tx.amount - (tx.fee_amount ?? 0)
          : tx.amount,
      };
    }
    case "Buy":
      return {
        ...baseData,
        account: "Exchange",
        amountUSD: tx.cost_basis_usd ?? 0,
        amountBTC: tx.amount,
      };
    case "Sell":
      return {
        ...baseData,
        account: "Exchange",
        amountBTC: tx.amount,
        amountUSD: tx.proceeds_usd ?? 0,
      };
    default:
      // Return the base for safety
      return baseData;
  }
}

/**
 * TransactionForm:
 * Now supports both "create new" and "edit existing" (transactionId).
 */
const TransactionForm: React.FC<TransactionFormProps> = ({
  id,
  onDirtyChange,
  onSubmitSuccess,
  transactionId,           // new prop
  onUpdateStatusChange,     // new prop
}) => {
  // Set up react-hook-form
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    getValues,
    formState: { errors, isDirty },
  } = useForm<TransactionFormData>({
    defaultValues: {
      // Minimal defaults to start
      timestamp: new Date().toISOString().slice(0, 16),
      fee: 0,
      costBasisUSD: 0,
      proceeds_usd: 0,
    },
  });

  // Local state
  const [currentType, setCurrentType] = useState<TransactionType | "">("");
  const [feeInUsdDisplay, setFeeInUsdDisplay] = useState<number>(0);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Watch various fields
  const accountVal = watch("account");
  const currencyVal = watch("currency");
  const fromAccountVal = watch("fromAccount");
  const fromCurrencyVal = watch("fromCurrency");
  const amountFromVal = watch("amountFrom") || 0;
  const amountToVal = watch("amountTo") || 0;
  const amountUsdVal = watch("amountUSD") || 0;
  const amountBtcVal = watch("amountBTC") || 0;
  const purposeVal = watch("purpose");
  const proceedsUsdVal = watch("proceeds_usd") || 0;

  useEffect(() => {
  console.log("currencyVal:", currencyVal);
  console.log("amountUsdVal:", amountUsdVal);
  console.log("amountBtcVal:", amountBtcVal);
}, [currencyVal, amountUsdVal, amountBtcVal]);

  /**
   * Load existing transaction if we have a transactionId
   */
  useEffect(() => {
    if (transactionId) {
      api
        .get<ITransactionRaw>(`/transactions/${transactionId}`)
        .then((res) => {
          const tx = parseTransaction(res.data);
          const formData = mapTransactionToFormData(tx);
          reset(formData);
          setCurrentType(tx.type);
        })
        .catch((err) => {
          console.error("Failed to fetch transaction:", err);
          alert("Failed to load transaction data.");
        });
    } else {
      // If no transactionId => create mode
      reset({
        timestamp: new Date().toISOString().slice(0, 16),
        fee: 0,
        costBasisUSD: 0,
        proceeds_usd: 0,
      });
      setCurrentType("");
    }
  }, [transactionId, reset]);

  /**
   * Notify parent about "dirty" form
   */
  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  /**
   * Notify parent about submission status
   */
  useEffect(() => {
    onUpdateStatusChange?.(isSubmitting);
  }, [isSubmitting, onUpdateStatusChange]);

  /**
   * If Deposit/Withdrawal => auto-set currency for Bank/Wallet
   */
  useEffect(() => {
    if (currentType === "Deposit" || currentType === "Withdrawal") {
      if (accountVal === "Bank") {
        setValue("currency", "USD");
      } else if (accountVal === "Wallet") {
        setValue("currency", "BTC");
      }
      // If account=Exchange => user picks currency
    }
  }, [currentType, accountVal, setValue]);

  /**
   * Transfer logic => auto-set "toAccount" & "toCurrency" based on "fromAccount"
   */
  useEffect(() => {
    if (currentType === "Transfer") {
      if (fromAccountVal === "Bank") {
        setValue("fromCurrency", "USD");
        setValue("toAccount", "Exchange");
        setValue("toCurrency", "USD");
      } else if (fromAccountVal === "Wallet") {
        setValue("fromCurrency", "BTC");
        setValue("toAccount", "Exchange");
        setValue("toCurrency", "BTC");
      } else if (fromAccountVal === "Exchange") {
        if (fromCurrencyVal === "USD") {
          setValue("toAccount", "Bank");
          setValue("toCurrency", "USD");
        } else if (fromCurrencyVal === "BTC") {
          setValue("toAccount", "Wallet");
          setValue("toCurrency", "BTC");
        }
      }
    }
  }, [currentType, fromAccountVal, fromCurrencyVal, setValue]);

  /**
   * Auto-calc fee for BTC Transfer: fee = (amountFrom - amountTo)
   */
  useEffect(() => {
    if (currentType === "Transfer" && fromCurrencyVal === "BTC") {
      const calcFee = amountFromVal - amountToVal;
      if (calcFee < 0) {
        setValue("fee", 0);
      } else {
        const feeBtc = Number(calcFee.toFixed(8));
        setValue("fee", feeBtc);
        // Show approximate USD
        const mockBtcPrice = 30000; // or some dynamic price
        const approxUsd = feeBtc * mockBtcPrice;
        setFeeInUsdDisplay(Number(approxUsd.toFixed(2)));
      }
    }
  }, [currentType, fromCurrencyVal, amountFromVal, amountToVal, setValue]);

  /**
   * onTransactionTypeChange:
   * When user picks a new type from the dropdown, reset form fields.
   * (Disabled in edit mode, so only for creating new.)
   */
  const onTransactionTypeChange = (
    e: React.ChangeEvent<HTMLSelectElement>
  ) => {
    const newType = e.target.value as TransactionType;
    setCurrentType(newType);
  
    // Get the current values from the form
    const currentValues = getValues();
  
    // Partially reset: preserve existing values (including timestamp),
    // but override type, fee, costBasisUSD, proceeds_usd, etc.
    reset({
      ...currentValues,
      type: newType,
      fee: 0,
      costBasisUSD: 0,
      proceeds_usd: 0,
    });
  };

  /**
   * onSubmit:
   * Either create a new transaction or update the existing one.
   */
  const onSubmit: SubmitHandler<TransactionFormData> = async (data) => {
    setIsSubmitting(true);
    try {
      // 1) if BTC withdrawal & proceeds_usd not set, default to 0
      if (
        data.type === "Withdrawal" &&
        data.currency === "BTC" &&
        !data.proceeds_usd
      ) {
        data.proceeds_usd = 0;
      }

      // 2) from/to IDs
      const { from_account_id, to_account_id } = mapDoubleEntryAccounts(data);

      // 3) datetime => ISO
      const isoTimestamp = localDatetimeToIso(data.timestamp);

      // 4) figure out amount, costBasis, etc.
      let amount = 0;
      let feeCurrency: Currency = "USD";
      let source: string | undefined;
      let purpose: string | undefined;
      let cost_basis_usd = 0;
      let proceeds_usd: number | undefined;

      switch (data.type) {
        case "Deposit":
          amount = parseDecimal(data.amount);
          feeCurrency = data.currency === "BTC" ? "BTC" : "USD";
          source = data.source && data.source !== "N/A" ? data.source : "N/A";
          if (
            data.currency === "BTC" &&
            (data.account === "Wallet" || data.account === "Exchange")
          ) {
            cost_basis_usd = parseDecimal(data.costBasisUSD);
          }
          break;

        case "Withdrawal":
          amount = parseDecimal(data.amount);
          feeCurrency = data.currency === "BTC" ? "BTC" : "USD";
          purpose = data.purpose && data.purpose !== "N/A" ? data.purpose : "N/A";
          proceeds_usd = parseDecimal(data.proceeds_usd);
          break;

        case "Transfer":
          amount = parseDecimal(data.amountFrom);
          feeCurrency = data.fromCurrency === "BTC" ? "BTC" : "USD";
          break;

        case "Buy":
          amount = parseDecimal(data.amountBTC);
          feeCurrency = "USD";
          cost_basis_usd = parseDecimal(data.amountUSD);
          break;

        case "Sell":
          amount = parseDecimal(data.amountBTC);
          feeCurrency = "USD";
          proceeds_usd = parseDecimal(data.amountUSD);
          break;
      }

      // 5) Build payload
      const payload: Omit<ICreateTransactionPayload, "is_locked"> = {
        type: data.type,
        timestamp: isoTimestamp,
        from_account_id,
        to_account_id,
        amount,
        fee_amount: parseDecimal(data.fee),
        fee_currency: feeCurrency,
        cost_basis_usd,
        proceeds_usd,
        source,
        purpose,
      };

      if (transactionId) {
        // --- Editing existing transaction ---
        await api.put(`/transactions/${transactionId}`, payload);
        alert("Transaction updated successfully!");
      } else {
        // --- Creating new transaction ---
        const createPayload: ICreateTransactionPayload = {
          ...payload,
          is_locked: false,
        };
        const response = await api.post("/transactions", createPayload);
        const createdTx = response.data as ITransactionRaw;
        const rg = createdTx.realized_gain_usd
          ? parseDecimal(createdTx.realized_gain_usd)
          : 0;

        if (rg !== 0) {
          const sign = rg >= 0 ? "+" : "";
          alert(
            `Transaction created successfully!\n` +
              `Realized Gain: ${sign}${formatUsd(rg)}`
          );
        } else {
          alert("Transaction created successfully!");
        }
      }

      // Reset & notify success
      reset();
      setCurrentType("");
      onSubmitSuccess?.();
    } catch (error) {
      if (axios.isAxiosError<ApiErrorResponse>(error)) {
        const detailMsg =
          error.response?.data?.detail || error.message || "Error";
        alert(
          `Failed to ${
            transactionId ? "update" : "create"
          } transaction: ${detailMsg}`
        );
      } else if (error instanceof Error) {
        alert(
          `Failed to ${
            transactionId ? "update" : "create"
          } transaction: ${error.message}`
        );
      } else {
        alert(
          `An unexpected error occurred while ${
            transactionId ? "updating" : "creating"
          } the transaction.`
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteClick = async () => {
    const confirmed = window.confirm(
      "Are you sure you want to delete this transaction?"
    );
    if (!confirmed) return;
  
    setIsSubmitting(true);
    try {
      // We assume you have a DELETE /transactions/{id} route.
      await api.delete(`/transactions/${transactionId}`);
      alert("Transaction deleted successfully!");
      reset();
      onSubmitSuccess?.();
    } catch (error) {
      alert("Failed to delete transaction. Check console for details.");
      console.error("Delete error:", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  /**
   * renderDynamicFields:
   * Here is where we restore the complete JSX for each transaction type,
   * just like in your “before” file. That’s what was missing!
   */
  const renderDynamicFields = () => {
    switch (currentType) {
      case "Deposit": {
        // watchers you need inside deposit:
        const account = watch("account");
        const currency = watch("currency");

        // Show cost basis if BTC deposit into Wallet or Exchange
        const showCostBasisField =
          currentType === "Deposit" &&
          currency === "BTC" &&
          (account === "Wallet" || account === "Exchange");

        // Show source if BTC deposit into Wallet/Exchange
        const showSource =
          account === "Wallet" ||
          (account === "Exchange" && currency === "BTC");

        return (
          <>
            {/* Account */}
            <div className="form-group">
              <label>Account:</label>
              <select
                className="form-control"
                {...register("account", { required: true })}
              >
                <option value="">Select Account</option>
                <option value="Bank">Bank Account</option>
                <option value="Wallet">Bitcoin Wallet</option>
                <option value="Exchange">Exchange</option>
              </select>
              {errors.account && (
                <span className="error-text">Please select an account</span>
              )}
            </div>

            {/* Currency */}
            <div className="form-group">
              <label>Currency:</label>
              {account === "Exchange" ? (
                <select
                  className="form-control"
                  {...register("currency", { required: true })}
                >
                  <option value="">Select Currency</option>
                  <option value="USD">USD</option>
                  <option value="BTC">BTC</option>
                </select>
              ) : (
                <input
                  type="text"
                  className="form-control"
                  {...register("currency")}
                  readOnly
                />
              )}
              {errors.currency && (
                <span className="error-text">Currency is required</span>
              )}
            </div>

            {/* Amount */}
            <div className="form-group">
              <label>Amount:</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("amount", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amount && (
                <span className="error-text">Amount is required</span>
              )}
            </div>

            {/* Source */}
            {showSource && (
              <div className="form-group">
                <label>Source:</label>
                <select
                  className="form-control"
                  {...register("source", { required: true })}
                >
                  <option value="N/A">N/A</option>
                  <option value="MyBTC">MyBTC</option>
                  <option value="Gift">Gift</option>
                  <option value="Income">Income</option>
                  <option value="Interest">Interest</option>
                  <option value="Reward">Reward</option>
                </select>
              </div>
            )}

            {/* Cost Basis if BTC deposit */}
            {showCostBasisField && (
              <div className="form-group">
                <label>Cost Basis (USD):</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-control"
                  {...register("costBasisUSD", { valueAsNumber: true })}
                />
                <small style={{ color: "#888", display: "block", marginTop: 4 }}>
                  If you paid a miner fee in BTC externally, add its USD value here.
                </small>
              </div>
            )}
          </>
        );
      }

      case "Withdrawal": {
        const account = watch("account");
        const currency = watch("currency");
        const feeLabel = currency === "BTC" ? "Fee (BTC)" : "Fee (USD)";

        // Only show purpose if BTC withdrawal from Wallet/Exchange
        const showPurpose =
          account === "Wallet" ||
          (account === "Exchange" && currency === "BTC");

        return (
          <>
            {/* Account */}
            <div className="form-group">
              <label>Account:</label>
              <select
                className="form-control"
                {...register("account", { required: true })}
              >
                <option value="">Select Account</option>
                <option value="Bank">Bank Account</option>
                <option value="Wallet">Bitcoin Wallet</option>
                <option value="Exchange">Exchange</option>
              </select>
              {errors.account && (
                <span className="error-text">Please select an account</span>
              )}
            </div>

            {/* Currency */}
            <div className="form-group">
              <label>Currency:</label>
              {account === "Exchange" ? (
                <select
                  className="form-control"
                  {...register("currency", { required: true })}
                >
                  <option value="">Select Currency</option>
                  <option value="USD">USD</option>
                  <option value="BTC">BTC</option>
                </select>
              ) : (
                <input
                  type="text"
                  className="form-control"
                  {...register("currency")}
                  readOnly
                />
              )}
              {errors.currency && (
                <span className="error-text">Currency is required</span>
              )}
            </div>

            {/* Amount */}
            <div className="form-group">
              <label>Amount:</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("amount", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amount && (
                <span className="error-text">Amount is required</span>
              )}
            </div>

            {/* Purpose (BTC only) */}
            {showPurpose && (
              <div className="form-group">
                <label>Purpose (BTC only):</label>
                <select
                  className="form-control"
                  {...register("purpose", { required: true })}
                >
                  <option value="">Select Purpose</option>
                  <option value="Spent">Spent</option>
                  <option value="Gift">Gift</option>
                  <option value="Donation">Donation</option>
                  <option value="Lost">Lost</option>
                </select>
              </div>
            )}

            {/* Fee */}
            <div className="form-group">
              <label>{feeLabel}:</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("fee", { valueAsNumber: true })}
              />
            </div>

            {/* Proceeds if BTC */}
            {currency === "BTC" && (
              <div className="form-group">
                <label>Proceeds (USD):</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-control"
                  defaultValue={0}
                  {...register("proceeds_usd", { valueAsNumber: true })}
                />
                {/* Optional warning if user selects Spent with proceeds=0 */}
                {purposeVal === "Spent" && proceedsUsdVal === 0 && (
                  <div style={{ color: "red", marginTop: "5px" }}>
                    <strong>Warning:</strong> You selected “Spent” but “Proceeds (USD)” is 0.
                  </div>
                )}
              </div>
            )}
          </>
        );
      }

      case "Transfer": {
        const fromAccount = watch("fromAccount");
        const fromCurr = watch("fromCurrency");
        return (
          <>
            {/* From Account */}
            <div className="form-group">
              <label>From Account:</label>
              <select
                className="form-control"
                {...register("fromAccount", { required: true })}
              >
                <option value="">Select From Account</option>
                <option value="Bank">Bank Account</option>
                <option value="Wallet">Bitcoin Wallet</option>
                <option value="Exchange">Exchange</option>
              </select>
              {errors.fromAccount && (
                <span className="error-text">From Account is required</span>
              )}
            </div>

            {/* From Currency */}
            <div className="form-group">
              <label>From Currency:</label>
              {fromAccount === "Exchange" ? (
                <select
                  className="form-control"
                  {...register("fromCurrency", { required: true })}
                >
                  <option value="">Select Currency</option>
                  <option value="USD">USD</option>
                  <option value="BTC">BTC</option>
                </select>
              ) : (
                <input
                  type="text"
                  className="form-control"
                  {...register("fromCurrency")}
                  readOnly
                />
              )}
              {errors.fromCurrency && (
                <span className="error-text">From Currency is required</span>
              )}
            </div>

            {/* Amount (From) */}
            <div className="form-group">
              <label>Amount (From):</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("amountFrom", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amountFrom && (
                <span className="error-text">Amount (From) is required</span>
              )}
            </div>

            {/* To Account */}
            <div className="form-group">
              <label>To Account:</label>
              <input
                type="text"
                className="form-control"
                {...register("toAccount")}
                readOnly
              />
            </div>

            {/* To Currency */}
            <div className="form-group">
              <label>To Currency:</label>
              <input
                type="text"
                className="form-control"
                {...register("toCurrency")}
                readOnly
              />
            </div>

            {/* Amount (To) */}
            <div className="form-group">
              <label>Amount (To):</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("amountTo", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amountTo && (
                <span className="error-text">Amount (To) is required</span>
              )}
            </div>

            {/* Fee auto-calc if BTC */}
            {fromCurr === "BTC" ? (
              <div className="form-group">
                <label>Fee (BTC):</label>
                <input
                  type="number"
                  step="0.00000001"
                  className="form-control"
                  {...register("fee", { valueAsNumber: true })}
                  readOnly
                />
                {feeInUsdDisplay > 0 && (
                  <small style={{ color: "#999" }}>
                    (~ ${feeInUsdDisplay} USD)
                  </small>
                )}
              </div>
            ) : (
              <div className="form-group">
                <label>Fee (USD):</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-control"
                  defaultValue={0}
                  {...register("fee", { valueAsNumber: true })}
                />
              </div>
            )}
          </>
        );
      }

      case "Buy": {
        return (
          <>
            {/* Account is always Exchange */}
            <div className="form-group">
              <label>Account:</label>
              <input
                type="text"
                className="form-control"
                value="Exchange"
                {...register("account")}
                readOnly
              />
            </div>

            {/* Amount USD */}
            <div className="form-group">
              <label>Amount USD:</label>
              <input
                type="number"
                step="0.01"
                className="form-control"
                {...register("amountUSD", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amountUSD && (
                <span className="error-text">Amount USD is required</span>
              )}
            </div>

            {/* Amount BTC */}
            <div className="form-group">
              <label>Amount BTC:</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("amountBTC", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amountBTC && (
                <span className="error-text">Amount BTC is required</span>
              )}
            </div>

            {/* Fee (USD) */}
            <div className="form-group">
              <label>Fee (USD):</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("fee", { valueAsNumber: true })}
              />
            </div>
          </>
        );
      }

      case "Sell": {
        return (
          <>
            {/* Account = Exchange */}
            <div className="form-group">
              <label>Account:</label>
              <input
                type="text"
                className="form-control"
                value="Exchange"
                {...register("account")}
                readOnly
              />
            </div>

            {/* Amount BTC */}
            <div className="form-group">
              <label>Amount BTC:</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("amountBTC", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amountBTC && (
                <span className="error-text">Amount BTC is required</span>
              )}
            </div>

            {/* Amount USD */}
            <div className="form-group">
              <label>Amount USD:</label>
              <input
                type="number"
                step="0.01"
                className="form-control"
                {...register("amountUSD", {
                  required: true,
                  valueAsNumber: true,
                })}
              />
              {errors.amountUSD && (
                <span className="error-text">Amount USD is required</span>
              )}
            </div>

            {/* Fee (USD) */}
            <div className="form-group">
              <label>Fee (USD):</label>
              <input
                type="number"
                step="0.00000001"
                className="form-control"
                {...register("fee", { valueAsNumber: true })}
              />
            </div>
          </>
        );
      }

      default:
        return null; // If type not chosen yet
    }
  };

  // ------------------------------------------------------------------------
  // Actual render
  // ------------------------------------------------------------------------
  return (
    <form
      id={id || "transaction-form"}
      className="transaction-form"
      onSubmit={handleSubmit(onSubmit)}
    >
      {/* Optional spinner if isSubmitting */}
      {isSubmitting && (
        <div style={{ textAlign: "center", marginBottom: "20px" }}>
          <div className="spinner"></div>
          <p>Processing transaction...</p>
        </div>
      )}

      <div className="form-fields-grid">
        {/* Transaction Type */}
        <div className="form-group">
          <label>Transaction Type:</label>
          <select
            className="form-control"
            value={currentType}
            onChange={onTransactionTypeChange}
            required
            disabled={!!transactionId} // if editing, lock the type
          >
            <option value="">Select Transaction Type</option>
            <option value="Deposit">Deposit</option>
            <option value="Withdrawal">Withdrawal</option>
            <option value="Transfer">Transfer</option>
            <option value="Buy">Buy</option>
            <option value="Sell">Sell</option>
          </select>
        </div>

        {/* Date & Time */}
        <div className="form-group">
          <label>Date & Time:</label>
          <input
            type="datetime-local"
            className="form-control"
            {...register("timestamp", { required: "Date & Time is required" })}
          />
          {errors.timestamp && (
            <span className="error-text">{errors.timestamp.message}</span>
          )}
        </div>

        {/* Now render all dynamic fields */}
        {renderDynamicFields()}
      </div>

      {/*
        For new transactions: Show a "Create" or "Save" button, etc.
        If you already have code for those, keep them.

        We'll show the Delete button only if transactionId is present (edit mode).
      */}

      {transactionId && (
        <div style={{ marginTop: "20px", textAlign: "right" }}>
          <button
            type="button"
            className="delete-button"
            onClick={handleDeleteClick}
            disabled={isSubmitting}
          >
            Delete Transaction
          </button>
        </div>
      )}
    </form>
  );
};

export default TransactionForm;