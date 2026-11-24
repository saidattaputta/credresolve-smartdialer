"""Small standard-library HTTP load smoke test for /health."""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")

    def request_once(_: int) -> float:
        started = time.perf_counter()
        with urlopen(args.url, timeout=10) as response:
            response.read()
            if response.status != 200:
                raise RuntimeError(f"Unexpected HTTP status: {response.status}")
        return time.perf_counter() - started

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        latencies = list(pool.map(request_once, range(args.requests)))
    elapsed = time.perf_counter() - started
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print(f"requests={args.requests} concurrency={args.concurrency}")
    print(f"elapsed_seconds={elapsed:.3f}")
    print(f"throughput_rps={args.requests / elapsed:.2f}")
    print(f"mean_latency_ms={statistics.mean(latencies) * 1000:.2f}")
    print(f"p95_latency_ms={p95 * 1000:.2f}")


if __name__ == "__main__":
    main()
