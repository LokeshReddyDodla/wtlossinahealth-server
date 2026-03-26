#!/usr/bin/env python3
"""Upload all local .md prompts to Langfuse Prompt Management.

Run once to seed Langfuse with current prompts. After that, edit in the dashboard.

Usage:
    python scripts/upload_prompts_to_langfuse.py

Requires env vars:
    LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from langfuse import Langfuse
from lib.ai_foundation.prompts.loader import load_prompt_directory


def main():
    # Initialize Langfuse
    langfuse = Langfuse(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        host=os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
    )

    # Find all prompt directories
    agents_dir = Path("lib/ai_foundation/agents")
    uploaded = 0

    for agent_dir in sorted(agents_dir.iterdir()):
        prompts_dir = agent_dir / "prompts"
        if not prompts_dir.is_dir():
            continue

        templates = load_prompt_directory(prompts_dir)
        for template in templates:
            name = template.meta.name
            body = template.body

            try:
                langfuse.create_prompt(
                    name=name,
                    prompt=body,
                    labels=["production"],
                )
                print(f"  ✅ {name}")
                uploaded += 1
            except Exception as exc:
                # Prompt might already exist — try updating
                try:
                    langfuse.create_prompt(
                        name=name,
                        prompt=body,
                        labels=["production"],
                        is_active=True,
                    )
                    print(f"  🔄 {name} (updated)")
                    uploaded += 1
                except Exception as exc2:
                    print(f"  ❌ {name}: {exc2}")

    langfuse.flush()
    print(f"\nDone. {uploaded} prompts uploaded to Langfuse.")


if __name__ == "__main__":
    main()
