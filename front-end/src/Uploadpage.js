import { useState, useRef } from "react";
import { v4 as uuidv4 } from "uuid";
import "./Uploadpage.css";

const Uploadpage = () => {
  const [fileName, setFileName] = useState(null);
  const [resultsJSON, setResultsJSON] = useState(null);
  const fileInputRef = useRef();
  const [isProcessing, setIsProcessing] = useState(false);

  // API URL for uploading the PDF to Lambda 0
  const API_URL =
    "https://l83auaa4j8.execute-api.us-east-2.amazonaws.com/upload";

  // API URL to fetch the results json from Lambda 4
  const API_GET_URL =
    "https://l83auaa4j8.execute-api.us-east-2.amazonaws.com/testjson";

  // Opens the file selector dialog
  const handleButtonClick = () => {
    fileInputRef.current.click();
  };

  const handleReset = () => {
    setFileName(null);
    setResultsJSON(null);
    setIsProcessing(false);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  // For fetching the results json
  const fetchResultsWithRetry = async (
    jobIdToCheck,
    retries = 6,
    delay = 30000
  ) => {
    for (let i = 0; i < retries; i++) {
      try {
        const response = await fetch(`${API_GET_URL}?jobId=${jobIdToCheck}`, {
          method: "GET",
          headers: { "Content-Type": "application/json" },
        });

        if (response.ok) {
          const data = await response.json();
          setResultsJSON(data);
          setIsProcessing(false);
          console.log("Fetched JSON:", data);
          return;
        } else if (response.status === 404) {
          console.log("Made An Attempt: JSON Not ready yet");
        } else {
          console.error("Error fetching JSON: ", response.statusText);
          break;
        }
      } catch (err) {
        console.error("Fetch error:", err);
      }

      await new Promise((res) => setTimeout(res, delay));
    }

    alert("Failed to fetch the results after multiple attempts");
  };

  // Handles the PDF upload
  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (file) {
      if (file.type !== "application/pdf") {
        alert(
          "Invalid file type. Please upload your medical bill in PDF format."
        );
        event.target.value = "";
        return;
      }

      setFileName(file.name);
      const newJobId = uuidv4();
      console.log("selected file:", file);
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = async () => {
        const base64Data = reader.result.split(",")[1];
        try {
          const response = await fetch(API_URL, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              job_id: newJobId,
              file_name: file.name,
              file_content: base64Data,
            }),
          });

          const data = await response.json();
          console.log("server response:", data);

          if (!response.ok) {
            alert(
              data.error || data.message || "Upload Failed. Lambda had an error"
            );
            return;
          }

          alert(data.message || "Upload Complete!");

          setIsProcessing(true);

          fetchResultsWithRetry(newJobId);
        } catch (err) {
          console.error("Upload error:", err);
          alert("Failed to upload file");
        }
      };
    }
  };

  // Filters the json (removes characters like '{}', '[]', '""', and commas)
  const renderJSON = (data, indent = 0) => {
    return Object.entries(data).map(([key, value]) => {
      const padding = " ".repeat(indent * 2);
      const displayKey = key
        .replaceAll("_", " ")
        .split(" ")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");

      if (key === "coverage_analysis" && Array.isArray(value)) {
        return (
          <div key={key} style={{ marginTop: "20px", padding: "16px" }}>
            <h3 style={{ textAlign: "center" }}>Coverage Analysis</h3>

            <table className="coverage-table">
              <thead>
                <tr>
                  <th>Procedure</th>
                  <th>CPT Code</th>
                  <th>Billed</th>
                  <th>Covered</th>
                  <th>Coverage Type</th>
                  <th>Deductible Applies</th>
                  <th>Deductible Amount</th>
                  <th>Coinsurance Rate</th>
                  <th>Patient Responsibility</th>
                  <th>Insurance Pays</th>
                  <th>Explanation</th>
                </tr>
              </thead>
              <tbody>
                {value.map((proc, i) => (
                  <tr key={i}>
                    <td>{proc.procedure}</td>
                    <td>{proc.cpt_code}</td>
                    <td>{proc.billed_amount}</td>
                    <td>{proc.covered ? "Yes" : "No"}</td>
                    <td>{proc.coverage_type}</td>
                    <td>{proc.deductible_applies ? "Yes" : "No"}</td>
                    <td>{proc.deductible_amount}</td>
                    <td>{proc.coinsurance_rate}</td>
                    <td>{proc.patient_responsibility}</td>
                    <td>{proc.insurance_pays}</td>
                    <td>{proc.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }

      if (typeof value === "object" && value !== null) {
        return (
          <div key={key} style={{ marginLeft: indent * 10 }}>
            <p>
              {padding}
              <strong>{displayKey}:</strong>
            </p>
            {Array.isArray(value)
              ? value.map((item, i) => (
                  <div key={i} style={{ marginLeft: (indent + 1) * 10 }}>
                    {typeof item === "object"
                      ? renderJSON(item, indent + 2)
                      : item.toString()}
                  </div>
                ))
              : renderJSON(value, indent + 1)}
          </div>
        );
      } else {
        return (
          <p key={key} style={{ marginLeft: indent * 10 }}>
            {padding}
            <strong>{displayKey}:</strong>{" "}
            {value !== null && value !== undefined ? value.toString() : "null"}
          </p>
        );
      }
    });
  };

  return (
    <div className="uploadpage">
      <h2 style={{ textAlign: "left", padding: "16px" }}>Upload Page</h2>
      <p>
        <strong>
          When uploading the medical bills for adjudication make sure:
        </strong>
      </p>
      <p>
        <strong>File Format:</strong> PDF Only
      </p>
      <p>
        <strong>Maximum Pages:</strong> 3 Pages Per Bill
      </p>
      <button className="outline-btn" onClick={handleButtonClick}>
        Upload Bill
      </button>

      <input
        type="file"
        ref={fileInputRef}
        style={{ display: "none" }}
        onChange={handleFileChange}
        accept="application/pdf"
      />

      {fileName && <p>Selected file: {fileName}</p>}

      {isProcessing && !resultsJSON && (
        <p style={{ fontWeight: "bold", padding: "16px" }}>Processing...</p>
      )}

      {fileName && resultsJSON && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "20px",
            padding: "16px",
          }}
        >
          {/* Results JSON (top)*/}
          <div
            className="fade-block"
            style={{
              flex: 1,
              overflowY: "auto",
              border: "1px solid #ccc",
              textAlign: "left",
              padding: "16px",
            }}
          >
            <h3 style={{ textAlign: "center" }}>Adjudication Results</h3>
            {renderJSON(resultsJSON)}
          </div>

          {/* PDF Viewer (below) */}
          <div style={{ border: "1px solid #ccc", height: "800px" }}>
            <iframe
              src={URL.createObjectURL(fileInputRef.current.files[0])}
              style={{ width: "100%", height: "100%" }}
              title="Uploaded PDF"
            ></iframe>
          </div>

          {/* Submit a New Bill Button */}
          <button
            className="outline-btn"
            onClick={handleReset}
            style={{ alignSelf: "center" }}
          >
            Upload a New Bill
          </button>
        </div>
      )}
    </div>
  );
};

export default Uploadpage;
