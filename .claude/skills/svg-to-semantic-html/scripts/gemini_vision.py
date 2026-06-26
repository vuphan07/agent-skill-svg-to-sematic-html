#!/usr/bin/env python3
"""Minimal, self-contained Gemini vision client for the verify step.

This skill needs exactly ONE capability from a multimodal API: "look at this
image and describe the differences". So rather than depend on a separate
multimodal skill (and all its video/music/MiniMax/OpenRouter machinery), we
vendor just the vision-analyze call here. One dependency: `google-genai`.

    pip install google-genai
    # key resolved from env GEMINI_API_KEY, or a .env in: this skill dir,
    # the project root, or ~/.claude/.env  (see .env.example)

Use:
    from gemini_vision import analyze, available
    if available():
        text = analyze("crop.png", "List the visual differences as JSON.")

Or as a CLI (handy for a one-off manual check):
    python gemini_vision.py crop.png --prompt "what differs between the halves?"
"""
import os
import sys
import mimetypes

DEFAULT_MODEL = os.getenv("MULTIMODAL_MODEL", "gemini-2.5-flash")

_ENV_LOADED = False


def _load_env_once():
    """Populate GEMINI_API_KEY from the first .env that has it. Cheap KEY=VALUE
    parser (no python-dotenv dependency). Search order favours the project, then
    the user's global config."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    here = os.path.dirname(os.path.abspath(__file__))
    skill = os.path.dirname(here)
    candidates = [
        os.path.join(skill, ".env"),                       # this skill (primary)
        os.path.join(os.getcwd(), ".env"),                 # project root
        os.path.expanduser("~/.claude/.env"),              # global
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            pass


def _api_key():
    _load_env_once()
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def available():
    """True if we can actually call Gemini (package + key present)."""
    if not _api_key():
        return False
    try:
        import google.genai  # noqa: F401
        return True
    except Exception:
        return False


def analyze(image_path, prompt, model=DEFAULT_MODEL):
    """Send one image + a text prompt to Gemini; return the model's text.
    Raises RuntimeError with a clear message if the package/key is missing."""
    key = _api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found (env or .env). See .env.example.")
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        raise RuntimeError(f"google-genai not installed (pip install google-genai): {e}")

    with open(image_path, "rb") as f:
        data = f.read()
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=data, mime_type=mime), prompt],
    )
    return (resp.text or "").strip()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Minimal Gemini vision analyze")
    ap.add_argument("image")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    try:
        print(analyze(a.image, a.prompt, a.model))
    except RuntimeError as e:
        print(f"[gemini_vision] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
