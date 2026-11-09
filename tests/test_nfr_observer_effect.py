# tests/test_nfr_observer_effect.py

import shutil
import subprocess
import time

import pytest

psutil = pytest.importorskip("psutil")

@pytest.mark.integration
@pytest.mark.skipif(shutil.which("energibridge") is None, reason="energibridge not installed")
def test_telemetry_cpu_overhead_limits(tmp_path):
    """Validates NFR-3.1: Active sampling must maintain < 2.0% CPU usage."""
    output_csv = tmp_path / "nfr_test.csv"
    
    # Define a 15-second dummy telemetry session at your default sampling interval
    eb_cmd = ["energibridge", "--output", str(output_csv), "--interval", "200", "sleep", "15"]
    
    # Spawn the process headlessly
    process = subprocess.Popen(eb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Allow the process a brief moment to initialize and hook into system registers
    time.sleep(1)
    
    cpu_readings = []
    try:
        ps_util_proc = psutil.Process(process.pid)
        
        # Collect CPU percentage readings across the lifecycle window
        while process.poll() is None:
            # interval=0.1 calculates percentage over a 100ms window
            cpu_percent = ps_util_proc.cpu_percent(interval=0.1)
            
            # Divide by CPU count if you want to measure total system capacity overhead
            # or keep it as per-core overhead depending on how your NFR is defined.
            total_cores = psutil.cpu_count()
            system_wide_overhead = cpu_percent / total_cores
            
            cpu_readings.append(system_wide_overhead)
    except psutil.NoSuchProcess:
        pass # Process finished executing early
    finally:
        process.wait()
        if output_csv.exists():
            output_csv.unlink() # Cleanup test artifact

    assert len(cpu_readings) > 0, "Telemetry engine failed to record data."
    
    mean_cpu_overhead = sum(cpu_readings) / len(cpu_readings)
    max_cpu_overhead = max(cpu_readings)
    
    print("\nNFR Diagnostic Overhead Profile:")
    print(f"   Mean System-Wide CPU Overhead: {mean_cpu_overhead:.3f}%")
    print(f"   Peak System-Wide CPU Overhead: {max_cpu_overhead:.3f}%")
    
    # Assert compliance against the 2.0% threshold requirement
    assert mean_cpu_overhead < 2.0, f"NFR-3.1 Violation! Mean overhead was {mean_cpu_overhead:.2f}%"
