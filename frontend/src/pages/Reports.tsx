import React, { useState } from "react";
import { downloadPdfWithAxios } from "../api";
import "../styles/reports.css"; // Our spinner CSS is also in here

// Hardcoded base URL for your FastAPI server:
const API_BASE = "http://localhost:8000";

// Example list of possible reports
const REPORTS = [
  {
    key: "completeTax",
    label: "Complete Tax Report",
    endpoint: "/api/reports/complete_tax_report",
    pdfOnly: true,
  },
  {
    key: "irsReports",
    label: "IRS Reports (Form 8949, Schedule D, etc.)",
    endpoint: "/api/reports/irs_reports",
    pdfOnly: true,
  },
  {
    
    // to "/api/reports/simple_transaction_history"
    key: "transactionHistory",
    label: "Transaction History",
    endpoint: "/api/reports/simple_transaction_history",
    pdfOnly: false,
  },
];

const Reports: React.FC = () => {
  // Default to Complete Tax (PDF)
  const [selectedReport, setSelectedReport] = useState<string>("completeTax");
  const [taxYear, setTaxYear] = useState<string>("");
  const [format, setFormat] = useState<string>("pdf");

  // Loading states for the spinner & progress
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [progress, setProgress] = useState<number>(0);

  const handleExport = async () => {
    // Basic validation
    if (!taxYear) {
      alert("Please enter a valid year (e.g. 2024).");
      return;
    }
    const reportDef = REPORTS.find((r) => r.key === selectedReport);
    if (!reportDef) {
      alert("Invalid report selection.");
      return;
    }

    // If it's PDF-only but user selected CSV, override
    let finalFormat = format;
    if (reportDef.pdfOnly && format === "csv") {
      finalFormat = "pdf";
    }

    // Build final URL
    const url = `${API_BASE}${reportDef.endpoint}?year=${taxYear}&format=${finalFormat}`;

    setIsLoading(true);
    setProgress(0);

    try {
      // 1) Download as Blob with onProgress
      const blob = await downloadPdfWithAxios(url, (percent) => {
        setProgress(percent);
      });

      // 2) Build a filename
      const safeLabel = reportDef.label.replace(/\s+/g, "");
      const fileExt = finalFormat.toLowerCase();
      const fileName = `${safeLabel}_${taxYear}.${fileExt}`;

      // 3) Create a temporary link to force download
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(blobUrl);

    } catch (error) {
      console.error("Error generating report:", error);
      alert("Failed to generate the report. Check console for details.");
    } finally {
      setIsLoading(false);
    }
  };

  // ------------------------------------------------------------
  // We removed the user-selectable dropdown for format.
  // Instead, we auto-set "csv" if Transaction History is chosen,
  // otherwise "pdf".
  // ------------------------------------------------------------

  return (
    <div className="reports-container">
      <h2 className="reports-title">Reports</h2>
      <p className="reports-description">
        Generate or view financial and tax reports. ...
      </p>

      <div className="reports-section">
        <div className="input-group">
          <label>Tax Year:</label>
          <input
            type="text"
            className="report-year-input"
            placeholder="e.g. 2024"
            value={taxYear}
            onChange={(e) => setTaxYear(e.target.value)}
          />

          {/* 
             Removed the <select> for Format. 
             We now show a read-only field to reflect the auto-chosen format.
          */}
          <label>Format:</label>
          <input
            type="text"
            className="report-format-input"
            readOnly
            value={format}
          />

          {/*
          // Original <select> block for reference (commented out):
          // <select
          //   value={format}
          //   onChange={(e) => setFormat(e.target.value)}
          //   className="report-format-select"
          // >
          //   <option value="pdf">PDF</option>
          //   <option value="csv">CSV</option>
          // </select>
          */}
        </div>

        {/* Radio buttons for which report */}
        <div className="report-selection">
          {REPORTS.map((r) => (
            <div key={r.key} className="report-radio">
              <input
                type="radio"
                id={r.key}
                name="report"
                value={r.key}
                checked={selectedReport === r.key}
                onChange={() => {
                  setSelectedReport(r.key);
                  // If transactionHistory => CSV, else PDF
                  if (r.key === "transactionHistory") {
                    setFormat("csv");
                  } else {
                    setFormat("pdf");
                  }
                }}
              />
              <label htmlFor={r.key}>{r.label}</label>
            </div>
          ))}
        </div>

        {/* Export Button */}
        <div className="report-actions">
          <button className="report-button" onClick={handleExport}>
            Export
          </button>
        </div>

        {/* Spinner + progress UI pinned to bottom-left of the card */}
        {isLoading && (
          <div className="downloading-overlay">
            <span>
              {progress > 0 ? `Downloading... ${progress}%` : "Downloading..."}
            </span>
            <div className="spinner" />
          </div>
        )}
      </div>
    </div>
  );
};

export default Reports;