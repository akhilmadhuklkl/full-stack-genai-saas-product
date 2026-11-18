# AI review evaluations

Evaluation fixtures describe small projects where the expected review behavior is known.
They help us compare prompt versions and local models without relying on subjective judgment.

Each case contains:

- Source files
- Expected findings
- A short description of the behavior being tested

The current evaluation cases are offline fixtures. They do not call Ollama automatically.
The next evaluation step will add a bounded command that runs each case against the configured
model and stores a JSON result for comparison.

Run one case locally with:

```powershell
python evals/run_evals.py --case sql_injection --max-cases 1
```

Reports are written to `evals/results/latest.json`, which is intentionally ignored by Git.
