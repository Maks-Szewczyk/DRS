import os
import csv
import time
import statistics
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from azure.storage.blob import BlobServiceClient

# my url gotten from Azure, removed for submission.
function_url = ""
storage_connection_string = os.environ.get("AzureWebJobsStorage")
output_container = "processed-audio"
workload_sizes = [1, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 1500, 2000]
workers = 100
batch_timeout_seconds = 900
poll_interval_seconds = 2
summary_csv = "workload_summary.csv"

job = {
    "audio_file": "tuned_g_string.wav",
    "desired_note": "D4",
}

def submit_job(job_number):
    submitted_at = time.monotonic()
    response = requests.post(function_url, json=job, timeout=60)
    submit_latency = time.monotonic() - submitted_at
    if response.status_code not in (200, 202):
        return {
            "job_number": job_number,
            "job_id": None,
            "submitted_at": submitted_at,
            "submit_latency": submit_latency,
            "http_failure": True,
        }

    body = response.json()

    return {
        "job_number": job_number,
        "job_id": int(body["job_id"]),
        "submitted_at": submitted_at,
        "submit_latency": submit_latency,
        "http_failure": False,
    }

def work_done(results, blob_container, batch_start):
    pending = {row["job_id"]: row for row in results if row["job_id"] is not None}
    deadline = batch_start + batch_timeout_seconds

    while pending and time.monotonic() < deadline:
        for job_id, row in list(pending.items()):
            output_name = f"shifted_string_{job_id}.wav"
            blob = blob_container.get_blob_client(output_name)

            if blob.exists():
                row["completed"] = True
                row["latency"] = time.monotonic() - row["submitted_at"]
                del pending[job_id]

        if pending:
            time.sleep(poll_interval_seconds)

    return results

def run_workload(job_count, blob_container):
    print(f"\nRunning {job_count:,} jobs")
    batch_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=min(workers, job_count)) as executor:
        futures = [executor.submit(submit_job, number) for number in range(1, job_count + 1)]
        results = [future.result() for future in as_completed(futures)]

    for row in results:
        row["completed"] = False
        row["latency"] = None

    work_done(results, blob_container, batch_start)
    runtime = time.monotonic() - batch_start
    completed = sum(row["completed"] for row in results)
    completion_rate = completed / job_count * 100

    throughput = completed / runtime * 60 if runtime > 0 else 0
    latencies = [row["latency"] for row in results if row["latency"] is not None]
    mean_latency = statistics.mean(latencies) if latencies else 0
    http_failures = sum(row["http_failure"] for row in results)

    finished_data = {
        "Jobs": job_count,
        "Completed": completed,
        "Completion": f"{completion_rate:.1f}%",
        "Batch (s)": round(runtime, 1),
        "Throughput/min": round(throughput, 1),
        "Mean latency (s)": round(mean_latency, 1),
        "HTTP failures": http_failures,
    }

    print(finished_data)
    return finished_data

blob_service = BlobServiceClient.from_connection_string(storage_connection_string)
blob_container = blob_service.get_container_client(output_container)
summaries = []

for job_count in workload_sizes:
    summaries.append(run_workload(job_count, blob_container))

    if job_count != workload_sizes[-1]:
        time.sleep(10)

with open(summary_csv, "w", newline="", encoding="utf-8") as f:
    columns = ["Jobs", "Completed", "Completion", "Batch (s)", "Throughput/min", "Mean latency (s)", "HTTP failures"]
    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()
    writer.writerows(summaries)
