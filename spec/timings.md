# Measurements

November 22, 2026. Public seed 1, one million events and 250,000 requested clicks, eight worker threads in fast mode. The initial native Apple Silicon quick build took 0.168 s internally with a process RSS peak of 343,392,256 bytes. The local simple control used 391,872,512 bytes and took 0.355 s. Both outputs matched the 117,038 official user rows and 27,400 campaign rows. Docker Desktop amd64 emulation ran the same fast driver under a 512 MiB cgroup in 0.316 s internally with RSS of 252,993,536 bytes. These are development measurements on the public dataset. Official start-to-exit practice times are recorded separately.

The local test budget excludes the multi-gigabyte 20M, 60M and 120M workloads. The organizer runs hidden practice on its own machine. Local VM measurements for cold caches and the 120M stress test are outstanding.

In a seven-pair warm native development comparison on the same public data, sub-001 took a median of 90.15 ms from process start to exit. The second implementation took 68.61 ms. Each run's two outputs independently matched the official answer. With vector parsing, dense counters and parallel writes but the original per-bucket sort, the median was 75.34 ms. One launch of the hash-based executable took 473 ms, so this series alone does not establish the strict spread criterion for qualification on the final hardware.
