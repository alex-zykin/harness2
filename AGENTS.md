# Business fork working boundary

- Preserve the Google upstream license, attribution and benchmark behaviour.
- Business changes live in `harness2/business/`, `schemas/`, `examples/business/`,
  `scripts/business/` and their tests/docs; keep upstream changes minimal and reviewable.
- Default validation is deterministic and synthetic. No model/provider/mail calls,
  credential discovery, production data, host Codex execution or bypass flags.
- `HARNESS2_NO_DOTENV=1` must be set before importing upstream core in offline processes.
- Only `AGENTS.md` may be changed by a business prompt candidate. Tools, sender,
  permission, suppression, money and external effects stay owned by the product.
- Never promote an upstream candidate or prompt automatically. Record the reviewed
  upstream commit separately from the candidate, run offline checks and review the diff.
- Temporary output belongs in ignored `.run/` on the workspace drive.
- Run `python -B -m unittest discover -s tests -p 'test_*.py'` on Python 3.12/3.13;
  also exercise both deterministic demos from `docs/BUSINESS.md`.
