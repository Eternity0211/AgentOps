# Local Compose secrets

Copy `.env.example` to `.env`, then create the four runtime `.txt` files referenced there with
distinct, non-empty local-only credentials. The evaluation-only Ground Truth credential is a fifth
file and is required only for isolated evaluation Compose runs. Files matching `secrets/*.txt` are
ignored by Git. Do not reuse production, personal, or shared credentials in this lab. Run
`python scripts/dev.py doctor` to validate paths and file bounds without printing secret contents.
