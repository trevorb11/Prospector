"""
Batch processing module for handling large datasets efficiently.

This module provides optimized processing for large prospect lists,
including:
- Parallel processing with configurable workers
- Progress tracking and resumability
- Memory-efficient streaming
- Rate limiting and backoff
- Error handling and retry logic
- Result aggregation and export
"""

import os
import json
import time
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from queue import Queue, Empty
import csv

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batch processing."""
    # Parallelism
    max_workers: int = 10
    batch_size: int = 100

    # Rate limiting
    requests_per_minute: int = 60
    burst_limit: int = 10

    # Retry logic
    max_retries: int = 3
    retry_backoff_base: float = 2.0  # Exponential backoff multiplier
    retry_backoff_max: float = 60.0  # Maximum backoff seconds

    # Checkpointing
    checkpoint_interval: int = 50  # Save progress every N records
    checkpoint_dir: str = ".prospector_checkpoints"

    # Memory management
    stream_results: bool = True  # Write results as they complete
    max_queue_size: int = 1000

    # Timeouts
    task_timeout: float = 300.0  # 5 minutes per task


@dataclass
class BatchProgress:
    """Tracks batch processing progress."""
    total: int = 0
    completed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    retried: int = 0

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_checkpoint_at: Optional[datetime] = None

    current_rate: float = 0.0  # Records per second
    estimated_remaining: float = 0.0  # Seconds

    errors: List[Dict[str, Any]] = field(default_factory=list)

    def update(self, success: bool = True, retried: bool = False) -> None:
        """Update progress counters."""
        self.completed += 1
        if success:
            self.successful += 1
        else:
            self.failed += 1
        if retried:
            self.retried += 1

        # Calculate rate
        if self.started_at:
            elapsed = (datetime.now() - self.started_at).total_seconds()
            if elapsed > 0:
                self.current_rate = self.completed / elapsed
                remaining = self.total - self.completed
                self.estimated_remaining = remaining / self.current_rate if self.current_rate > 0 else 0

    def add_error(self, record_id: str, error: str) -> None:
        """Record an error."""
        self.errors.append({
            "record_id": record_id,
            "error": error,
            "timestamp": datetime.now().isoformat()
        })

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total": self.total,
            "completed": self.completed,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "retried": self.retried,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "current_rate": self.current_rate,
            "estimated_remaining": self.estimated_remaining,
            "error_count": len(self.errors)
        }


@dataclass
class BatchResult:
    """Result of batch processing."""
    progress: BatchProgress
    output_file: Optional[str] = None
    hot_file: Optional[str] = None
    errors_file: Optional[str] = None
    summary: Dict[str, Any] = field(default_factory=dict)


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts based on API responses.

    Automatically backs off when rate limits are hit and
    increases throughput when successful.
    """

    def __init__(self, initial_rpm: int = 60, burst_limit: int = 10):
        self.target_rpm = initial_rpm
        self.current_rpm = initial_rpm
        self.burst_limit = burst_limit
        self.min_rpm = 10
        self.max_rpm = initial_rpm * 2

        self.call_times: List[float] = []
        self.lock = threading.Lock()
        self.backoff_until: Optional[float] = None

        # Tracking for adaptation
        self.success_streak = 0
        self.rate_limit_count = 0

    def acquire(self) -> None:
        """Wait for rate limit slot."""
        with self.lock:
            now = time.time()

            # Check backoff
            if self.backoff_until and now < self.backoff_until:
                sleep_time = self.backoff_until - now
                logger.debug(f"Rate limit backoff: {sleep_time:.1f}s")
                time.sleep(sleep_time)
                self.backoff_until = None
                now = time.time()

            # Clean old calls
            self.call_times = [t for t in self.call_times if now - t < 60]

            # Check rate limit
            if len(self.call_times) >= self.current_rpm:
                sleep_time = 60 - (now - self.call_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    now = time.time()
                    self.call_times = [t for t in self.call_times if now - t < 60]

            # Check burst limit
            recent = [t for t in self.call_times if now - t < 1]
            if len(recent) >= self.burst_limit:
                time.sleep(1.0 / self.burst_limit)

            self.call_times.append(time.time())

    def report_success(self) -> None:
        """Report successful call - may increase rate."""
        with self.lock:
            self.success_streak += 1
            if self.success_streak >= 20 and self.current_rpm < self.max_rpm:
                self.current_rpm = min(self.current_rpm + 5, self.max_rpm)
                self.success_streak = 0
                logger.debug(f"Rate increased to {self.current_rpm} RPM")

    def report_rate_limit(self, retry_after: Optional[float] = None) -> None:
        """Report rate limit hit - back off."""
        with self.lock:
            self.rate_limit_count += 1
            self.success_streak = 0

            # Reduce rate
            self.current_rpm = max(self.current_rpm - 10, self.min_rpm)
            logger.warning(f"Rate limited - reduced to {self.current_rpm} RPM")

            # Set backoff
            backoff = retry_after or (30 if self.rate_limit_count < 3 else 60)
            self.backoff_until = time.time() + backoff

    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            "current_rpm": self.current_rpm,
            "target_rpm": self.target_rpm,
            "rate_limit_count": self.rate_limit_count,
            "success_streak": self.success_streak
        }


