# Getting Started: Measuring Software Energy

This page explains what GreenBench does and why, using as little jargon as possible. You do not need to know anything about statistics or hardware.

## Why measure software energy?

Every program that runs uses electricity, and electricity has a carbon footprint. One run of one program is tiny. But software runs millions of times: on phones, in data centres, in your CI pipeline every night. Small differences add up. The hard part is that you can't _see_ the difference by looking at the code. You have to measure.

## Three units you will see

| Unit          | What it is                                                         | Everyday picture                                            |
| ------------- | ------------------------------------------------------------------ | ----------------------------------------------------------- |
| **Watt (W)**  | _Power_: how fast energy is being used right now                   | How bright a light bulb is                                  |
| **Joule (J)** | _Energy_: the total amount used (1 W for 1 second = 1 J)           | How long you left the bulb on, multiplied by its brightness |
| **gCO2e**     | _Carbon_: grams of CO2-equivalent produced making that electricity | Depends on the power grid (coal vs. hydro)                  |

GreenBench measures Watts many times a second, adds them up over the run to get Joules, and converts Joules to grams of CO2e using a **carbon intensity** (default 475 gCO2e per kWh, roughly a global average; 1 kWh = 3,600,000 J).

## Why one measurement is not enough

Run the same program twice and you will get two different energy numbers. Your laptop is doing other things, it warms up and slows down, the operating system gets in the way. This is **noise**.

So if version B measured 3% lower than version A _once_, that tells you nothing: it could easily be noise. To know whether B is really better we need to:

1. **Repeat** the measurement many times (we use 30 by default).
2. **Take turns** running A and B, in random order, so that things like a warming-up laptop affect both equally. Think of two runners alternating laps on the same track rather than one running all morning and the other all afternoon.
3. **Ask a statistics question**: "if A and B were actually identical, how surprising would it be to see a gap this big?" That is what the **p-value** answers.

## Reading the result

GreenBench prints a table like this (numbers invented):

```
Baseline Median Energy       95.1 J
Treatment Median Energy      24.0 J
Treatment Effect (median)   -74.8%   (95% CI -76.1% to -73.2%)
P(treatment run < baseline)  100%
Mann-Whitney p-value         0.00000
OUTCOME: Statistically significant difference detected
```

- **Median energy**: the "typical" run in each group.
- **Treatment effect**: how much more or less energy version B used. Negative = B used less. The **confidence interval (CI)** is the range of plausible values; a narrow one means a precise answer.
- **P(treatment run < baseline run)**: pick one random run from each group; how often is B lower? 50% means a coin flip (no difference), 100% means B always wins.
- **p-value**: the chance of seeing a gap at least this big _if there were really no difference_. By convention, below **0.05** is called "statistically significant".

Two things the p-value does **not** tell you:

- It does not tell you whether the difference _matters_. With enough runs, a 0.1% difference can be "significant". Look at the effect size and the CI too.
- A high p-value does not prove the versions are the same. It may just mean you didn't measure enough.

## The two charts

- **Distribution (box plot)**: each dot is one run; the box shows where the middle half of the runs fall. If the two boxes barely overlap, the groups differ clearly.
- **Stability over iterations**: energy of each run in order. A line drifting upwards means your machine was changing during the experiment, which is a reason to be careful with the result.

## Your first run

1. Install the tool and EnergiBridge: see the [README](../README.md#requirements).
2. Try the built-in example (two versions of an N-Queens solver). It prints the exact command it runs, so you can adapt it to your own project:

   ```bash
   green-bench demo
   ```

3. Open `green-bench-results/nqueens-demo/results.csv` and the PNG charts, and try to explain them in your own words.

## Glossary

- **Baseline / treatment**: the current version (A) and the version you want to test (B).
- **Workload**: the command being measured. It should do the same work every time.
- **Warm-up**: an unmeasured first run so caches are filled.
- **Cooldown**: a pause before each run so one run's heat doesn't leak into the next.
- **A/A test**: comparing a version with itself. A good "no difference" reference for how noisy your machine is.
- **Block randomization**: runs come in pairs (one A, one B) and the order inside each pair is random.
- **Operational emissions**: carbon from _running_ the software (not building the hardware).

## FAQ

**Can I trust the absolute numbers?** No. They include the whole machine and depend on your hardware. Trust the _comparison_ between A and B on the same machine in the same session.

**Why is it slow?** 30 runs × 2 versions × (cooldown + runtime). Use fewer runs (`-n 10`) and a shorter `--cooldown` for practice, never for a real conclusion.

**My result says "not significant". Did I fail?** No, that is a result: "no detectable difference at this sample size". If you expected a difference, try more runs or a longer workload.

**Does faster mean greener?** Often, but not always (for example, a parallel version may finish sooner yet draw much more power). That's why we measure.
