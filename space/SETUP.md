# Deploying this Space

Nothing here is deployed. These are the steps, for when the account exists.

1. Create a free account at https://huggingface.co (no card needed).

2. **New Space** → name `climatelens` → **SDK: Docker** → **Public**.

3. Push, with `space/` contents at the Space root:

   ```bash
   git clone https://huggingface.co/spaces/<user>/climatelens /tmp/hf-climatelens
   cd /tmp/hf-climatelens
   cp -r ~/climatelens/{climatelens,pyproject.toml,LICENSE} .
   cp ~/climatelens/space/{Dockerfile,README.md} .
   git add -A && git commit -m "climatelens" && git push
   ```

## Narration is off, in the image itself

The Dockerfile sets `CLIMATELENS_DISABLE_NARRATION=1`. Narration is the only
part of this application that costs money per visitor, and on a public
deployment that cost lands on whoever configured the key.

The flag is checked in two places — `available()`, which governs whether the
button appears, and `explain()` itself, because a client can post to the
endpoint regardless of what the page shows. With it set, no request reaches
Anthropic even if a key finds its way into the environment.

Every number on the page still works: it is all ERA5, CMIP6 and NOAA, over
keyless public APIs.

**Do not set an ANTHROPIC_API_KEY secret on this Space.**