class CheckpointManager:
    """
    Manages checkpoints for resumable batch processing.

    Saves progress periodically so processing can be resumed
    after interruption.
    """

    def __init__(self, checkpoint_dir: str, job_id: str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)
        self.job_id = job_id
        self.checkpoint_file = self.checkpoint_dir / f"{job_id}.checkpoint.json"
        self.results_file = self.checkpoint_dir / f"{job_id}.results.jsonl"

    def save_checkpoint(self, progress: BatchProgress,
                        processed_ids: set,
                        pending_results: List[Dict[str, Any]]) -> None:
        """Save checkpoint for resumability."""
        checkpoint = {
            "job_id": self.job_id,
            "saved_at": datetime.now().isoformat(),
            "progress": progress.to_dict(),
            "processed_ids": list(processed_ids),
            "pending_count": len(pending_results)
        }

        # Atomic write
        temp_file = self.checkpoint_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(checkpoint, f)
        temp_file.replace(self.checkpoint_file)

        # Append pending results
        with open(self.results_file, 'a') as f:
            for result in pending_results:
                f.write(json.dumps(result) + '\n')

        progress.last_checkpoint_at = datetime.now()
        logger.info(f"Checkpoint saved: {progress.completed}/{progress.total}")

    def load_checkpoint(self) -> Optional[Tuple[BatchProgress, set]]:
        """Load checkpoint if exists."""
        if not self.checkpoint_file.exists():
            return None

        try:
            with open(self.checkpoint_file, 'r') as f:
                checkpoint = json.load(f)

            progress = BatchProgress(
                total=checkpoint["progress"]["total"],
                completed=checkpoint["progress"]["completed"],
                successful=checkpoint["progress"]["successful"],
                failed=checkpoint["progress"]["failed"],
                skipped=checkpoint["progress"]["skipped"],
                retried=checkpoint["progress"]["retried"]
            )

            processed_ids = set(checkpoint["processed_ids"])

            logger.info(f"Resumed from checkpoint: {progress.completed}/{progress.total}")
            return progress, processed_ids

        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def get_processed_results(self) -> Generator[Dict[str, Any], None, None]:
        """Stream previously processed results."""
        if self.results_file.exists():
            with open(self.results_file, 'r') as f:
                for line in f:
                    try:
                        yield json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue

    def cleanup(self) -> None:
        """Remove checkpoint files after completion."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
        if self.results_file.exists():
            self.results_file.unlink()


class ResultWriter:
    """
    Streams results to disk as they complete.

    Memory-efficient for large datasets.
    """

    def __init__(self, output_path: str, fieldnames: Optional[List[str]] = None):
        self.output_path = Path(output_path)
        self.fieldnames = fieldnames
        self._file = None
        self._writer = None
        self._lock = threading.Lock()
        self._header_written = False

    def __enter__(self):
        self._file = open(self.output_path, 'w', newline='', encoding='utf-8')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()

    def write(self, record: Dict[str, Any]) -> None:
        """Write a single record."""
        with self._lock:
            if not self._header_written:
                if not self.fieldnames:
                    self.fieldnames = list(record.keys())
                self._writer = csv.DictWriter(
                    self._file,
                    fieldnames=self.fieldnames,
                    extrasaction='ignore'
                )
                self._writer.writeheader()
                self._header_written = True

            self._writer.writerow(record)
            self._file.flush()


class BatchProcessor:
    """
    Main batch processor for large-scale prospect processing.

    Features:
    - Parallel execution with configurable workers
    - Adaptive rate limiting
    - Checkpointing for resumability
    - Streaming results to disk
    - Progress callbacks
    - Error handling and retry logic
    """

    def __init__(self, config: Optional[BatchConfig] = None):
        """
        Initialize batch processor.

        Args:
            config: Batch processing configuration
        """
        self.config = config or BatchConfig()
        self.rate_limiter = AdaptiveRateLimiter(
            initial_rpm=self.config.requests_per_minute,
            burst_limit=self.config.burst_limit
        )

    def process(self,
                records: List[Dict[str, Any]],
                processor_func: Callable[[Dict[str, Any]], Dict[str, Any]],
                output_file: str,
                id_field: str = "id",
                job_id: Optional[str] = None,
                resume: bool = True,
                progress_callback: Optional[Callable[[BatchProgress], None]] = None,
                hot_threshold: int = 70,
                score_field: str = "Score") -> BatchResult:
        """
        Process a batch of records.

        Args:
            records: List of records to process
            processor_func: Function to process each record
            output_file: Path to output CSV file
            id_field: Field to use as record ID
            job_id: Job ID for checkpointing
            resume: Whether to resume from checkpoint
            progress_callback: Optional callback for progress updates
            hot_threshold: Score threshold for hot prospects
            score_field: Field name for score

        Returns:
            BatchResult with processing results
        """
        job_id = job_id or f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        checkpoint_mgr = CheckpointManager(self.config.checkpoint_dir, job_id)

        # Initialize progress
        progress = BatchProgress(total=len(records))
        processed_ids: set = set()

        # Try to resume from checkpoint
        if resume:
            checkpoint = checkpoint_mgr.load_checkpoint()
            if checkpoint:
                progress, processed_ids = checkpoint

        progress.started_at = datetime.now()

        # Filter records to process
        records_to_process = [
            r for r in records
            if self._get_record_id(r, id_field) not in processed_ids
        ]

        # Prepare output files
        output_path = Path(output_file)
        hot_file = str(output_path.with_stem(output_path.stem + "_HOT"))
        errors_file = str(output_path.with_stem(output_path.stem + "_errors"))

        # Results collection
        all_results: List[Dict[str, Any]] = []
        hot_results: List[Dict[str, Any]] = []
        pending_results: List[Dict[str, Any]] = []

        # Load previously processed results if resuming
        if resume and processed_ids:
            for result in checkpoint_mgr.get_processed_results():
                all_results.append(result)
                if result.get(score_field, 0) >= hot_threshold:
                    hot_results.append(result)

        try:
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                # Submit all tasks
                futures: Dict[Future, Dict[str, Any]] = {}

                for record in records_to_process:
                    # Apply rate limiting
                    self.rate_limiter.acquire()

                    future = executor.submit(
                        self._process_with_retry,
                        processor_func,
                        record,
                        self.config.max_retries
                    )
                    futures[future] = record

                # Process completed tasks
                for future in as_completed(futures):
                    record = futures[future]
                    record_id = self._get_record_id(record, id_field)

                    try:
                        result, was_retried = future.result(timeout=self.config.task_timeout)

                        if result:
                            all_results.append(result)
                            pending_results.append(result)

                            if result.get(score_field, 0) >= hot_threshold:
                                hot_results.append(result)

                            processed_ids.add(record_id)
                            progress.update(success=True, retried=was_retried)
                            self.rate_limiter.report_success()
                        else:
                            progress.update(success=False)
                            progress.add_error(str(record_id), "Processing returned None")

                    except Exception as e:
                        progress.update(success=False)
                        progress.add_error(str(record_id), str(e))
                        logger.error(f"Failed to process {record_id}: {e}")

                        if "rate limit" in str(e).lower():
                            self.rate_limiter.report_rate_limit()

                    # Progress callback
                    if progress_callback:
                        progress_callback(progress)

                    # Checkpoint periodically
                    if len(pending_results) >= self.config.checkpoint_interval:
                        checkpoint_mgr.save_checkpoint(progress, processed_ids, pending_results)
                        pending_results = []

            # Final checkpoint
            if pending_results:
                checkpoint_mgr.save_checkpoint(progress, processed_ids, pending_results)

        except KeyboardInterrupt:
            logger.info("Processing interrupted - saving checkpoint")
            checkpoint_mgr.save_checkpoint(progress, processed_ids, pending_results)
            raise

        progress.completed_at = datetime.now()

        # Write final output files
        self._write_results(all_results, output_file)

        if hot_results:
            self._write_results(hot_results, hot_file)

        if progress.errors:
            self._write_errors(progress.errors, errors_file)

        # Cleanup checkpoint on success
        if progress.failed == 0:
            checkpoint_mgr.cleanup()

        # Build result
        return BatchResult(
            progress=progress,
            output_file=output_file,
            hot_file=hot_file if hot_results else None,
            errors_file=errors_file if progress.errors else None,
            summary={
                "total_processed": progress.completed,
                "successful": progress.successful,
                "failed": progress.failed,
                "hot_prospects": len(hot_results),
                "processing_time": (progress.completed_at - progress.started_at).total_seconds()
                    if progress.started_at and progress.completed_at else 0,
                "rate_limiter_stats": self.rate_limiter.get_stats()
            }
        )

    def _get_record_id(self, record: Dict[str, Any], id_field: str) -> str:
        """Get record identifier."""
        if id_field in record:
            return str(record[id_field])
        # Fallback to hash of record
        return str(hash(json.dumps(record, sort_keys=True, default=str)))

    def _process_with_retry(self,
                           processor_func: Callable[[Dict[str, Any]], Dict[str, Any]],
                           record: Dict[str, Any],
                           max_retries: int) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Process with retry logic."""
        last_error = None
        was_retried = False

        for attempt in range(max_retries + 1):
            try:
                result = processor_func(record)
                return result, was_retried

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    was_retried = True
                    backoff = min(
                        self.config.retry_backoff_base ** attempt,
                        self.config.retry_backoff_max
                    )
                    logger.warning(f"Retry {attempt + 1}/{max_retries} after {backoff}s: {e}")
                    time.sleep(backoff)

        raise last_error

    def _write_results(self, results: List[Dict[str, Any]], output_file: str) -> None:
        """Write results to CSV."""
        if not results:
            return

        fieldnames = list(results[0].keys())

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(results)

        logger.info(f"Wrote {len(results)} records to {output_file}")

    def _write_errors(self, errors: List[Dict[str, Any]], output_file: str) -> None:
        """Write errors to file."""
        with open(output_file, 'w') as f:
            json.dump(errors, f, indent=2)

        logger.info(f"Wrote {len(errors)} errors to {output_file}")

    def process_stream(self,
                       record_generator: Generator[Dict[str, Any], None, None],
                       processor_func: Callable[[Dict[str, Any]], Dict[str, Any]],
                       output_file: str,
                       total_estimate: Optional[int] = None,
                       progress_callback: Optional[Callable[[BatchProgress], None]] = None) -> BatchResult:
        """
        Process records from a generator (memory-efficient streaming).

        Args:
            record_generator: Generator yielding records
            processor_func: Function to process each record
            output_file: Path to output CSV file
            total_estimate: Estimated total records
            progress_callback: Optional callback for progress updates

        Returns:
            BatchResult with processing results
        """
        progress = BatchProgress(total=total_estimate or 0)
        progress.started_at = datetime.now()

        results_queue: Queue = Queue(maxsize=self.config.max_queue_size)
        completed = threading.Event()
        writer_error = None

        # Background writer thread
        def writer_thread():
            nonlocal writer_error
            fieldnames = None
            try:
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = None
                    while True:
                        try:
                            result = results_queue.get(timeout=1)
                            if result is None:  # Sentinel
                                break

                            if writer is None:
                                fieldnames = list(result.keys())
                                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                                writer.writeheader()

                            writer.writerow(result)
                            f.flush()
                            results_queue.task_done()

                        except Empty:
                            if completed.is_set():
                                break

            except Exception as e:
                writer_error = e
                logger.error(f"Writer thread error: {e}")

        # Start writer
        writer = threading.Thread(target=writer_thread, daemon=True)
        writer.start()

        try:
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                futures: Dict[Future, int] = {}
                record_count = 0

                # Submit initial batch
                for record in record_generator:
                    record_count += 1
                    progress.total = max(progress.total, record_count)

                    self.rate_limiter.acquire()

                    future = executor.submit(processor_func, record)
                    futures[future] = record_count

                    # Process completed futures
                    done_futures = [f for f in futures if f.done()]
                    for future in done_futures:
                        try:
                            result = future.result()
                            if result:
                                results_queue.put(result)
                                progress.update(success=True)
                            else:
                                progress.update(success=False)
                        except Exception as e:
                            progress.update(success=False)
                            logger.error(f"Processing error: {e}")

                        del futures[future]

                        if progress_callback:
                            progress_callback(progress)

                # Wait for remaining futures
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result:
                            results_queue.put(result)
                            progress.update(success=True)
                        else:
                            progress.update(success=False)
                    except Exception as e:
                        progress.update(success=False)
                        logger.error(f"Processing error: {e}")

                    if progress_callback:
                        progress_callback(progress)

        finally:
            completed.set()
            results_queue.put(None)  # Sentinel
            writer.join()

        progress.completed_at = datetime.now()

        if writer_error:
            raise writer_error

        return BatchResult(
            progress=progress,
            output_file=output_file,
            summary={
                "total_processed": progress.completed,
                "successful": progress.successful,
                "failed": progress.failed,
                "processing_time": (progress.completed_at - progress.started_at).total_seconds()
                    if progress.started_at and progress.completed_at else 0
            }
        )


