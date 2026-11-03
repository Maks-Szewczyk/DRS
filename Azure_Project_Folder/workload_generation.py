
import os
import csv
import json
import time
import statistics
import requests

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from azure.storage.blob import BlobServiceClient


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

FUNCTION_URL = "https://YOUR-APP.azurewebsites.net/api/submit_note"
FUNCTION_KEY = ""  # Set this if your HTTP function requires a key.

# Must be a connection string with access to the processed-audio container.
STORAGE_CONNECTION_STRING = os.environ.get("AzureWebJobsStorage", "")

OUTPUT_CONTAINER = "processed-audio"

# Requested workload sizes
WORKLOAD_SIZES = [1, 10, 50, 100]

# Maximum simultaneous HTTP submissions.
# Increase gradually; 10,000 workers would use excessive resources.
MAX_WORKERS = 100

# Maximum time allowed for each workload batch to finish.
BATCH_TIMEOUT_SECONDS = 900

# How often to check for output files.
POLL_INTERVAL_SECONDS = 2

SUMMARY_CSV = "workload_summary.csv"
DETAIL_CSV = "workload_job_details.csv"

# Input blobs must already exist in ready-audio.
JOBS = [
    {"audio_file": "tuned_g_string.wav", "desired_note": "D4"},
]


# --------------------------------------------------
# SUBMIT ONE JOB
# --------------------------------------------------

def submit_job(job_number):
    job = JOBS[(job_number - 1) % len(JOBS)]

    headers = {"Content-Type": "application/json"}

    if FUNCTION_KEY:
        headers["x-functions-key"] = FUNCTION_KEY

    submitted_at = time.monotonic()
    submitted_utc = datetime.now(timezone.utc).isoformat()

    result = {
        "job_number": job_number,
        "audio_file": job["audio_file"],
        "desired_note": job["desired_note"],
        "job_id": None,
        "submitted_at_monotonic": submitted_at,
        "submitted_utc": submitted_utc,
        "submit_latency_seconds": None,
        "submit_status": None,
        "submit_error": "",
        "completed_at_monotonic": None,
        "processing_latency_seconds": None,
        "completed": False,
        "timed_out": False,
    }

    try:
        response = requests.post(
            FUNCTION_URL,
            json=job,
            headers=headers,
            timeout=60,
        )

        result["submit_latency_seconds"] = (
            time.monotonic() - submitted_at
        )
        result["submit_status"] = response.status_code

        if response.status_code not in (200, 202):
            result["submit_error"] = (
                f"HTTP {response.status_code}: {response.text[:300]}"
            )
            return result

        try:
            body = response.json()
            result["job_id"] = int(body["job_id"])
        except (ValueError, KeyError, TypeError):
            result["submit_error"] = (
                "Successful HTTP response did not contain a numeric job_id."
            )

    except requests.RequestException as error:
        result["submit_latency_seconds"] = (
            time.monotonic() - submitted_at
        )
        result["submit_error"] = str(error)

    return result


# --------------------------------------------------
# WAIT FOR OUTPUT FILES
# --------------------------------------------------

def wait_for_completion(results, blob_container, batch_start):
    pending = {
        row["job_id"]: row
        for row in results
        if row["job_id"] is not None
    }

    deadline = batch_start + BATCH_TIMEOUT_SECONDS

    while pending and time.monotonic() < deadline:
        for job_id, row in list(pending.items()):
            output_name = f"shifted_string_{job_id}.wav"

            try:
                blob = blob_container.get_blob_client(output_name)

                if blob.exists():
                    completed_at = time.monotonic()

                    row["completed"] = True
                    row["completed_at_monotonic"] = completed_at
                    row["processing_latency_seconds"] = (
                        completed_at - row["submitted_at_monotonic"]
                    )

                    del pending[job_id]

            except Exception as error:
                # Keep polling; transient storage errors may recover.
                row["poll_error"] = str(error)

        if pending:
            time.sleep(POLL_INTERVAL_SECONDS)

    # Anything still pending at the deadline has timed out.
    for row in pending.values():
        row["timed_out"] = True

    return results


# --------------------------------------------------
# RUN ONE WORKLOAD SIZE
# --------------------------------------------------

def run_workload(job_count, blob_container):
    print(f"\nStarting workload with {job_count:,} jobs")

    batch_start = time.monotonic()
    results = []

    with ThreadPoolExecutor(
        max_workers=min(MAX_WORKERS, job_count)
    ) as executor:

        futures = [
            executor.submit(submit_job, number)
            for number in range(1, job_count + 1)
        ]

        for future in as_completed(futures):
            results.append(future.result())

    # Include submission failures in the final submitted-job count.
    results.sort(key=lambda row: row["job_number"])

    # Wait for all accepted jobs with known IDs to produce output blobs.
    wait_for_completion(results, blob_container, batch_start)

    batch_end = time.monotonic()
    batch_duration = batch_end - batch_start

    submitted = len(results)
    completed = sum(row["completed"] for row in results)
    timeouts = sum(row["timed_out"] for row in results)

    completion_rate = completed / submitted if submitted else 0
    throughput = (
        completed / batch_duration * 60
        if batch_duration > 0
        else 0
    )

    completed_latencies = [
        row["processing_latency_seconds"]
        for row in results
        if row["completed"]
        and row["processing_latency_seconds"] is not None
    ]

    mean_latency = (
        statistics.mean(completed_latencies)
        if completed_latencies
        else None
    )

    summary = {
        "workload_size": job_count,
        "submitted_jobs": submitted,
        "completed_jobs": completed,
        "completion_rate": round(completion_rate, 4),
        "batch_duration_seconds": round(batch_duration, 3),
        "throughput_jobs_per_minute": round(throughput, 3),
        "mean_latency_seconds": (
            round(mean_latency, 3)
            if mean_latency is not None
            else ""
        ),
        "timeouts": timeouts,
        "submission_failures": sum(
            1 for row in results
            if row["submit_error"]
        ),
        "missing_job_ids": sum(
            1 for row in results
            if row["job_id"] is None
        ),
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }

    print(json.dumps(summary, indent=2))

    return summary, results


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    if "YOUR-APP" in FUNCTION_URL:
        raise ValueError("Set FUNCTION_URL to your deployed function URL.")

    if not STORAGE_CONNECTION_STRING:
        raise ValueError(
            "Set AzureWebJobsStorage in the environment before running."
        )

    blob_service = BlobServiceClient.from_connection_string(
        STORAGE_CONNECTION_STRING
    )

    blob_container = blob_service.get_container_client(OUTPUT_CONTAINER)

    all_summaries = []
    all_details = []

    for job_count in WORKLOAD_SIZES:
        summary, details = run_workload(job_count, blob_container)

        all_summaries.append(summary)

        for row in details:
            # Remove monotonic clock values from exported results.
            row.pop("submitted_at_monotonic", None)
            row.pop("completed_at_monotonic", None)
            all_details.append(row)

        # Allow the previous workload's queue to settle before the next.
        if job_count != WORKLOAD_SIZES[-1]:
            print("Pausing 10 seconds before the next workload...")
            time.sleep(10)

    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(all_summaries[0].keys())
        )
        writer.writeheader()
        writer.writerows(all_summaries)

    detail_fields = sorted({
        key for row in all_details for key in row.keys()
    })

    with open(DETAIL_CSV, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(all_details)

    print(f"\nSummary saved to {SUMMARY_CSV}")
    print(f"Per-job details saved to {DETAIL_CSV}")


if __name__ == "__main__":
    main()