def create_enrichment_processor(contact_enricher=None, signal_analyzer=None):
    """
    Create a processor function that enriches prospects.

    Args:
        contact_enricher: ContactEnricher instance
        signal_analyzer: FundingSignalAnalyzer instance

    Returns:
        Processor function for BatchProcessor
    """
    def processor(record: Dict[str, Any]) -> Dict[str, Any]:
        result = record.copy()

        # Contact enrichment
        if contact_enricher:
            contact_info = contact_enricher.enrich(
                company_name=record.get("Company Name", record.get("company_name", "")),
                domain=record.get("Website", record.get("website")),
                city=record.get("City", record.get("city")),
                state=record.get("State", record.get("state")),
                phone=record.get("Phone", record.get("phone"))
            )

            # Merge contact data
            if contact_info.primary_email and not result.get("Email"):
                result["Email"] = contact_info.primary_email
            if contact_info.primary_phone and not result.get("Phone"):
                result["Phone"] = contact_info.primary_phone
            if contact_info.linkedin_company_url:
                result["LinkedIn"] = contact_info.linkedin_company_url
            if contact_info.company_website and not result.get("Website"):
                result["Website"] = contact_info.company_website

            # Add decision makers
            if contact_info.decision_makers:
                dm = contact_info.decision_makers[0]
                result["Contact Name"] = dm.get("name", "")
                result["Contact Title"] = dm.get("title", "")
                result["Contact Email"] = dm.get("email", "")
                result["Contact LinkedIn"] = dm.get("linkedin_url", "")

            result["Enrichment Confidence"] = contact_info.confidence_score
            result["Enrichment Sources"] = ", ".join(contact_info.sources_used)

        # Funding signals
        if signal_analyzer:
            report = signal_analyzer.analyze(
                company_name=record.get("Company Name", record.get("company_name", "")),
                state=record.get("State", record.get("state")),
                industry=record.get("Industry", record.get("industry"))
            )

            if report.signals:
                result["Funding Signals"] = "; ".join(s.signal_name for s in report.signals[:3])
                result["Funding Signal Count"] = len(report.signals)
                result["Funding Likelihood"] = report.funding_likelihood

                # Add to score
                current_score = result.get("Score", 0)
                result["Score"] = current_score + report.total_score_boost
                result["Signal Score Boost"] = report.total_score_boost

                # Recommendations
                result["Recommended Products"] = ", ".join(report.recommended_products[:2])
                result["Recommended Timing"] = report.recommended_timing

        return result

    return processor
